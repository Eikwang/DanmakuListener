# -*- coding: utf-8 -*-
"""淘宝直播弹幕冒烟工具（mtop 双通道；契约消息 wire dump）

用法：
    python tools/taobao_smoke.py <直播间链接> [--duration 300] [--dump-all]
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine


async def main(spec: str, duration: float, dump_all: bool) -> int:
    eng = TaobaoWebProtocolEngine()
    dump_fh = None
    n_dump = 0
    if dump_all:
        dump_fh = open("taobao_dump.jsonl", "a", encoding="utf-8")

    def on_msg(m):
        nonlocal n_dump
        print(f"[{m.get('type')}] {json.dumps(m.get('payload') or {}, ensure_ascii=False)[:150]}")
        if dump_fh:
            dump_fh.write(json.dumps({"ts": time.time(), "kind": "wire",
                                      "data": m},
                                     ensure_ascii=False, default=str) + "\n")
            dump_fh.flush()
            n_dump += 1

    eng.on_message(on_msg)
    await eng.start(spec)
    print(f"[listen] 监听中 {duration:.0f} 秒——请发弹幕！"
          + ("（契约消息 → taobao_dump.jsonl）" if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(spec)
    if dump_fh:
        dump_fh.close()
        print(f"[done] 契约消息共 {n_dump} 条 → taobao_dump.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="淘宝直播间链接")
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="契约消息写 taobao_dump.jsonl")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration, a.dump_all)))
