# -*- coding: utf-8 -*-
"""1688 直播弹幕冒烟/采样工具

用途：
1. 验证 1688 直播间 powermsg 通道连通性（凭证/topic/轮询）
2. 在弹幕活跃时段抓取聊天消息原始样本（JSON 对象 dump 到 stdout/文件），
   供 1688 引擎弹幕映射校准（当前映射按淘宝同构假设——subType/nick/content）

用法：
    python tools/alive1688_smoke.py <feedId 或直播间链接> [--duration 120] [--dump samples.jsonl]
"""

import argparse
import asyncio
import json
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, ".")

import danmaku_listener.engines.protocol.alibaba1688 as ab
from danmaku_listener.engines.protocol.mtop import MtopClient, parse_base64_mixed_message


async def main(feed: str, duration: float, dump_path: str) -> int:
    eng = ab.Alibaba1688Engine()
    live_id = eng._extract_live_id(feed)
    topic, cred = await asyncio.wait_for(
        eng._fetch_credentials(feed), timeout=140)
    print(f"[cred] topic={topic} tk={cred.m_h5_tk[:14]}...")

    import requests as rq
    s = rq.Session()
    from danmaku_listener.engines.protocol.taobao import UA as _UA
    s.headers.update({"User-Agent": _UA})
    for k, v in cred.cookies.items():
        s.cookies.set(k, v)
    from danmaku_listener.engines.protocol.taobao import UA as _UA2
    client = MtopClient(eng.MTOP_DOMAIN, _UA2, s)

    offset = "0"
    stats = {"pull": 0, "objs": 0, "chat_like": 0, "unknown_keys": {}}
    dump_fh = open(dump_path, "a", encoding="utf-8") if dump_path else None
    headers = {"x-biz-type": "powermsg", "x-biz-info": "namespace=1",
               "referer": eng.PAGE_ORIGIN + "/", "origin": eng.PAGE_ORIGIN}
    end = time.monotonic() + duration
    loop = asyncio.get_running_loop()

    while time.monotonic() < end:
        data = {"topic": topic, "offset": offset,
                "pagesize": eng.POWERMSG_PAGESIZE, "tag": "", "bizcode": 1,
                "sdkversion": eng.POWERMSG_SDK_VERSION, "role": 3}
        try:
            result = await loop.run_in_executor(
                None, client.get, 'mtop.taobao.powermsg.h5.msg.pullnativemsg',
                '1.0', '12574478', data, cred.m_h5_tk, headers)
        except Exception as e:
            print(f"[pull err] {type(e).__name__}: {str(e)[:60]}")
            await asyncio.sleep(5)
            continue
        stats["pull"] += 1
        tlist = (result.get("data") or {}).get("timestampList") or []
        if tlist:
            offset = tlist[-1].get("offset", offset)
        for td in tlist:
            b64 = td.get("data", "")
            if not b64:
                continue
            try:
                objs, _ = parse_base64_mixed_message(b64)
            except Exception:
                continue
            for o in objs:
                if not isinstance(o, dict):
                    continue
                stats["objs"] += 1
                keys = tuple(sorted(o.keys()))
                is_chat = ("content" in o and ("nick" in o or "userName" in o
                           or "subType" in o))
                if is_chat:
                    stats["chat_like"] += 1
                    print(f"[聊天形态] {json.dumps(o, ensure_ascii=False)[:200]}")
                else:
                    stats["unknown_keys"][keys] = stats["unknown_keys"].get(keys, 0) + 1
                if dump_fh:
                    dump_fh.write(json.dumps({"ts": time.time(), "obj": o,
                                              "keys": list(keys)},
                                             ensure_ascii=False,
                                             default=str) + "\n")
        await asyncio.sleep(5)

    if dump_fh:
        dump_fh.close()
    print(f"[done] pull={stats['pull']} objs={stats['objs']} "
          f"chat_like={stats['chat_like']}")
    print("unknown keys 分布（校准目标）:")
    for k, n in sorted(stats["unknown_keys"].items(), key=lambda x: -x[1])[:10]:
        print(f"  x{n}: {list(k)}")
    if dump_path:
        print(f"样本已 dump: {dump_path}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("feed")
    p.add_argument("--duration", type=float, default=120.0)
    p.add_argument("--dump", default="1688_samples.jsonl")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.feed, a.duration, a.dump)))
