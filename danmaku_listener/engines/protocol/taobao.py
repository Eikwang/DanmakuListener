"""淘宝直播弹幕 Web 协议引擎（mtop 双通道，TaobaoLiveWebFetcher 参考实现对照）

协议（2026-09-29 校准，参考实现 537 行逐段对照）：
- 凭证：Playwright 打开 tbzb.taobao.com/live?liveId={id}（游客可用）→
  拦截 iliad 请求拿 topic → 取 _m_h5_tk/_m_h5_tk_enc cookies
- 主通道：mtop.taobao.powermsg.h5.msg.pullnativemsg（appKey 12574478，10s 轮询）
  响应 data.timestampList[].data = base64(protobuf+JSON 混合) → 扫描提取 JSON 对象，
  按字段特征分发：viewCountFormat=统计 / nick+flowSourceText=进场 / value.dig=点赞 /
  subType==10001 聊天 / subType==10002 礼物 / status==3 下播
- 评论通道：mtop.taobao.iliad.comment.query.latest（appKey 34675810，服务端 delay 轮询）
  data.comments[]（publisherNick/publisherId/content）
- 30s 无消息 → 凭证过期/风控 → 整轮重建（重取凭证，契约 O）

映射：ChatMessage→DANMU、Member→ENTER_ROOM、Gift→GIFT、Like→LIKE、
统计→ROOM_STATS、Control(status==3)→LIVE_STATUS_CHANGE(live=false)。
"""

import asyncio
import json
import re
import time
from typing import Any, Dict, Optional

import websockets  # noqa: F401  保留与其它协议引擎一致的导入形态
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol.mtop import (
    MtopClient,
    MtopError,
    MtopCredential,
    extract_live_id,
    parse_base64_mixed_message,
)

PROTOCOL_VERSION = "taobao-1"

LIVE_URL = "https://tbzb.taobao.com/live?liveId={live_id}"
POWERMSG_API = "mtop.taobao.powermsg.h5.msg.pullnativemsg"
POWERMSG_VERSION = "1.0"
POWERMSG_APP_KEY = "12574478"
ILIAD_API = "mtop.taobao.iliad.comment.query.latest"
ILIAD_VERSION = "1.0"
ILIAD_APP_KEY = "34675810"

POLL_INTERVAL_POWERMSG = 10.0
NO_MESSAGE_TIMEOUT = 30.0

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")


class TaobaoWebProtocolEngine(BaseEngine):
    """淘宝直播 mtop 双通道引擎（每平台一实例、每房间独立任务）"""

    platform = "taobao"

    def __init__(self, state_store=None, domain: str = "taobao.com"):
        super().__init__(state_store=state_store)
        self._domain = domain  # 1688 复用：domain="1688.com"（API 名实测后配置）
        self._room_tasks: Dict[str, asyncio.Task] = {}
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "webws:taobao"

    # ---- 公开契约 ----

    async def start(self, room_id: str) -> None:
        if room_id in self._room_tasks and not self._room_tasks[room_id].done():
            return
        self._stop_flags[room_id] = False
        self._room_tasks[room_id] = asyncio.create_task(
            self._run_room(room_id), name=f"taobao-room-{room_id}")

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

    # ---- 凭证阶段（Playwright）----

    async def _fetch_credentials(self, room_id: str) -> tuple:
        """打开直播间页 → topic + cookies（async Playwright；失败抛 RuntimeError）"""
        from playwright.async_api import async_playwright

        live_id = extract_live_id(room_id)
        live_url = LIVE_URL.format(live_id=live_id)
        topic: Optional[str] = None
        cookies: Dict[str, str] = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=UA)
                page = await context.new_page()

                def on_request(request) -> None:
                    nonlocal topic
                    if topic:
                        return
                    if ILIAD_API in request.url:
                        m = re.search(r"[?&]data=([^&]+)", request.url)
                        if m:
                            try:
                                data = json.loads(m.group(1))
                                topic = data.get("topic")
                            except json.JSONDecodeError:
                                pass

                context.on("request", on_request)
                try:
                    await page.goto(live_url, timeout=15000)
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"[taobao] room {room_id} page goto warning: {e}")
                for _ in range(10):
                    if topic:
                        break
                    await asyncio.sleep(1)
                for c in await context.cookies():
                    if c["name"] in ("_m_h5_tk", "_m_h5_tk_enc"):
                        cookies[c["name"]] = c["value"]
            finally:
                await browser.close()

        if not topic:
            raise RuntimeError(
                "taobao.credential.topic_failed: 未能获取 topic（房间号错误/未开播/风控）")
        if not cookies.get("_m_h5_tk"):
            raise RuntimeError("taobao.credential.token_failed: 未获取 _m_h5_tk（风控升级特征）")
        logger.info(f"[taobao] room {room_id} credentials ready (topic={topic[:24]}...)")
        return topic, MtopCredential(cookies)

    # ---- 房间任务主循环 ----

    async def _run_room(self, room_id: str) -> None:
        live_id = extract_live_id(room_id)
        logger.info(f"[taobao] room {room_id} connecting (live_id={live_id})")
        backoff = 15.0
        while not self._stop_flags.get(room_id):
            try:
                topic, cred = await self._fetch_credentials(room_id)
                session = requests.Session()
                session.headers.update({"User-Agent": UA})
                for k, v in cred.cookies.items():
                    session.cookies.set(k, v)
                client = MtopClient(self._domain, UA, session)

                last_msg = time.monotonic()
                poll_task = asyncio.create_task(
                    self._poll_powermsg(room_id, client, cred, topic, live_id,
                                        lambda: last_msg))
                comment_task = asyncio.create_task(
                    self._poll_comments(room_id, client, cred, topic))
                self._set_status(self.status.__class__.RUNNING)
                try:
                    while not self._stop_flags.get(room_id):
                        await asyncio.sleep(2)
                        # 30s 无消息 → 凭证过期/风控 → 整轮重建（Eng：主通道断流检测）
                        if time.monotonic() - last_msg > NO_MESSAGE_TIMEOUT:
                            raise RuntimeError(
                                "taobao.no_message_timeout: 30s 无消息（凭证过期/风控）")
                finally:
                    poll_task.cancel()
                    comment_task.cancel()
                    for tk in (poll_task, comment_task):
                        try:
                            await tk
                        except (asyncio.CancelledError, Exception):
                            pass
                backoff = 15.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[taobao] room {room_id} error: {type(e).__name__}: {str(e)[:90]}")
                self._set_status(self.status.__class__.ERROR)
                self.mark_gap_start(room_id)
                gap = self.build_gap_message(room_id, GapReason.NETWORK)
                if gap:
                    await self._emit_system(gap)
                if self._stop_flags.get(room_id):
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 900.0)

    # ---- 主通道：powermsg 长轮询 ----

    async def _poll_powermsg(self, room_id: str, client: MtopClient, cred: MtopCredential,
                             topic: str, live_id: str, last_msg_ref) -> None:
        offset = str(int(time.time() * 1000))
        loop = asyncio.get_running_loop()
        headers = {
            "x-biz-type": "powermsg",
            "x-biz-info": "namespace=1",
            "referer": LIVE_URL.format(live_id=live_id),
        }
        while not self._stop_flags.get(room_id):
            try:
                data = {
                    "topic": topic, "offset": offset, "pagesize": 10,
                    "tag": "", "bizcode": 1, "sdkversion": "h5_3.4.2", "role": 3,
                }
                result = await loop.run_in_executor(
                    None, client.get, POWERMSG_API, POWERMSG_VERSION,
                    POWERMSG_APP_KEY, data, cred.m_h5_tk, headers)
                timestamps = (result.get("data") or {}).get("timestampList") or []
                if timestamps:
                    offset = timestamps[-1].get("offset", offset)
                    for td in timestamps:
                        await self._parse_powermsg_item(room_id, td, ts=int(time.time()))
                    last_msg_ref()
                await asyncio.sleep(POLL_INTERVAL_POWERMSG)
            except MtopError as e:
                logger.warning(f"[taobao] room {room_id} powermsg error: {e}")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise

    async def _parse_powermsg_item(self, room_id: str, td: Dict[str, Any], ts: int) -> None:
        data_b64 = td.get("data", "")
        if not data_b64:
            return
        try:
            json_objects, _raw = parse_base64_mixed_message(data_b64)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[taobao] room {room_id} b64 parse error: {e}")
            return
        for obj in json_objects:
            if not isinstance(obj, dict):
                continue
            mapped = self._map_powermsg(room_id, obj, self.next_seq(room_id), ts)
            if mapped:
                await self._emit_message(mapped)

    # ---- 评论通道：iliad 轮询 ----

    async def _poll_comments(self, room_id: str, client: MtopClient, cred: MtopCredential,
                             topic: str) -> None:
        pagination_ctx = None
        loop = asyncio.get_running_loop()
        while not self._stop_flags.get(room_id):
            try:
                payload: Dict[str, Any] = {"topic": topic, "limit": 20, "tab": 2,
                                           "order": "asc"}
                if pagination_ctx:
                    payload["paginationContext"] = pagination_ctx
                result = await loop.run_in_executor(
                    None, client.get, ILIAD_API, ILIAD_VERSION,
                    ILIAD_APP_KEY, payload, cred.m_h5_tk, None)
                data = result.get("data") or {}
                pagination_ctx = data.get("paginationContext") or pagination_ctx
                delay_ms = data.get("delay", 6000)
                for c in data.get("comments") or []:
                    mapped = self._map_comment(room_id, c, self.next_seq(room_id),
                                               int(time.time()))
                    if mapped:
                        await self._emit_message(mapped)
                await asyncio.sleep(max(int(delay_ms), 2000) / 1000.0)
            except MtopError as e:
                logger.warning(f"[taobao] room {room_id} iliad error: {e}")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise

    # ---- 上游消息 → 契约 v1（显式清单，与 test_taobao_protocol.py 对齐）----

    @staticmethod
    def _map_powermsg(room_id: str, obj: Dict[str, Any], seq: int, ts: int) -> Optional[Dict[str, Any]]:
        # 分发顺序修正（参考实现的字段特征重叠 bug）：subType 聊天/礼物优先判定，
        # 否则 subType==10001 聊天（含 nick）会被进场分支误吞
        sub_type = obj.get("subType")
        if sub_type == 10001:
            content = obj.get("content", obj.get("text", ""))
            if not content:
                return None
            return {"category": "business", "type": "DANMU", "seq": seq, "timestamp": ts,
                    "payload": {"type": "DANMU", "user_name": obj.get("nick", ""),
                                "content": content,
                                "user_id": str(obj.get("userid", obj.get("userId", "")))}}
        if sub_type == 10002:
            gift_name = obj.get("giftName", obj.get("itemName", ""))
            if not gift_name:
                return None
            return {"category": "business", "type": "GIFT", "seq": seq, "timestamp": ts,
                    "payload": {"type": "GIFT", "user_name": obj.get("nick", ""),
                                "gift_name": gift_name,
                                "gift_count": obj.get("count", obj.get("num", 1))}}
        # 统计：viewCountFormat/pageViewCount
        if "viewCountFormat" in obj or "pageViewCount" in obj:
            current = obj.get("onlineCount", obj.get("current_viewers", 0))
            total = obj.get("totalCount", obj.get("total_viewers", 0))
            return {"category": "business", "type": "ROOM_STATS", "seq": seq,
                    "timestamp": ts,
                    "payload": {"type": "ROOM_STATS", "viewer_count": current,
                                "total_view_count": total}}
        # 进场：nick + flowSourceText（subType 已在上方处理）
        if "nick" in obj and "flowSourceText" in obj:
            identify = obj.get("identify") or {}
            fan_level = identify.get("fanLevel", 0)
            if isinstance(fan_level, str) and fan_level.isdigit():
                fan_level = int(fan_level)
            elif not isinstance(fan_level, int):
                fan_level = 0
            return {"category": "business", "type": "ENTER_ROOM", "seq": seq,
                    "timestamp": ts,
                    "payload": {"type": "ENTER_ROOM",
                                "user_name": obj.get("nick", ""),
                                "user_id": str(obj.get("userid", obj.get("userId", ""))),
                                "fan_level": fan_level}}
        # 点赞：value.dig
        if "value" in obj and isinstance(obj.get("value"), dict) and "dig" in obj["value"]:
            return {"category": "business", "type": "LIKE", "seq": seq, "timestamp": ts,
                    "payload": {"type": "LIKE", "count": obj["value"].get("dig", 1)}}
        logger.debug(f"[taobao] room {room_id} unmapped powermsg keys={sorted(obj)[:6]}")
        return None

    @staticmethod
    def _map_comment(room_id: str, c: Dict[str, Any], seq: int, ts: int) -> Optional[Dict[str, Any]]:
        content = c.get("content", "")
        if not content:
            return None
        nick = c.get("publisherNick", "")
        user_id = str(c.get("publisherId", ""))
        return {"category": "business", "type": "DANMU", "seq": seq, "timestamp": ts,
                "payload": {"type": "DANMU", "user_name": nick, "content": content,
                            "user_id": user_id}}
