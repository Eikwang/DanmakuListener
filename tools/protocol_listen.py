"""协议直连引擎测试助手：不经过 listener 旧路由，直接驱动阶段 1-4 协议引擎

用法：
    python tools/protocol_listen.py bilibili 23058 [--duration 60]
    python tools/protocol_listen.py douyu   99999  [--duration 60]

说明：
- 阶段 1-4 协议引擎尚未接入旧 listener 路由（阶段 6 注册表已就绪但 serve 集成待接），
  本脚本绕过旧路由直接驱动新引擎，输出契约 v1 线格式 JSON 到 stdout
- 真实连接失败时按契约输出 GAP/错误信息（stderr），并自动进入慢速重试
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

_ENGINES = {
    "bilibili": BilibiliProtocolEngine,
    "douyu": DouyuProtocolEngine,
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="协议直连引擎测试助手（阶段 1-4）")
    parser.add_argument("platform", choices=sorted(_ENGINES.keys()))
    parser.add_argument("room_id", help="房间 ID")
    parser.add_argument("--duration", type=float, default=60.0, help="测试时长（秒）")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO")

    engine = _ENGINES[args.platform]()
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
