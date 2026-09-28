"""快手直播弹幕协议直连引擎（阶段 4）

token 获取（2026-09-28 实测校准，对齐 barrage-fly KuaishouApis）：
1. 游客路线：GET live_api/liveroom/livedetail?principalId={room_id}
   → websocketInfo.token + liveStream.id + webSocketAddresses
   （SDK 2024 路线；2026-09 部分环境已被风控"请求过快"拦截）
2. 登录态浏览器路线（实测主路线）：快手 web 直播间已强制游客登录——
   Playwright 加载 storage_state（kuaishou_login 登录闭环产物）打开直播间页，
   拦截 websocketinfo XHR 提取 token/liveStreamId/webSocketAddresses

协议连接保持直连（token 注入），浏览器仅承担 token 获取（同 B站登录闭环角色）。
"""

import asyncio
import random
import re
import time
from typing import Any, Dict

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol import kuaishou_codec as codec

HEARTBEAT_INTERVAL = 20.0  # 快手心跳口径较短

LIVE_DETAIL_URL = "https://live.kuaishou.com/live_api/liveroom/livedetail?principalId={room_id}"
LIVE_ROOM_URL = "https://live.kuaishou.com/u/{room_id}"
_BROWSER_TOKEN_TIMEOUT = 30.0

#: liveroom XHR 响应体中提取 liveStream.id（2026-09 URL 不再携带该参数）
_LIVE_STREAM_ID_RE = re.compile(r'"liveStream":\s*\{"id":\s*"([A-Za-z0-9_-]{8,24})"')

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://live.kuaishou.com/",
}


class KuaishouProtocolEngine(BaseEngine):
    """快手协议直连引擎（复用阶段 1 骨架模式）"""

    platform = "kuaishou"

    def __init__(self, state_store=None, token_provider=None, cookie_file: Any = None):
        super().__init__(state_store=state_store)
        # token_provider: async (room_id) -> str；默认内置（游客 API → 登录态浏览器回退）
        self._token_provider = token_provider
        self._cookie_file = cookie_file  # kuaishou_storage_state.json（登录态）
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "protocol:kuaishou"

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(self._run_room(room_id), name=f"kuaishou-room-{room_id}")

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

    # ---- 房间上下文（token/直播流/WS 地址）----

    @staticmethod
    def _fetch_room_context_sync(room_id: str) -> Dict[str, Any]:
        """游客上下文：livedetail 接口（SDK KuaishouApis.roomInitGet 同款）

        Returns: {"token": str, "live_stream_id": str, "ws_urls": [str]}
        Raises: ValueError（房间不存在/未开播——liveStream 为空）
        """
        import requests

        resp = requests.get(
            LIVE_DETAIL_URL.format(room_id=room_id),
            headers=_HTTP_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        websocket_info = data.get("websocketInfo") or {}
        live_stream = data.get("liveStream") or {}
        token = websocket_info.get("token") or ""
        live_stream_id = live_stream.get("id") or ""
        ws_urls = [
            str(u) for u in (websocket_info.get("webSocketAddresses") or []) if u
        ]
        if not token or not live_stream_id:
            raise ValueError(
                "livedetail 未返回 token/liveStreamId（房间不存在、未开播或已下播）"
            )
        return {"token": token, "live_stream_id": live_stream_id, "ws_urls": ws_urls}

    async def _room_context(self, room_id: str) -> Dict[str, Any]:
        """房间连接上下文：注入 token_provider 优先 → 游客 API → 登录态浏览器"""
        if self._token_provider is not None:
            token = await self._token_provider(room_id)
            return {"token": token, "live_stream_id": room_id, "ws_urls": []}
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self._fetch_room_context_sync, room_id
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[kuaishou] room {room_id} guest API failed: {e}")
        return await self._fetch_context_via_browser(room_id)

    async def _fetch_context_via_browser(self, room_id: str) -> Dict[str, Any]:
        """登录态浏览器打开直播间页 → 拦截 websocketinfo XHR → token 上下文

        快手 web 直播间已强制游客登录（2026-09 实测），登录态由 kuaishou_login
        登录闭环提供（storage_state）。浏览器仅承担 token 获取，协议连接直连。

        2026-09 接口校准（SDK 2024 字段已变）：
        - websocketinfo 响应：webSocketAddresses → **websocketUrls**
          （地址带 path，如 wss://livejs-ws.kuaishou.cn/group10）
        - URL 不再携带 liveStreamId——从 liveroom XHR 响应或页面
          __INITIAL_STATE__.liveroom.playList 取
        """
        from playwright.async_api import async_playwright

        from danmaku_listener.engines import kuaishou_login

        state_path = self._cookie_file or kuaishou_login.DEFAULT_STATE_PATH
        result: Dict[str, Any] = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context_kwargs: Dict[str, Any] = {
                    "user_agent": _HTTP_HEADERS["User-Agent"],
                    "viewport": {"width": 1280, "height": 800},
                }
                if kuaishou_login.has_login_cookie(state_path):
                    context_kwargs["storage_state"] = state_path
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                async def on_response(resp) -> None:
                    url = resp.url
                    if "websocketinfo" in url and "token" not in result:
                        try:
                            data = (await resp.json()).get("data") or {}
                            if data.get("token"):
                                result["token"] = data["token"]
                                # 2026-09: websocketUrls（带 path）；兼容旧 webSocketAddresses
                                urls = (data.get("websocketUrls")
                                        or data.get("webSocketAddresses") or [])
                                result["ws_urls"] = [str(u) for u in urls if u]
                        except Exception:  # noqa: BLE001
                            pass
                    elif ("liveroom" in url) and "live_stream_id" not in result:
                        try:
                            body = await resp.text()
                            m = _LIVE_STREAM_ID_RE.search(body)
                            if m:
                                result["live_stream_id"] = m.group(1)
                        except Exception:  # noqa: BLE001
                            pass

                page.on("response", on_response)
                await page.goto(
                    LIVE_ROOM_URL.format(room_id=room_id),
                    wait_until="domcontentloaded",
                )
                deadline = time.monotonic() + _BROWSER_TOKEN_TIMEOUT
                while time.monotonic() < deadline:
                    if "token" in result and "live_stream_id" in result:
                        break
                    if "live_stream_id" not in result:
                        # 页面 store 兜底（__INITIAL_STATE__.liveroom.playList）
                        try:
                            live_stream_id = await page.evaluate(
                                "() => { const s = window.__INITIAL_STATE__ || {};"
                                " const pl = (s.liveroom || {}).playList || [];"
                                " for (const it of pl) {"
                                "  const id = (it.liveStream || {}).id;"
                                "  if (id) return id; } return ''; }"
                            )
                            if live_stream_id:
                                result["live_stream_id"] = str(live_stream_id)
                        except Exception:  # noqa: BLE001
                            pass
                    await asyncio.sleep(1)
                # 顺带续期 storage_state（登录态刷新）
                try:
                    await context.storage_state(path=state_path)
                except Exception:  # noqa: BLE001
                    pass
                await browser.close()
            finally:
                await browser.close()

        if "token" not in result or not result.get("live_stream_id"):
            missing = "token" if "token" not in result else "liveStreamId"
            raise ValueError(
                f"websocketinfo 未捕获 {missing}（未登录/房间未开播/页面限流）——"
                "登录闭环见 bridge NEEDS_LOGIN 流程"
            )
        return result

    async def _run_room(self, room_id: str) -> None:
        logger.info(f"[kuaishou] room {room_id} connecting")
        while not self._stop_flags.get(room_id):
            try:
                ctx = await self._room_context(room_id)
                ws_urls = ctx["ws_urls"] or [codec.WS_URL]
                last_err: Exception = RuntimeError("无可用弹幕服务器")
                connected = False
                for ws_url in ws_urls[:3]:
                    try:
                        await self._serve_room(room_id, ws_url, ctx)
                        connected = True
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        last_err = e
                        logger.warning(
                            f"[kuaishou] room {room_id} ws {ws_url} failed: "
                            f"{type(e).__name__}: {str(e)[:80]}"
                        )
                if not connected:
                    raise last_err
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[kuaishou] room {room_id} error: {e}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                gap = self.build_gap_message(room_id, GapReason.NETWORK)
                if gap:
                    await self._emit_system(gap)
                if self._stop_flags.get(room_id):
                    return
                await asyncio.sleep(15)

    async def _serve_room(self, room_id: str, ws_url: str, ctx: Dict[str, Any]) -> None:
        """单地址连接 + enter_room（token/liveStreamId/随机 pageId）+ 心跳 + 读循环"""
        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None) as ws:
            await ws.send(codec.build_enter_room(
                ctx["token"], ctx["live_stream_id"],
                page_id=random.randrange(16**16).__format__("x").zfill(16)[:16]
                        + str(int(time.time() * 1000)),
            ))
            logger.info(f"[kuaishou] room {room_id} enter_room sent to {ws_url}")
            self._set_status(self.status.__class__.RUNNING)
            hb_task = asyncio.create_task(self._heartbeat(room_id, ws))
            try:
                await self._read_loop(room_id, ws)
            finally:
                hb_task.cancel()

    async def _heartbeat(self, room_id: str, ws) -> None:
        try:
            while True:
                await ws.send(codec.build_heartbeat())
                await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _read_loop(self, room_id: str, ws) -> None:
        async for raw in ws:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            ts = int(time.time())
            self.mark_received(room_id, ts)
            mapped_list = codec.map_socket_message(data, self.next_seq(room_id), ts)
            for mapped in mapped_list:
                await self._emit_message({
                    "contract_version": "1.0.0",
                    "category": mapped["category"],
                    "type": mapped["type"],
                    "platform": "kuaishou",
                    "room_id": room_id,
                    "seq": mapped["seq"],
                    "timestamp": mapped["timestamp"],
                    "engine": self.engine_id,
                    "protocol_version": codec.PROTOCOL_VERSION,
                    "msg_id": mapped.get("msg_id"),
                    "payload": mapped["payload"],
                })
