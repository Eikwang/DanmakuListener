# -*- coding: utf-8 -*-
"""视频号直播弹幕冒烟工具

用法：
    python tools/wxsp_smoke.py <房间备注名> [--duration 180]

流程：
1. 首次运行自动弹出浏览器 → 用微信扫码登录视频号管理后台（channels.weixin.qq.com）
   （需一个有视频号直播权限的微信小号——监听自己后台，只读不发送）
2. 登录成功后自动开始监听：在视频号 App 开一场直播，然后在直播间
   发弹幕/点赞/送礼/进出来对照输出
3. 登录态持久化（cookie/wechat_channels_state.json），后续免扫码
"""

import argparse
import asyncio
import sys

sys.path.insert(0, ".")

from danmaku_listener.engines.wechat_channels import WechatChannelsEngine


async def main(room_name: str, duration: float) -> int:
    eng = WechatChannelsEngine()

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}: {p.get('content')}")
        elif t == "ENTER_ROOM":
            print(f"[ENTER] {p.get('user_name')}")
        elif t == "LIKE":
            print(f"[LIKE] {p.get('user_name')} x{p.get('count')}")
        elif t == "GIFT":
            print(f"[GIFT] {p.get('user_name')} → {p.get('gift_name')} "
                  f"x{p.get('gift_count')}")
        elif t in ("LIVE_STATUS_CHANGE", "ENGINE_STATUS"):
            print(f"[{t}] {p}")
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    await eng.start(room_name)
    print(f"[listen] 监听中 {duration:.0f} 秒（首次运行请先在弹出窗口扫码登录，"
          "然后在视频号 App 开播并发弹幕/点赞）")
    await asyncio.sleep(duration)
    await eng.stop(room_name)
    print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("room_name", help="房间备注名（任意标识，如小号昵称）")
    ap.add_argument("--duration", type=float, default=180.0)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.room_name, a.duration)))
