"""抖音平台适配器

解析抖音 WebSocket 消息，转换为标准格式。
支持两种数据源：
1. JSON 格式（原有路径）：dict with method + payload
2. Protobuf 格式（新增路径）：DecodedMessage(method, payload, msg_id)
"""

import json
from typing import Any, Dict, Optional

from loguru import logger

from danmaku_listener.adapters.base import BaseAdapter
from danmaku_listener.adapters.protocols.message_types import parse_message_type
from danmaku_listener.bus.message import DanmakuMessage, GiftInfo


class DouyinAdapter(BaseAdapter):
    """抖音平台适配器

    解析抖音 WebSocket 消息，支持 JSON 和 Protobuf 两种格式。
    Protobuf 格式通过 DecodedMessage 传入，payload 为具体消息类型的序列化字节。
    """

    @property
    def platform(self) -> str:
        """返回平台标识"""
        return "douyin"

    def can_parse(self, data: Any) -> bool:
        """判断是否能处理该数据

        支持两种格式：
        1. dict 类型，包含 method 和 payload 字段（JSON 格式）
        2. DecodedMessage 实例（Protobuf 格式）

        Args:
            data: 待检测的数据

        Returns:
            True 如果适配器能处理此数据
        """
        # Protobuf 格式：DecodedMessage 实例
        if hasattr(data, 'method') and hasattr(data, 'payload') and hasattr(data, 'msg_id'):
            return True

        # JSON 格式：dict 类型
        if isinstance(data, dict):
            return "method" in data and "payload" in data

        return False

    async def parse(
        self, raw_data: Any, context: Optional[Dict] = None
    ) -> Optional[DanmakuMessage]:
        """解析原始数据为标准消息格式

        支持 JSON 和 Protobuf 两种数据格式，自动检测并路由到对应解析路径。

        Args:
            raw_data: 原始数据（dict 或 DecodedMessage）
            context: 可选的上下文信息（如 room_id）

        Returns:
            DanmakuMessage 实例，如果解析失败返回 None
        """
        try:
            # 检测数据格式并路由
            if self._is_protobuf_data(raw_data):
                return await self._parse_protobuf(raw_data, context)
            elif isinstance(raw_data, dict):
                return await self._parse_json(raw_data, context)
            else:
                return None

        except Exception as e:
            logger.error(f"Error parsing douyin message: {e}")
            return None

    def _is_protobuf_data(self, data: Any) -> bool:
        """判断是否为 Protobuf 解码数据（DecodedMessage）

        Args:
            data: 待检测的数据

        Returns:
            True 如果是 DecodedMessage 实例
        """
        # DecodedMessage 是 dataclass，有 method/payload/msg_id 属性
        # dict 也有 method/payload 但没有 msg_id
        if isinstance(data, dict):
            return False
        return hasattr(data, 'method') and hasattr(data, 'payload') and hasattr(data, 'msg_id')

    async def _parse_protobuf(
        self, decoded: Any, context: Optional[Dict] = None
    ) -> Optional[DanmakuMessage]:
        """解析 Protobuf 解码数据

        Args:
            decoded: DecodedMessage 实例（method, payload, msg_id）
            context: 可选的上下文信息

        Returns:
            DanmakuMessage 实例，解析失败返回 None
        """
        method = decoded.method
        payload_bytes = decoded.payload

        # 解析消息类型
        msg_type = parse_message_type(method)
        if msg_type == "unknown":
            return None  # → AC-018

        # 获取 room_id
        room_id = ""
        if context and "room_id" in context:
            room_id = context["room_id"]

        # 根据消息类型反序列化 payload 并提取字段
        if msg_type == "chat":
            return self._parse_protobuf_chat(payload_bytes, room_id)
        elif msg_type == "gift":
            return self._parse_protobuf_gift(payload_bytes, room_id)
        elif msg_type == "like":
            return self._parse_protobuf_like(payload_bytes, room_id)
        elif msg_type == "member":
            return self._parse_protobuf_member(payload_bytes, room_id)
        else:
            # 其他已知类型暂不处理
            return None

    def _parse_protobuf_chat(self, payload_bytes: bytes, room_id: str) -> Optional[DanmakuMessage]:
        """解析 Protobuf ChatMessage → AC-004"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import ChatMessage

        try:
            chat = ChatMessage()
            chat.ParseFromString(payload_bytes)

            user_name = chat.user.nickname if chat.user.nickname else ""
            content = chat.content

            return DanmakuMessage(
                platform="douyin",
                room_id=room_id,
                user_name=user_name,
                content=content,
                timestamp=0,
                message_type="normal",
            )
        except Exception as e:
            logger.warning(f"Failed to parse ChatMessage: {e}")
            return None

    def _parse_protobuf_gift(self, payload_bytes: bytes, room_id: str) -> Optional[DanmakuMessage]:
        """解析 Protobuf GiftMessage → AC-005"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import GiftMessage

        try:
            gift = GiftMessage()
            gift.ParseFromString(payload_bytes)

            user_name = gift.user.nickname if gift.user.nickname else ""
            gift_name = gift.gift.name if gift.gift.name else ""
            diamond_count = gift.gift.diamondCount
            repeat_count = gift.repeatCount

            gift_info = GiftInfo(
                user_name=user_name,
                gift_name=gift_name,
                gift_count=repeat_count,
                gift_value=diamond_count,
            )

            return DanmakuMessage(
                platform="douyin",
                room_id=room_id,
                user_name=user_name,
                content=f"送出 {gift_name} x{repeat_count}",
                timestamp=0,
                message_type="gift",
                gift_info=gift_info,
            )
        except Exception as e:
            logger.warning(f"Failed to parse GiftMessage: {e}")
            return None

    def _parse_protobuf_like(self, payload_bytes: bytes, room_id: str) -> Optional[DanmakuMessage]:
        """解析 Protobuf LikeMessage"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import LikeMessage

        try:
            like = LikeMessage()
            like.ParseFromString(payload_bytes)

            user_name = like.user.nickname if like.user.nickname else ""
            count = like.count

            return DanmakuMessage(
                platform="douyin",
                room_id=room_id,
                user_name=user_name,
                content=f"{user_name} 点赞 x{count}",
                timestamp=0,
                message_type="system",
            )
        except Exception as e:
            logger.warning(f"Failed to parse LikeMessage: {e}")
            return None

    def _parse_protobuf_member(self, payload_bytes: bytes, room_id: str) -> Optional[DanmakuMessage]:
        """解析 Protobuf MemberMessage"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import MemberMessage

        try:
            member = MemberMessage()
            member.ParseFromString(payload_bytes)

            user_name = member.user.nickname if member.user.nickname else ""
            member_count = member.memberCount

            return DanmakuMessage(
                platform="douyin",
                room_id=room_id,
                user_name=user_name,
                content=f"{user_name} 进入直播间 (当前{member_count}人)",
                timestamp=0,
                message_type="system",
            )
        except Exception as e:
            logger.warning(f"Failed to parse MemberMessage: {e}")
            return None

    async def _parse_json(
        self, raw_data: Dict, context: Optional[Dict] = None
    ) -> Optional[DanmakuMessage]:
        """解析 JSON 格式数据（原有路径）

        Args:
            raw_data: 包含 method 和 payload 的字典
            context: 可选的上下文信息

        Returns:
            DanmakuMessage 实例，解析失败返回 None
        """
        method = raw_data.get("method", "")
        payload = raw_data.get("payload", b"{}")

        # 解析消息类型
        msg_type = parse_message_type(method)
        if msg_type == "unknown":
            return None

        # 解析 payload（支持 bytes 和 str）
        if isinstance(payload, bytes):
            try:
                data = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to decode payload: {e}")
                return None
        elif isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse payload: {e}")
                return None
        else:
            data = payload

        # 提取用户信息
        user = data.get("User", {})
        user_name = user.get("Nickname", "")

        # 提取房间信息
        room_id = data.get("RoomId", "")
        if context and "room_id" in context:
            room_id = context["room_id"]

        # 时间戳
        timestamp = int(data.get("Timestamp", 0)) or 0

        # 根据消息类型解析
        if msg_type == "chat":
            return self._parse_chat(data, user_name, room_id, timestamp)
        elif msg_type == "gift":
            return self._parse_gift(data, user_name, room_id, timestamp)
        elif msg_type == "like":
            return self._parse_like(data, user_name, room_id, timestamp)
        elif msg_type == "member":
            return self._parse_member(data, user_name, room_id, timestamp)
        else:
            return self._parse_system(data, user_name, room_id, timestamp, msg_type)

    def _parse_chat(
        self, data: Dict, user_name: str, room_id: str, timestamp: int
    ) -> DanmakuMessage:
        """解析普通弹幕消息"""
        return DanmakuMessage(
            platform="douyin",
            room_id=room_id,
            user_name=user_name,
            content=data.get("Content", ""),
            timestamp=timestamp,
            message_type="normal",
        )

    def _parse_gift(
        self, data: Dict, user_name: str, room_id: str, timestamp: int
    ) -> DanmakuMessage:
        """解析礼物消息"""
        gift_info = GiftInfo(
            user_name=user_name,
            gift_name=data.get("GiftName", ""),
            gift_count=int(data.get("GiftCount", 1)),
            gift_value=int(data.get("DiamondCount", 0)),
        )

        return DanmakuMessage(
            platform="douyin",
            room_id=room_id,
            user_name=user_name,
            content=data.get("Content", "送出礼物"),
            timestamp=timestamp,
            message_type="gift",
            gift_info=gift_info,
        )

    def _parse_like(
        self, data: Dict, user_name: str, room_id: str, timestamp: int
    ) -> DanmakuMessage:
        """解析点赞消息"""
        count = int(data.get("Count", 1))
        return DanmakuMessage(
            platform="douyin",
            room_id=room_id,
            user_name=user_name,
            content=f"{user_name} 点赞 x{count}",
            timestamp=timestamp,
            message_type="system",
        )

    def _parse_member(
        self, data: Dict, user_name: str, room_id: str, timestamp: int
    ) -> DanmakuMessage:
        """解析进房消息"""
        current_count = int(data.get("CurrentCount", 0))
        return DanmakuMessage(
            platform="douyin",
            room_id=room_id,
            user_name=user_name,
            content=f"{user_name} 进入直播间 (当前{current_count}人)",
            timestamp=timestamp,
            message_type="system",
        )

    def _parse_system(
        self, data: Dict, user_name: str, room_id: str, timestamp: int, msg_type: str
    ) -> DanmakuMessage:
        """解析其他系统消息"""
        return DanmakuMessage(
            platform="douyin",
            room_id=room_id,
            user_name=user_name,
            content=data.get("Content", f"[{msg_type}]"),
            timestamp=timestamp,
            message_type="system",
        )
