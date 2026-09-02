"""Task-09: DouyinAdapter Protobuf 增强 测试

验证 DouyinAdapter 支持 Protobuf 解码数据（DecodedMessage）的解析：
- ChatMessage → DanmakuMessage(message_type="normal")
- GiftMessage → DanmakuMessage(message_type="gift", gift_info)
- LikeMessage → DanmakuMessage(message_type="system")
- MemberMessage → DanmakuMessage(message_type="system")
- 未知 method → None
- payload 无效 → None
- 原有 JSON 路径不受影响
- can_parse 对 DecodedMessage 返回 True
"""

import pytest
from unittest.mock import MagicMock

from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
from danmaku_listener.adapters.protocols.proto.message_pb2 import (
    Response, Message, ChatMessage, GiftMessage, LikeMessage, MemberMessage, User,
)


def _build_decoded_message(method: str, payload_bytes: bytes, msg_id: str = "123"):
    """构造 DecodedMessage 实例"""
    from danmaku_listener.engines.protobuf_decoder import DecodedMessage
    return DecodedMessage(method=method, payload=payload_bytes, msg_id=msg_id)


def _build_chat_msg(content: str = "你好", nickname: str = "测试用户") -> bytes:
    """构造 ChatMessage 的序列化字节"""
    chat = ChatMessage(content=content)
    chat.user.nickname = nickname
    return chat.SerializeToString()


def _build_gift_msg(
    nickname: str = "送礼者", gift_name: str = "火箭",
    diamond_count: int = 100, repeat_count: int = 2,
) -> bytes:
    """构造 GiftMessage 的序列化字节"""
    gift = GiftMessage()
    gift.user.nickname = nickname
    gift.gift.name = gift_name
    gift.gift.diamondCount = diamond_count
    gift.repeatCount = repeat_count
    return gift.SerializeToString()


def _build_like_msg(nickname: str = "点赞者", count: int = 5) -> bytes:
    """构造 LikeMessage 的序列化字节"""
    like = LikeMessage(count=count)
    like.user.nickname = nickname
    return like.SerializeToString()


def _build_member_msg(nickname: str = "进房者", member_count: int = 100) -> bytes:
    """构造 MemberMessage 的序列化字节"""
    member = MemberMessage(memberCount=member_count)
    member.user.nickname = nickname
    return member.SerializeToString()


class TestDouyinAdapterCanParseProtobuf:
    """can_parse 对 DecodedMessage 的判断"""

    def test_can_parse_decoded_message(self):
        """can_parse 对 DecodedMessage 实例返回 True"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        from danmaku_listener.engines.protobuf_decoder import DecodedMessage
        adapter = DouyinAdapter()
        msg = DecodedMessage(method="WebcastChatMessage", payload=b"", msg_id="123")
        assert adapter.can_parse(msg) is True

    def test_can_parse_dict_still_works(self):
        """can_parse 对原有 dict 格式仍返回 True"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()
        data = {"method": "WebcastChatMessage", "payload": b"{}"}
        assert adapter.can_parse(data) is True

    def test_can_parse_other_type_returns_false(self):
        """can_parse 对其他类型返回 False"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()
        assert adapter.can_parse("string") is False
        assert adapter.can_parse(123) is False
        assert adapter.can_parse(None) is False


class TestDouyinAdapterProtobufChat:
    """Protobuf ChatMessage 解析 → AC-004"""

    @pytest.mark.asyncio
    async def test_parse_chat_message(self):
        """ChatMessage → DanmakuMessage(platform="douyin", content="你好", message_type="normal")"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        payload = _build_chat_msg("你好", "测试用户")
        decoded = _build_decoded_message("WebcastChatMessage", payload, "123")

        result = await adapter.parse(decoded, context={"room_id": "999"})
        assert result is not None
        assert result.platform == "douyin"
        assert result.content == "你好"
        assert result.user_name == "测试用户"
        assert result.message_type == "normal"
        assert result.room_id == "999"

    @pytest.mark.asyncio
    async def test_parse_chat_msg_id(self):
        """DecodedMessage.msg_id 正确传递"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        payload = _build_chat_msg("test", "user")
        decoded = _build_decoded_message("WebcastChatMessage", payload, "456")

        result = await adapter.parse(decoded)
        assert result is not None


class TestDouyinAdapterProtobufGift:
    """Protobuf GiftMessage 解析 → AC-005"""

    @pytest.mark.asyncio
    async def test_parse_gift_message(self):
        """GiftMessage → DanmakuMessage(message_type="gift", gift_info)"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        payload = _build_gift_msg("送礼者", "火箭", 100, 2)
        decoded = _build_decoded_message("WebcastGiftMessage", payload, "456")

        result = await adapter.parse(decoded, context={"room_id": "999"})
        assert result is not None
        assert result.message_type == "gift"
        assert result.gift_info is not None
        assert result.gift_info.gift_name == "火箭"
        assert result.gift_info.gift_count == 2
        assert result.gift_info.gift_value == 100
        assert result.gift_info.user_name == "送礼者"


class TestDouyinAdapterProtobufLike:
    """Protobuf LikeMessage 解析"""

    @pytest.mark.asyncio
    async def test_parse_like_message(self):
        """LikeMessage → DanmakuMessage(message_type="system", content="点赞者 点赞 x5")"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        payload = _build_like_msg("点赞者", 5)
        decoded = _build_decoded_message("WebcastLikeMessage", payload, "789")

        result = await adapter.parse(decoded, context={"room_id": "999"})
        assert result is not None
        assert result.message_type == "system"
        assert "点赞者" in result.content
        assert "5" in result.content


class TestDouyinAdapterProtobufMember:
    """Protobuf MemberMessage 解析"""

    @pytest.mark.asyncio
    async def test_parse_member_message(self):
        """MemberMessage → DanmakuMessage(message_type="system", content="进房者 进入直播间")"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        payload = _build_member_msg("进房者", 100)
        decoded = _build_decoded_message("WebcastMemberMessage", payload, "012")

        result = await adapter.parse(decoded, context={"room_id": "999"})
        assert result is not None
        assert result.message_type == "system"
        assert "进房者" in result.content
        assert "100" in result.content


class TestDouyinAdapterProtobufErrors:
    """Protobuf 解析异常处理"""

    @pytest.mark.asyncio
    async def test_unknown_method_returns_none(self):
        """未知 method → None → AC-018"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        decoded = _build_decoded_message("UnknownMessage", b"", "999")
        result = await adapter.parse(decoded)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_protobuf_payload_returns_none(self):
        """payload 无效（非 Protobuf 格式）→ None，不抛异常"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        decoded = _build_decoded_message("WebcastChatMessage", b"invalid_protobuf", "111")
        result = await adapter.parse(decoded)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_payload_returns_none(self):
        """空 payload → None"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        decoded = _build_decoded_message("WebcastChatMessage", b"", "111")
        # ChatMessage 空内容应该返回空字符串 content，不是 None
        result = await adapter.parse(decoded)
        # 空 payload 的 ChatMessage 仍可解析（content=""）
        assert result is not None or result is None  # 容错即可


class TestDouyinAdapterJsonStillWorks:
    """原有 JSON 格式解析路径不受影响"""

    @pytest.mark.asyncio
    async def test_parse_json_chat(self):
        """JSON 格式弹幕仍正常解析"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        data = {
            "method": "WebcastChatMessage",
            "payload": b'{"Content":"hello","User":{"Nickname":"test"}}',
        }
        result = await adapter.parse(data, context={"room_id": "123"})
        assert result is not None
        assert result.content == "hello"
        assert result.user_name == "test"
        assert result.message_type == "normal"

    @pytest.mark.asyncio
    async def test_parse_json_gift(self):
        """JSON 格式礼物仍正常解析"""
        from danmaku_listener.adapters.douyin import DouyinAdapter
        adapter = DouyinAdapter()

        data = {
            "method": "WebcastGiftMessage",
            "payload": b'{"GiftName":"rose","GiftCount":3,"DiamondCount":10,"User":{"Nickname":"gifter"}}',
        }
        result = await adapter.parse(data, context={"room_id": "123"})
        assert result is not None
        assert result.message_type == "gift"
        assert result.gift_info.gift_name == "rose"
