"""抖音 profile DOM sender（AutoDanmu M0 实测结论落地）

关键约束（2026-10-07 实测）：
- **必须有头窗口**（headless 下聊天面板不出现——bd_ticket_guard 会话对 headless 敏感）
- 登录态在 cookie/douyin_profile persistent profile（扫码一次，指纹绑定）
- 输入框=div[contenteditable=true]（editor-kit-container），发送=[class*=send] 图标按钮
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

from danmaku_listener.contract.models import SendRejectReason, SendStatus
from danmaku_listener.senders.base import BaseSender, SendResult


class DouyinProfileSender(BaseSender):
    """抖音发送器：headed persistent context → 直播间 DOM 发送"""

    platform = "douyin"

    SEND_URL = "https://live.douyin.com/{room_id}"
    INPUT_SELECTORS = ["div[contenteditable=true]"]
    BUTTON_SELECTORS = ["[class*=send]", 'button:has-text("发送")']
    PROFILE_DIR = "cookie/douyin_profile"

    def __init__(self, profile_dir: Optional[str] = None, headed: bool = True):
        self._profile_dir = profile_dir or self.PROFILE_DIR
        self._headed = headed  # 抖音聊天会话 headless 敏感——默认有头

    async def send(self, room_id: str, content: str) -> SendResult:
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as pw:
                context = await pw.chromium.launch_persistent_context(
                    self._profile_dir,
                    headless=not self._headed,
                    viewport={"width": 1280, "height": 800},
                    args=["--disable-blink-features=AutomationControlled",
                          "--disable-setuid-sandbox",
                          "--hide-crash-restore-bubble"],
                )
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    try:
                        await page.goto(self.SEND_URL.format(room_id=room_id),
                                        timeout=45000, wait_until="domcontentloaded")
                    except Exception as e:  # noqa: BLE001
                        return SendResult(SendStatus.UNKNOWN, SendRejectReason.SEND_TIMEOUT.value,
                                          detail=f"goto: {type(e).__name__}")
                    await asyncio.sleep(3)
                    input_sel = None
                    for sel in self.INPUT_SELECTORS:
                        try:
                            loc = page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                input_sel = sel; break
                        except Exception:  # noqa: BLE001
                            continue
                    if input_sel is None:
                        # 登录态失效（headless/指纹/过期）——诊断截图+如实 FAIL
                        try:
                            await page.screenshot(path="persistence_data/douyin-send-blocked.png")
                        except Exception:  # noqa: BLE001
                            pass
                        return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                                          fix_hint="聊天面板未出现——profile 登录态失效，重跑 douyin_login 扫码",
                                          docs_anchor="docs/ops/send-runbook.md")
                    await page.locator(input_sel).first.fill(content)
                    btn_sel = None
                    for sel in self.BUTTON_SELECTORS:
                        try:
                            if await page.locator(sel).first.count() > 0:
                                btn_sel = sel; break
                        except Exception:  # noqa: BLE001
                            continue
                    if btn_sel:
                        try:
                            await page.locator(btn_sel).first.click(timeout=5000, force=True)
                        except Exception:  # noqa: BLE001
                            await page.locator(input_sel).first.press("Enter")
                    else:
                        await page.locator(input_sel).first.press("Enter")
                    await asyncio.sleep(2.5)
                    echo_deadline = time.monotonic() + 8  # 1688 实证：聊天列表渲染延迟可达数秒
                    sent_echo = False
                    while time.monotonic() < echo_deadline:
                        if content in await page.content():
                            sent_echo = True; break
                        await asyncio.sleep(1.5)
                    if sent_echo:
                        return SendResult(SendStatus.SENT, sent_at=int(time.time()))
                    return SendResult(SendStatus.UNKNOWN, SendRejectReason.SEND_TIMEOUT.value,
                                      detail="无回显无显式错误（虚拟列表/慢渲染）")
                finally:
                    try:
                        await context.close()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[douyin] send error: {type(e).__name__}: {str(e)[:100]}")
            return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                              detail=f"{type(e).__name__}: {str(e)[:100]}")
