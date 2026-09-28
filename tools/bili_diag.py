"""B站弹幕流诊断：统计 60 秒内收到的全部上游 cmd 分布与 DANMU 解析结果

用法（先停掉 serve 进程，避免同房间第二连接被 B站哑化）：
    python tools/bili_diag.py 27695110

输出：
- 每个上游 cmd 的出现次数（原始流真实分布）
- DANMU_MSG 解析成功/失败计数与失败样本（定位映射缺陷）
- 压缩协议分布（proto 2/3 占比）
- 解压/JSON 错误计数
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets
from loguru import logger

from danmaku_listener.engines.protocol import bilibili_codec as codec
from danmaku_listener.engines.protocol.bilibili import DanmuInfoFetcher


async def main(room_id: int, duration: float, cookie_file: str = "") -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    fetcher = DanmuInfoFetcher(cookie_file=cookie_file or None)
    ctx = await fetcher.connect_context(room_id)
    token = ctx.get("token", "")
    hosts = [h for h in (ctx.get("host_list") or []) if h.get("wss_port")]
    assert token and hosts, "token/host_list 获取失败"
    print(f"ctx: uid={ctx.get('uid')} buvid={'set' if ctx.get('buvid') else 'MISSING'} "
          f"real_room_id={ctx.get('real_room_id')}", file=sys.stderr)
    url = f"wss://{hosts[0]['host']}:{hosts[0]['wss_port']}/sub"

    stats = {"frames": 0, "proto": {}, "cmds": {}, "danmu_ok": 0, "danmu_fail": 0,
             "danmu_fail_samples": [], "decompress_err": 0, "json_err": 0}

    ws_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://live.bilibili.com",
        "Pragma": "no-cache",
    }
    async with websockets.connect(url, ping_interval=None, additional_headers=ws_headers) as ws:
        await ws.send(codec.encode_packet(codec.OP_AUTH, codec.build_auth_body(
            ctx.get("real_room_id", room_id), token,
            uid=ctx.get("uid", 0), buvid=ctx.get("buvid", ""),
            queue_uuid=uuid.uuid4().hex[:8])))
        print(f"auth sent to {url}", file=sys.stderr)
        end = asyncio.get_event_loop().time() + duration
        last_hb = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() < end:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.5, end - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                break
            stats["frames"] += 1
            try:
                packets = codec.decode_packets(raw if isinstance(raw, bytes) else raw.encode())
            except Exception as e:
                stats["decode_err"] = stats.get("decode_err", 0) + 1
                stats["decode_err_detail"] = f"{type(e).__name__}: {e}"[:100]
                continue
            for proto, op, body in packets:
                stats["proto"][proto] = stats["proto"].get(proto, 0) + 1
                if op in (3, 8):
                    continue  # 心跳应答/认证应答
                bodies = []
                if proto in (codec.PROTOCOL_ZLIB, codec.PROTOCOL_BROTLI):
                    try:
                        bodies = list(codec.decompress(proto, body))
                    except Exception as e:
                        stats["decompress_err"] += 1
                        stats["decompress_err_detail"] = f"{type(e).__name__}: {e}"[:100]
                        continue
                else:
                    bodies = [(op, body)]
                for _iop, ib in bodies:
                    try:
                        doc = json.loads(ib.decode("utf-8"))
                    except Exception:
                        stats["json_err"] += 1
                        continue
                    cmd = doc.get("cmd", "?")
                    stats["cmds"][cmd] = stats["cmds"].get(cmd, 0) + 1
                    if cmd == "DANMU_MSG":
                        info_list = doc.get("info") or []
                        mapped = codec.map_upstream_message("DANMU_MSG", info_list, 0, 0)
                        if mapped:
                            stats["danmu_ok"] += 1
                            if len(stats["danmu_fail_samples"]) == 0:
                                stats.setdefault("danmu_ok_sample",
                                                 mapped["payload"].get("content", "")[:30])
                        else:
                            stats["danmu_fail"] += 1
                            if len(stats["danmu_fail_samples"]) < 3:
                                stats["danmu_fail_samples"].append(json.dumps(info_list, ensure_ascii=False)[:200])
            if asyncio.get_event_loop().time() - last_hb > 30:
                await ws.send(codec.encode_packet(codec.OP_HEARTBEAT))
                last_hb = asyncio.get_event_loop().time()

    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    import argparse
    import uuid

    parser = argparse.ArgumentParser()
    parser.add_argument("room_id", type=int)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--cookie", default="", help="登录 cookie 文件（storage_state/字符串），完整弹幕流验证")
    a = parser.parse_args()
    asyncio.run(main(a.room_id, a.duration, a.cookie))
