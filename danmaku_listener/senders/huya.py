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
    MODE_MINIMIZED,
    LoginTakeoverError,
    ResidentSendSession,
)

PROFILE_DIR = "cookie/huya_login_profile"
#: headless 反检测指纹包（2026-10-09 对抗实验 1：虎牙风控识别 headless=new
#: 指纹并静默吞弹幕——headed 对照可过。注入 7 信号伪装后再验）
STEALTH_JS = """
() => {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(window, 'outerWidth', {get: () => 1280});
    Object.defineProperty(window, 'outerHeight', {get: () => 800});
    Object.defineProperty(screen, 'availWidth', {get: () => 1280});
    Object.defineProperty(screen, 'availHeight', {get: () => 760});
    Object.defineProperty(screen, 'colorDepth', {get: () => 24});
    Object.defineProperty(screen, 'pixelDepth', {get: () => 24});
    if (!window.chrome) { window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}}; }
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) => p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission}) : origQuery(p);
}
"""

INPUT_SELECTORS = ("#pub_msg_input",  # 2026-10-09 验收用户 devtools 实测（真输入框；
                   # #J_RoomChatSpeaker 是容器——此前打容器导致假 UNKNOWN）
                   "#J_RoomChatSpeaker", "input[placeholder*=弹幕]", "textarea")
BUTTON_SELECTORS = ("#msg_send_bt",  # 2026-10-09 验收用户 devtools 实测（真发送按钮）
                    "[class*=send]", 'button:has-text("发送")', ".send-btn")
ECHO_WAIT_S = 12.0

#: 进程级会话单例（虎牙 profile 独立于抖音——第二实例参数化复用同一管理器类）
_session: ResidentSendSession | None = None


def _get_session(idle_timeout_s: int, window_mode: str) -> ResidentSendSession:  # noqa: 保持 STEALTH_JS 常量供后续对抗参考
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
        mode = MODE_MINIMIZED  # 2026-10-09 回退：headless=new 指纹被虎牙风控静默吞（对比实验实证），headed minimized 为 T6 实证可用形态
        idle = 1800
        if settings is not None:
            mode = getattr(settings, "send_window_mode", mode) or mode
            idle = int(getattr(settings, "send_session_idle_timeout_seconds", idle) or idle)
        self._session = _get_session(idle, mode)

    async def send(self, room_id: str, content: str) -> SendResult:
        url = f"https://www.huya.com/{room_id}"
        # 登录转正流程（可见窗+人工登录+30s 验证宽限）可能需要数分钟——
        # action 预算放宽至 360s（默认 90s 会掐断登录窗）
        return await self._session.send(room_id, url, self._page_action(content),
                                        action_timeout_s=360.0)

    def _page_action(self, content: str):
        async def action(page, rid: str) -> SendResult:
            # 登录态检测（2026-10-09 方案 A：UDB 遮罩/登录 cookie 缺失 → 可见登录窗
            # 转正——huya 登录令牌为会话级 cookie，profile cookie 无法跨页恢复登录态）
            try:
                mask = await page.locator("#UDBSdkLgn-mask").count()
                cookies = {c["name"] for c in await page.context.cookies() if c.get("value")}
                logged = bool({"yyuid", "hicl_imid", "huya_uid"} & cookies) and not mask
            except Exception:  # noqa: BLE001  探测失败不阻断（fake page 兼容）
                logged = True
            if not logged:
                logger.info(f"[huya] room {rid} 未登录（UDB 遮罩/cookie 缺失）——弹可见登录窗转正")
                try:
                    page = await self._session.login_takeover(
                        rid, f"https://www.huya.com/{rid}",
                        ("yyuid", "hicl_imid", "huya_uid"), grace_s=30.0)
                except LoginTakeoverError as e:
                    return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                                      detail=f"登录未完成: {e}",
                                      fix_hint="重试发送将再次弹出登录窗口——请在窗口内完成登录与安全验证")
                except Exception as e:  # noqa: BLE001  会话层异常隔离
                    logger.warning(f"[huya] login takeover error: {type(e).__name__}: {str(e)[:80]}")
                    return SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value,
                                      detail=f"登录窗异常: {type(e).__name__}: {str(e)[:80]}",
                                      fix_hint="重试发送将再次弹出登录窗口")
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
            # 提交后状态观测（前移至 +0.3s——huya 提交成功后会重建聊天区节点，
            # 观测晚了读到的就是重建后的世界，2026-10-09 实测教训）
            input_after = None
            try:
                ta = page.locator("#pub_msg_input").first
                if await ta.count() > 0:
                    input_after = (await ta.input_value()).strip()
            except Exception:  # noqa: BLE001  节点已被页面重建替换——按 None 记
                input_after = None
            # F5：get_by_text 穿透 shadow DOM 回显；兜底=聊天容器 innerText 扫描
            # （虎牙 2026-10-09 实测：提交成功后节点重建致 get_by_text 假阴性——
            #   斗鱼/1688 同款第三例；innerText 扫描按行拼接仍可命中）
            deadline = time.monotonic() + ECHO_WAIT_S
            while time.monotonic() < deadline:
                try:
                    if await page.get_by_text(content).count() > 0:
                        return SendResult(SendStatus.SENT, sent_at=int(time.time()))
                    aside_text = await page.evaluate(
                        "() => { const a = document.querySelector('#js-player-asideMain');"
                        " return a ? a.innerText : ''; }")
                    if content in (aside_text or ""):
                        return SendResult(SendStatus.SENT, sent_at=int(time.time()))
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(1.5)
            state = ("空(已提交——回显与观测均未命中)" if input_after == ""
                     else ("有内容(提交未触发)" if input_after else "无法读取(节点已重建)"))
            return SendResult(SendStatus.UNKNOWN, SendRejectReason.SEND_TIMEOUT.value,
                              detail=f"无回显无显式错误；提交后输入框={state}（虎牙冷却/虚拟列表可能）")
        return action
