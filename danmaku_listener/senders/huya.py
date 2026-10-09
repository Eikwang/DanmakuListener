"""虎牙常驻会话 sender（AutoDanmu T6/X1——ResidentSendSession 第二实例）

形态：huya_login_profile persistent + headed minimized（虎牙无 headless 探针证据——
保守用有头最小化窗口；ENG-8 flag 族由会话管理器统一注入）。冷却约束（普通账号
~30s，10-14s 实测失败、35s 补发全过）由 guard 的 per-platform 覆写内置默认
{"huya": 35} 兜底（senders/guard.py）——sender 内不再自设限速。

配方（M0 补发卡 found 字段）：`#pub_msg_input` + `[class*=send]`；
候选 .send-btn 实测不可见。登录失效回执同快手/斗鱼（DX-D1 CLI 重登）。
"""
from __future__ import annotations

import asyncio
import time

from loguru import logger

from danmaku_listener.contract.models import SendRejectReason, SendStatus
from danmaku_listener.senders.base import BaseSender, SendResult
from danmaku_listener.senders.resident_session import (
    MODE_HEADLESS_NEW,
    ResidentSendSession,
)

PROFILE_DIR = "cookie/huya_login_profile"
INPUT_SELECTORS = ("#pub_msg_input",  # 2026-10-09 验收用户 devtools 实测（真输入框；
                   # #J_RoomChatSpeaker 是容器——此前打容器导致假 UNKNOWN）
                   "#J_RoomChatSpeaker", "input[placeholder*=弹幕]", "textarea")
BUTTON_SELECTORS = ("#msg_send_bt",  # 2026-10-09 验收用户 devtools 实测（真发送按钮）
                    "[class*=send]", 'button:has-text("发送")', ".send-btn")
ECHO_WAIT_S = 12.0

#: 进程级会话单例（虎牙 profile 独立于抖音——第二实例参数化复用同一管理器类）
_session: ResidentSendSession | None = None


def _get_session(idle_timeout_s: int, window_mode: str) -> ResidentSendSession:
    global _session
    if _session is None or _session._window_mode != window_mode:
        _session = ResidentSendSession(
            "huya-send", PROFILE_DIR,
            # 2026-10-08 验收用户裁定：默认完全后台无痕（原 headed minimized 可见最小化）；
            # headless=new 完整 Blink 指纹+--mute-audio 静音；INI send_window_mode 可覆写
            window_mode=window_mode, idle_timeout_s=idle_timeout_s)
    return _session


class HuyaResidentSender(BaseSender):
    """虎牙常驻会话 sender（headless_new 完全后台；profile 持久会话）"""

    platform = "huya"

    def __init__(self, settings=None):
        mode = MODE_HEADLESS_NEW  # 2026-10-08 验收裁定：默认完全后台（原 minimized）
        idle = 1800
        if settings is not None:
            mode = getattr(settings, "send_window_mode", mode) or mode
            idle = int(getattr(settings, "send_session_idle_timeout_seconds", idle) or idle)
        self._session = _get_session(idle, mode)

    async def send(self, room_id: str, content: str) -> SendResult:
        url = f"https://www.huya.com/{room_id}"
        return await self._session.send(room_id, url, self._page_action(content))

    def _page_action(self, content: str):
        async def action(page, rid: str) -> SendResult:
            # 渲染等待：goto 返回后 SPA 输入框延迟挂载（1s 即查会假阴性）
            inp = None
            for _ in range(10):
                for sel in INPUT_SELECTORS:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            inp = loc
                            break
                    except Exception:  # noqa: BLE001
                        continue
                if inp is not None:
                    break
                await asyncio.sleep(2)
            if inp is None:
                return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                                  fix_hint="虎牙发送输入框未出现（登录态失效）——重新登录："
                                           "python -m danmaku_listener.engines.send_login huya [room_id]（DX-D1）",
                                  docs_anchor="docs/ops/send-runbook.md")
            await inp.click(timeout=10_000)
            await asyncio.sleep(0.4)
            await inp.press_sequentially(content, delay=40)
            await asyncio.sleep(0.3)
            sent_btn = None
            for sel in BUTTON_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        sent_btn = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            try:
                if sent_btn is not None:
                    await sent_btn.click(timeout=5_000)
                else:
                    await inp.press("Enter")
            except Exception:  # noqa: BLE001
                await inp.press("Enter")
            await asyncio.sleep(2)
            # 提交后状态观测（评审 F-B 同款——UNKNOWN 分流依据）：
            # 内层 #pub_msg_input 清空=框架已受理提交（送达未证）；有内容=提交未触发
            input_after = None
            try:
                ta = page.locator("#pub_msg_input").first
                if await ta.count() > 0:
                    input_after = (await ta.input_value()).strip()
            except Exception:  # noqa: BLE001
                pass
            # F5：get_by_text 穿透 shadow DOM 回显
            deadline = time.monotonic() + ECHO_WAIT_S
            while time.monotonic() < deadline:
                try:
                    if await page.get_by_text(content).count() > 0:
                        return SendResult(SendStatus.SENT, sent_at=int(time.time()))
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(1.5)
            state = "空(已提交或输入未进真输入框——按 #pub_msg_input 直打复验)" if input_after == "" else ("有内容(提交未触发)" if input_after else "无法读取")
            return SendResult(SendStatus.UNKNOWN, SendRejectReason.SEND_TIMEOUT.value,
                              detail=f"无回显无显式错误；提交后输入框={state}（虎牙冷却/虚拟列表可能）")
        return action
