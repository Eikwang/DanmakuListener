"""抖音 BarrageGrab 桥接引擎（ADR-001：独立代理进程 + WS IPC 接总线）

技术路线（对齐 DouyinBarrageGrab 参考项目）：
1. 用户安装 BarrageGrab 根证书 → 管理员启动 BarrageGrab（系统代理抓包模式）
2. 直播伴侣/浏览器/抖音客户端的弹幕流被 BarrageGrab 解析（protobuf → JSON）
3. 本引擎经其内置 WS 服务（默认 ws://127.0.0.1:8888）接收 JSON 消息
4. 消息格式 {"Type": 1-9, "Data": "<json 字符串>"} → 契约 v1 九类映射

消息类型（BarrageGrab PackMsgType）：
1弹幕 2点赞 3进入直播间 4关注 5礼物 6统计 7粉丝团 8分享 9下播

合规：只监听不发送；弹幕数据不持久化（docs/ops/compliance-review.md §5）。
"""

import asyncio
import json
import time
from typing import Any, Dict, Optional, Set

import websockets
from loguru import logger

from danmaku_listener.contract.models import GapReason
from danmaku_listener.engines.base import BaseEngine

PROTOCOL_VERSION = "douyin-1"
HEARTBEAT_INTERVAL = 30.0  # BarrageGrab WS 自身保活；websockets 库层 ping 关闭

# BarrageGrab PackMsgType
TYPE_DANMU = 1
TYPE_LIKE = 2
TYPE_ENTER = 3
TYPE_FOLLOW = 4
TYPE_GIFT = 5
TYPE_STATS = 6
TYPE_FANSCLUB = 7
TYPE_SHARE = 8
TYPE_LIVE_EXIT = 9


class DouyinBarrageGrabEngine(BaseEngine):
    """抖音 BarrageGrab WS 桥接引擎

    单 WS 连接服务多房间（BarrageGrab 抓本机全部弹幕源）：
    add_room 登记关注房间号，消息按 Data.RoomId/WebRoomId 分发。
    """

    platform = "douyin"

    def __init__(self, state_store=None, ws_url: str = "ws://127.0.0.1:8888"):
        super().__init__(state_store=state_store)
        self._ws_url = ws_url
        self._active_rooms: Set[str] = set()
        self._conn_task: Optional[asyncio.Task] = None
        self._stop_flags: Dict[str, bool] = {}

    @property
    def engine_id(self) -> str:
        return "grab:douyin"

    async def start(self, room_id: str) -> None:
        self._active_rooms.add(room_id)
        self._stop_flags[room_id] = False
        if self._conn_task is None or self._conn_task.done():
            self._conn_task = asyncio.create_task(self._run_connection(), name="douyin-grab-conn")
            logger.info(f"[douyin-grab] connecting {self._ws_url} (rooms: {sorted(self._active_rooms)})")

    async def stop(self, room_id: str) -> None:
        self._active_rooms.discard(room_id)
        self._stop_flags[room_id] = True
        if not self._active_rooms and self._conn_task:
            self._conn_task.cancel()
            try:
                await self._conn_task
            except (asyncio.CancelledError, Exception):
                pass
            self._conn_task = None

    async def restart(self, room_id: str) -> None:
        """桥接层：房间级 restart 等同 no-op（连接由 BarrageGrab 侧维持）"""
        return None

    # ---- 连接主循环 ----

    async def _run_connection(self) -> None:
        while self._active_rooms:
            try:
                async with websockets.connect(self._ws_url, ping_interval=None) as ws:
                    logger.info(f"[douyin-grab] connected {self._ws_url}")
                    self._set_status(self.status.__class__.RUNNING)
                    async for raw in ws:
                        data = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
                        await self._dispatch(data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[douyin-grab] ws {self._ws_url} failed: {type(e).__name__}: {str(e)[:80]}")
                self._set_status(self.status.__class__.ERROR)
                for room_id in list(self._active_rooms):
                    self.mark_gap_start(room_id)
                    gap = self.build_gap_message(room_id, GapReason.NETWORK)
                    if gap:
                        await self._emit_system(gap)
                await asyncio.sleep(15)  # 慢速重试（契约 O）

    async def _dispatch(self, data: str) -> None:
        """单条 BarrageGrab JSON → 契约消息"""
        try:
            doc = json.loads(data)
        except json.JSONDecodeError:
            return
        msg_type = doc.get("Type")
        if msg_type is None:
            return
        ts = int(time.time())
        if msg_type == TYPE_LIVE_EXIT:
            # 下播：Data 含 RoomId
            try:
                inner = json.loads(doc.get("Data") or "{}")
            except json.JSONDecodeError:
                inner = {}
            room_id = str(inner.get("WebRoomId") or inner.get("RoomId") or "")
            if room_id in self._active_rooms:
                await self._emit_live_status(room_id, False, ts)
            return
        raw_data = doc.get("Data")
        if not raw_data:
            return
        try:
            inner = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except json.JSONDecodeError:
            return
        room_id = str(inner.get("WebRoomId") or inner.get("RoomId") or "")
        if not room_id or room_id not in self._active_rooms:
            return
        self.mark_received(room_id, ts)
        mapped = self._map_message(msg_type, inner, self.next_seq(room_id), ts)
        if mapped:
            await self._emit_message({
                "contract_version": "1.0.0",
                "category": mapped["category"],
                "type": mapped["type"],
                "platform": "douyin",
                "room_id": room_id,
                "seq": mapped["seq"],
                "timestamp": mapped["timestamp"],
                "engine": self.engine_id,
                "protocol_version": PROTOCOL_VERSION,
                "msg_id": mapped.get("msg_id"),
                "payload": mapped["payload"],
            })

    async def _emit_live_status(self, room_id: str, live: bool, ts: int) -> None:
        """LIVE_STATUS_CHANGE（下播）"""
        from danmaku_listener.contract import Category

        await self._emit_message({
            "contract_version": "1.0.0",
            "category": Category.SYSTEM.value,
            "type": "LIVE_STATUS_CHANGE",
            "platform": "douyin",
            "room_id": room_id,
            "seq": self.next_seq(room_id),
            "timestamp": ts,
            "engine": self.engine_id,
            "protocol_version": PROTOCOL_VERSION,
            "payload": {"type": "LIVE_STATUS_CHANGE", "live": live},
        })

    # ---- 消息映射（BarrageGrab → 契约 v1）----

    @staticmethod
    def _map_message(msg_type: int, d: Dict[str, Any], seq: int, ts: int) -> Optional[Dict[str, Any]]:
        user = d.get("User") or {}
        user_name = user.get("Nickname") or ""
        user_id = str(user.get("Id")) if user.get("Id") else None
        msg_id = d.get("MsgId")

        if msg_type == TYPE_DANMU:
            content = d.get("Content") or ""
            if not content:
                return None
            return {
                "category": "business", "type": "DANMU", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "DANMU", "user_name": user_name,
                            "content": content, "user_id": user_id},
            }
        if msg_type == TYPE_LIKE:
            return {
                "category": "business", "type": "LIKE", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "LIKE", "count": d.get("Count", 1),
                            "user_name": user_name, "user_id": user_id},
            }
        if msg_type == TYPE_ENTER:
            return {
                "category": "business", "type": "ENTER_ROOM", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "ENTER_ROOM", "user_name": user_name, "user_id": user_id},
            }
        if msg_type == TYPE_FOLLOW:
            return {
                "category": "business", "type": "SOCIAL", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "SOCIAL", "action": "follow",
                            "user_name": user_name, "user_id": user_id},
            }
        if msg_type == TYPE_GIFT:
            gift_name = d.get("GiftName") or ""
            if not gift_name:
                return None
            return {
                "category": "business", "type": "GIFT", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "GIFT", "user_name": user_name, "user_id": user_id,
                            "gift_name": gift_name,
                            "gift_count": d.get("GiftCount") or d.get("RepeatCount") or 1,
                            "gift_value": d.get("DiamondCount") or d.get("GiftValue") or 0},
            }
        if msg_type == TYPE_STATS:
            return {
                "category": "business", "type": "ROOM_STATS", "seq": seq, "timestamp": ts,
                "payload": {"type": "ROOM_STATS",
                            "viewer_count": d.get("OnlineUserCount"),
                            "total_view_count": d.get("TotalUserCount")},
            }
        if msg_type == TYPE_FANSCLUB:
            action = "fansclub_level_up" if d.get("Type") == 1 else "fansclub_join"
            return {
                "category": "business", "type": "SOCIAL", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "SOCIAL", "action": action,
                            "user_name": user_name, "user_id": user_id,
                            "badge_name": d.get("FansClubName") or "",
                            "badge_level": d.get("Level", 0)},
            }
        if msg_type == TYPE_SHARE:
            return {
                "category": "business", "type": "SOCIAL", "seq": seq, "timestamp": ts,
                "msg_id": msg_id,
                "payload": {"type": "SOCIAL", "action": "share",
                            "user_name": user_name, "user_id": user_id},
            }
        return None
