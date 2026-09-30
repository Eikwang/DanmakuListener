# -*- coding: utf-8 -*-
"""京东直播弹幕冒烟工具

用法：
    python tools/jd_smoke.py "<京东直播间页链接>" [--duration 120] [--dump-all]

--dump-all：把页内 WS 的业务特征帧（含未映射）写 jd_raw.jsonl，
供咚咚 IM 帧结构校准。运行期间到直播间发弹幕/进场观察输出。
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.jd import JDProtocolEngine


async def main(spec: str, duration: float, dump_all: bool) -> int:
    eng = JDProtocolEngine()
    dump_fh = None
    n_raw = 0
    if dump_all:
        dump_fh = open("jd_raw.jsonl", "a", encoding="utf-8")

        def raw_hook(obj):
            nonlocal n_raw
            n_raw += 1
            dump_fh.write(json.dumps({"ts": time.time(), "obj": obj},
                                     ensure_ascii=False, default=str) + "\n")
            dump_fh.flush()

        eng._raw_hook = raw_hook

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}: {p.get('content')}")
        elif t == "ENTER_ROOM":
            print(f"[ENTER] {p.get('user_name')}")
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    await eng.start(spec)
    print(f"[listen] 监听中 {duration:.0f} 秒——请去直播间发弹幕！"
          + ("（业务特征帧 → jd_raw.jsonl）" if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(spec)
    if dump_fh:
        dump_fh.close()
        print(f"[done] 业务特征帧共 {n_raw} 条 → jd_raw.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="京东直播间页链接（务必加引号——URL 含 &）")
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="dump 业务特征帧到 jd_raw.jsonl（结构校准）")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration, a.dump_all)))
