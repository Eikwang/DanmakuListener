# -*- coding: utf-8 -*-
"""视频号直播弹幕冒烟工具（无头常驻版——与系统监听同引擎同逻辑）

用法：
    python tools/wxsp_smoke.py <房间备注名> [--duration 180] [--dump-all]

流程：
1. 默认**无头运行**（无浏览器窗口——2026-10-03 无头常驻模式，系统运行即监听）。
   登录态过期时自动弹出可见浏览器窗口 → 用微信扫码登录视频号管理后台
   （需一个有视频号直播权限的微信小号——监听自己后台，只读不发送）
   → 扫完自动切回无头继续监听（cookie 热切换实测通过）。
2. 在视频号 App 开播，然后在直播间发弹幕/点赞/送礼/关注/进出对照输出。
3. 登录态持久化（cookie/wxsp_profile），后续免扫码。

与系统监听（AUTOlive）的一致性：
- 同引擎（danmaku_listener.engines.wechat_channels），消息解析完全一致
- 差异仅在消费端呈现：系统端 LIKE 走 5s 聚合进对话链（"张三、李四 等 N 人
  点赞"），脚本端逐条打印（细粒度验证昵称/wording 更直观）
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.wechat_channels import WechatChannelsEngine


async def main(room_name: str, duration: float, dump_all: bool) -> int:
    dump_fh = open("wxsp_dump.jsonl", "a", encoding="utf-8") if dump_all else None
    n_raw = 0

    def raw_hook(body):
        nonlocal n_raw
        n_raw += 1
        dump_fh.write(json.dumps({"ts": time.time(), "kind": "raw",
                                  "data": body},
                                 ensure_ascii=False, default=str) + "\n")
        dump_fh.flush()

    # raw_hook 构造传参（事后属性赋值在引擎异步启动前存在时序风险）
    eng = WechatChannelsEngine(raw_hook=raw_hook if dump_all else None)

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}: {p.get('content')}")
        elif t == "ENTER_ROOM":
            print(f"[ENTER] {p.get('user_name')}")
        elif t == "LIKE":
            # 新版点赞（20122）：payload.content = "赞了直播"（wording）
            wording = f" ({p.get('content')})" if p.get("content") else ""
            print(f"[LIKE] {p.get('user_name') or '有人'}{wording} x{p.get('count')}")
        elif t == "GIFT":
            value = f" 价值{p.get('gift_value')}(微信豆)" if p.get("gift_value") else ""
            print(f"[GIFT] {p.get('user_name')} → {p.get('gift_name')} "
                  f"x{p.get('gift_count')}{value}")
        elif t == "SOCIAL":
            action = p.get("action") or ""
            label = {"follow": "关注了主播"}.get(action, action)
            print(f"[SOCIAL] {p.get('user_name')} {label}"
                  + (f" ({p.get('content')})" if p.get("content") else ""))
        elif t in ("LIVE_STATUS_CHANGE", "ENGINE_STATUS"):
            print(f"[{t}] {p}")
        else:
            print(f"[{t}] {p}")

    eng.on_message(on_msg)
    await eng.start(room_name)
    print(f"[listen] 无头监听中 {duration:.0f} 秒（登录态过期时会自动弹出可见"
          "窗口，请扫码；扫码后自动切回无头）。请在视频号 App 开播并发"
          "弹幕/点赞/送礼/关注" + ("（live/msg 原始响应 → wxsp_dump.jsonl）"
                                   if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(room_name)
    if dump_fh:
        dump_fh.close()
        print(f"[done] 原始响应共 {n_raw} 条 → wxsp_dump.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("room_name", help="房间备注名（任意标识，如小号昵称）")
    ap.add_argument("--duration", type=float, default=180.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="live/msg 原始响应写 wxsp_dump.jsonl（形态校准）")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.room_name, a.duration, a.dump_all)))
