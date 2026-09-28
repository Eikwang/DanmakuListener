"""协议直连引擎测试助手：不经过 listener 旧路由，直接驱动阶段 1-4 协议引擎

用法：
    python tools/protocol_listen.py bilibili 23058   [--duration 60] [--cookie cookie/bilibili_storage_state.json]
    python tools/protocol_listen.py douyu   99999    [--duration 60]
    python tools/protocol_listen.py kuaishou <主播ID> [--duration 60]  # 需登录态 storage_state

说明：
- 本脚本绕过 web 路由直接驱动协议引擎，输出契约 v1 线格式 JSON 到 stdout
- 真实连接失败时按契约输出 GAP/错误信息（stderr），并自动进入慢速重试
- 快手 token 走登录态浏览器获取（kuaishou_login 闭环产物）
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from danmaku_listener.engines.protocol.bilibili import BilibiliProtocolEngine
from danmaku_listener.engines.protocol.douyu import DouyuProtocolEngine
from danmaku_listener.engines.protocol.huya import HuyaProtocolEngine
from danmaku_listener.engines.protocol.kuaishou import KuaishouProtocolEngine

_ENGINES = {
    "bilibili": BilibiliProtocolEngine,
    "douyu": DouyuProtocolEngine,
    "huya": HuyaProtocolEngine,
    "kuaishou": KuaishouProtocolEngine,
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="协议直连引擎测试助手（阶段 1-4）")
    parser.add_argument("platform", choices=sorted(_ENGINES.keys()))
    parser.add_argument("room_id", help="房间 ID")
    parser.add_argument("--duration", type=float, default=60.0, help="测试时长（秒）")
    parser.add_argument("--cookie", default="", help="登录态 storage_state（bilibili/kuaishou）")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO")

    kwargs = {}
    if args.cookie and args.platform in ("bilibili", "kuaishou"):
        kwargs["cookie_file"] = args.cookie
    engine = _ENGINES[args.platform](**kwargs)
    t0 = time.perf_counter()
    first = True
    count = 0

    async def on_message(data: dict):
        nonlocal first, count
        if first:
            print(f"[tthw] first message after {(time.perf_counter() - t0) * 1000:.0f} ms", file=sys.stderr)
            first = False
        count += 1
        print(json.dumps(data, ensure_ascii=False), flush=True)

    engine.on_message(on_message)
    await engine.start(args.room_id)
    print(f"[listening] {args.platform}:{args.room_id} for {args.duration}s (Ctrl+C 停止)", file=sys.stderr)
    try:
        await asyncio.sleep(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        await engine.stop(args.room_id)
        print(f"[done] {count} messages in {args.duration}s", file=sys.stderr)
    return 0 if count > 0 else 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
