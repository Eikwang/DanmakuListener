# -*- coding: utf-8 -*-
"""小红书直播弹幕冒烟工具

用法：
    python tools/xiaohongshu_smoke.py <room_id 或直播间页链接> [--duration 90] [--dump-all]

--dump-all：把监听期间解析出的全部 customData（含未映射类型）写 xhs_raw.jsonl，
供礼物/点赞等消息形态校准。跑之前先到直播间发弹幕、点赞、送礼物。
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.xiaohongshu import XiaohongshuEngine


async def main(spec: str, duration: float, dump_all: bool) -> int:
    eng = XiaohongshuEngine()
    dump_fh = None
    n_raw = 0
    if dump_all:
        dump_fh = open("xhs_raw.jsonl", "a", encoding="utf-8")

        def raw_hook(cd):
            nonlocal n_raw
            n_raw += 1
            dump_fh.write(json.dumps({"ts": time.time(), "cd": cd},
                                     ensure_ascii=False, default=str) + "\n")
            dump_fh.flush()

        eng._raw_hook = raw_hook

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}: {p.get('content')}")
        elif t == "LIKE":
            print(f"[LIKE] {p.get('user_name')} x{p.get('count')}")
        elif t == "GIFT":
            print(f"[GIFT] {p.get('user_name')} → {p.get('gift_name')} x{p.get('gift_count')}")
        elif t == "ENTER_ROOM":
            print(f"[ENTER] {p.get('user_name')}")
        elif t == "SOCIAL":
            print(f"[FOLLOW] {p.get('user_name')}")
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    # start 传原始 spec：链接形态保留 xsec_token 等风控参数（引擎内部提取 room_id）
    await eng.start(spec)
    print(f"[listen] 监听中 {duration:.0f} 秒——请发弹幕/点赞/送礼物！"
          + ("（全部 customData → xhs_raw.jsonl）" if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(spec)
    if dump_fh:
        dump_fh.close()
        print(f"[done] raw customData 共 {n_raw} 条 → xhs_raw.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="room_id / 小红书直播间页链接")
    ap.add_argument("--duration", type=float, default=90.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="dump 全部 customData 到 xhs_raw.jsonl（形态校准）")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration, a.dump_all)))
