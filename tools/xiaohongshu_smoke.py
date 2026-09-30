# -*- coding: utf-8 -*-
"""小红书直播弹幕冒烟工具

用法：
    python tools/xiaohongshu_smoke.py <room_id 或直播间页链接> [--duration 90]

验证受控页面 WS 帧拦截通道；监听期间到直播间发弹幕/点赞观察输出。
首次运行会保存设备 cookie 到 cookie/xhs_profile。
"""

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.xiaohongshu import (
    XiaohongshuEngine,
    extract_room_id,
)


async def main(spec: str, duration: float) -> int:
    room_id = extract_room_id(spec)
    print(f"[spec] room_id = {room_id}")
    eng = XiaohongshuEngine()

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
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    await eng.start(room_id)
    print(f"[listen] 监听中 {duration:.0f} 秒——请去直播间发弹幕/点赞！")
    await asyncio.sleep(duration)
    await eng.stop(room_id)
    print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="room_id / 小红书直播间页链接")
    ap.add_argument("--duration", type=float, default=90.0)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration)))
