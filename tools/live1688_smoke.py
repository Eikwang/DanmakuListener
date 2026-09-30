# -*- coding: utf-8 -*-
"""1688 直播弹幕冒烟工具（受控页面引擎版——旧 mtop 路线工具 alive1688_smoke.py 已废弃删除）

用法：
    python tools/live1688_smoke.py <feedId 或直播间链接> [--duration 300] [--dump-all]

feedId 场次级——下播失效，需重新复制直播间链接。
首次运行如需登录会自动弹出浏览器（阿里账号扫码）。
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.live1688 import Live1688Engine, extract_feed_id


async def main(spec: str, duration: float, dump_all: bool) -> int:
    eng = Live1688Engine()
    dump_fh = None
    n_raw = 0
    if dump_all:
        dump_fh = open("1688_dump.jsonl", "a", encoding="utf-8")

        def raw_hook(data):
            nonlocal n_raw
            n_raw += 1
            dump_fh.write(json.dumps({"ts": time.time(), "kind": "raw",
                                      "data": data},
                                     ensure_ascii=False, default=str) + "\n")
            dump_fh.flush()

        eng._raw_hook = raw_hook

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}: {p.get('content')}")
        elif t == "ROOM_STATS":
            print(f"[ROOM_STATS] {p}")
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    await eng.start(spec)
    print(f"[listen] {spec[:60]} 监听中 {duration:.0f} 秒——请发弹幕！"
          + ("（DOM 条目/pull 响应 → 1688_dump.jsonl）" if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(spec)
    if dump_fh:
        dump_fh.close()
        print(f"[done] 原始数据共 {n_raw} 条 → 1688_dump.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="feedId / 1688 直播间链接")
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="DOM 弹幕条目+pull 原始响应写 1688_dump.jsonl")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration, a.dump_all)))
