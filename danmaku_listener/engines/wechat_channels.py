"""视频号受控后台引擎（阶段 5）

路线：受控浏览器打开官方直播管理后台，网络层拦截抓取（wxlivespy 验证的路线）。
与旧注入路线的本质区别：单页面、网络层拦截（response 监听）、无 DOM 遍历注入。

- 每直播间一个独立 BrowserContext 页面（崩溃不扩散）
- 登录态 storageState 持久化（cookie/ 目录）；过期 → NEEDS_LOGIN（interactive_login 载荷）
- 有界会话：生命周期上限（默认 4h）事件驱动重建，前后发 SYSTEM_STATUS（契约 v1）
- 部署前验证项：同账号多 BrowserContext 并行的风控实测（计划 Open Question）

后台页面/接口结构以**实测校准为准**（微信更新可能改变页面），接口名集中定义于
`BACKEND_URL` / `FEED_API_PATTERN`，变更时只需改此处（风控手册同步）。
"""

import asyncio
import base64
import io
import json
import qrcode
import time
from typing import Any, Callable, Dict, Optional

from loguru import logger

from danmaku_listener.contract import Category, SystemType
from danmaku_listener.contract.legacy import unified_to_legacy  # noqa: F401  过渡桥接
from danmaku_listener.contract.models import (
    Envelope,
    FailureInfo,
    InteractiveLogin,
    NeedsLoginPayload,
    UnifiedMessage,
)
from danmaku_listener.engines.base import BaseEngine

BACKEND_URL = "https://channels.weixin.qq.com/platform/live/liveBuild"
FEED_API_PATTERN = "channels.weixin.qq.com"  # 网络层拦截的域名锚点（实测校准项）
SESSION_LIFETIME_SECONDS = 14400  # 4 小时（契约 v1 有界会话）


class WechatChannelsEngine(BaseEngine):
    """视频号受控后台引擎"""

    platform = "wechat_channels"

    def __init__(self, state_store=None, headless: bool = True, cookie_dir: str = "./cookie",
                 session_lifetime: int = SESSION_LIFETIME_SECONDS):
        super().__init__(state_store=state_store)
        self._headless = headless
        self._cookie_dir = cookie_dir
        self._session_lifetime = session_lifetime
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}
        self._last_status_emitted: Dict[str, float] = {}

    @property
    def engine_id(self) -> str:
        return "controlled:wechat_channels"

    # ---- 公开契约 ----

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(self._run_room(room_id), name=f"wxsp-room-{room_id}")

    async def stop(self, room_id: str) -> None:
        self._stop_flags[room_id] = True
        task = self._room_tasks.pop(room_id, None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def restart(self, room_id: str) -> None:
        """仅重启该房间任务（契约 I）"""
        await self.stop(room_id)
        await self.start(room_id)

    # ---- 房间任务：有界会话循环 ----

    async def _run_room(self, room_id: str) -> None:
        """有界会话主循环：单页面生命周期到期后事件驱动重建（替代全局定时重启）"""
        while not self._stop_flags.get(room_id):
            session_start = int(time.time())
            try:
                await self._run_session(room_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[wxsp] room {room_id} session error: {e}")
                await self._emit_session_event(room_id, detail=f"session error: {e}")
            if self._stop_flags.get(room_id):
                return
            # 有界会话到期或异常退出：重建前后发 SYSTEM_STATUS（契约验收语义）
            elapsed = int(time.time()) - session_start
            await self._emit_session_event(room_id, detail=f"session rebuilt after {elapsed}s")
            await asyncio.sleep(5)

    async def _run_session(self, room_id: str) -> None:
        """单次有界会话：浏览器打开后台 → 拦截弹幕接口 → 生命周期上限退出"""
        from playwright.async_api import async_playwright

        deadline = time.monotonic() + self._session_lifetime
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self._headless)
            try:
                context = await browser.new_context(
                    storage_state=self._storage_state_path(),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                # 网络层拦截：后台弹幕接口响应（接口结构实测校准项）
                page.on("response", lambda r: asyncio.create_task(self._on_response(room_id, r)))

                await page.goto(BACKEND_URL, wait_until="domcontentloaded")
                if "login" in page.url or "scan" in page.url:
                    await self._emit_needs_login(room_id)
                    await self._wait_for_login(page, room_id)

                # 有界会话读循环：到期/停止信号退出（重建由外层负责）
                while time.monotonic() < deadline and not self._stop_flags.get(room_id):
                    await asyncio.sleep(2)
                    self.mark_received(room_id, int(time.time()))
            finally:
                await browser.close()

    async def _on_response(self, room_id: str, response) -> None:
        """网络层拦截：弹幕接口响应 → 契约消息（解析函数标注实测校准项）"""
        if FEED_API_PATTERN not in response.url:
            return
        try:
            body = await response.json()
        except Exception:
            return
        # 后台弹幕接口字段以实测为准（v1 透传结构化样本供校准）：
        payload_list = body.get("data", {}).get("commentList") or []
        for item in payload_list:
            nickname = item.get("nickname", "")
            content = item.get("content", "")
            if not content:
                continue
            seq = self.next_seq(room_id)
            ts = int(time.time())
            await self._emit_message({
                "contract_version": "1.0.0",
                "category": Category.BUSINESS.value,
                "type": "DANMU",
                "platform": self.platform,
                "room_id": room_id,
                "seq": seq,
                "timestamp": ts,
                "engine": self.engine_id,
                "protocol_version": "wxsp-backend-0",
                "payload": {"type": "DANMU", "user_name": nickname, "content": content,
                            "user_id": item.get("username")},
            })

    # ---- 登录闭环（Eng Q：NEEDS_LOGIN interactive_login） ----

    def _storage_state_path(self) -> str:
        return f"{self._cookie_dir}/wechat_channels_state.json"

    async def _emit_needs_login(self, room_id: str, login_url: Optional[str] = None) -> None:
        """NEEDS_LOGIN（含 interactive_login：扫码二维码 base64 或一次性 URL）"""
        qr_b64 = None
        if login_url:
            img = qrcode.make(login_url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        seq = self.next_seq(room_id)
        msg = UnifiedMessage(
            envelope=Envelope(
                category=Category.SYSTEM, type=SystemType.NEEDS_LOGIN.value,
                platform=self.platform, room_id=room_id, seq=seq,
                timestamp=int(time.time()), engine=self.engine_id,
            ),
            payload=NeedsLoginPayload(
                failure=FailureInfo(
                    reason_code="wechat_channels.login_expired",
                    fix_hint="在 AUTOlive 弹出的二维码上用微信扫码重新登录管理后台",
                    docs_anchor="docs/platforms/wechat_channels/runbook.md#relogin",
                ),
                interactive_login=(
                    {"qr_image_b64": qr_b64, "login_url": login_url} if (qr_b64 or login_url) else None
                ),
            ),
        )
        await self._emit_message(msg.to_wire())

    async def _wait_for_login(self, page, room_id: str, timeout: float = 300.0) -> None:
        """等待用户扫码完成（跳回后台即恢复；登录态刷新后 storageState 持久化）"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop_flags.get(room_id):
            if "login" not in page.url and "scan" not in page.url:
                await page.context.storage_state(path=self._storage_state_path())
                await self._emit_session_event(room_id, detail="login recovered")
                return
            await asyncio.sleep(2)
        raise TimeoutError("等待扫码登录超时")

    async def _emit_session_event(self, room_id: str, detail: str) -> None:
        """ENGINE_STATUS 会话事件（有界会话重建对上层可见）"""
        seq = self.next_seq(room_id)
        msg = UnifiedMessage(
            envelope=Envelope(
                category=Category.SYSTEM, type=SystemType.ENGINE_STATUS.value,
                platform=self.platform, room_id=room_id, seq=seq,
                timestamp=int(time.time()), engine=self.engine_id,
            ),
            payload={"type": "ENGINE_STATUS", "engine": self.engine_id, "detail": detail},
        )
        await self._emit_message(msg.to_wire())
