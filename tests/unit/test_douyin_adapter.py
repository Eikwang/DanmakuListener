"""抖音平台适配器测试

验证抖音消息的正确解析。
"""

import asyncio
import pytest

from danmaku_listener.adapters.douyin import DouyinAdapter
from danmaku_listener.bus.message import DanmakuMessage, GiftInfo


class TestDouyinAdapter:
    """抖音适配器测试"""

    @pytest.fixture
    def adapter(self):
        """创建适配器实例"""
        return DouyinAdapter()

    def test_platform_property(self, adapter):
        """测试平台标识"""
        assert adapter.platform == "douyin"

    def test_can_parse_with_valid_data(self, adapter):
        """测试能识别有效数据"""
        valid_data = {
            "method": "WebcastChatMessage",
            "payload": b'{"Content":"hello","User":{"Nickname":"test"}}',
        }
        assert adapter.can_parse(valid_data) is True

    def test_can_parse_with_invalid_data(self, adapter):
        """测试无效数据返回 False"""
        assert adapter.can_parse(None) is False
        assert adapter.can_parse("") is False
        assert adapter.can_parse({}) is False

    @pytest.mark.asyncio
    async def test_parse_chat_message(self, adapter):
        """测试解析普通弹幕消息"""
        raw_data = {
            "method": "WebcastChatMessage",
            "payload": b'{"Content":"hello world","User":{"Nickname":"userA"},"RoomId":"123456"}',
            "msg_id": "1001",
        }

        result = await adapter.parse(raw_data)

        assert result is not None
        assert isinstance(result, DanmakuMessage)
        assert result.platform == "douyin"
        assert result.room_id == "123456"
        assert result.user_name == "userA"
        assert result.content == "hello world"
        assert result.message_type == "normal"

    @pytest.mark.asyncio
    async def test_parse_gift_message(self, adapter):
        """测试解析礼物消息"""
        raw_data = {
            "method": "WebcastGiftMessage",
            "payload": b'{"Content":"send gift","User":{"Nickname":"giver"},"GiftName":"rocket","GiftCount":1,"DiamondCount":1000,"RoomId":"123456"}',
            "msg_id": "1002",
        }

        result = await adapter.parse(raw_data)

        assert result is not None
        assert isinstance(result, DanmakuMessage)
        assert result.message_type == "gift"
        assert result.gift_info is not None
        assert result.gift_info.user_name == "giver"
        assert result.gift_info.gift_name == "rocket"
        assert result.gift_info.gift_count == 1
        assert result.gift_info.gift_value == 1000

    @pytest.mark.asyncio
    async def test_parse_like_message(self, adapter):
        """测试解析点赞消息"""
        raw_data = {
            "method": "WebcastLikeMessage",
            "payload": b'{"Content":"like","User":{"Nickname":"userB"},"Count":10,"RoomId":"123456"}',
            "msg_id": "1003",
        }

        result = await adapter.parse(raw_data)

        assert result is not None
        assert result.message_type == "system"
        assert "userB" in result.content
        assert "x10" in result.content

    @pytest.mark.asyncio
    async def test_parse_member_message(self, adapter):
        """测试解析进房消息"""
        raw_data = {
            "method": "WebcastMemberMessage",
            "payload": b'{"Content":"enter","User":{"Nickname":"new user"},"CurrentCount":100,"RoomId":"123456"}',
            "msg_id": "1004",
        }

        result = await adapter.parse(raw_data)

        assert result is not None
        assert result.message_type == "system"
        assert "new user" in result.content
        assert "100" in result.content

    @pytest.mark.asyncio
    async def test_parse_unknown_message_type(self, adapter):
        """测试未知消息类型返回 None"""
        raw_data = {
            "method": "UnknownMessageType",
            "payload": b'{}',
        }

        result = await adapter.parse(raw_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_without_msg_id(self, adapter):
        """测试没有 msg_id 时仍能解析"""
        raw_data = {
            "method": "WebcastChatMessage",
            "payload": b'{"Content":"test","User":{"Nickname":"test user"},"RoomId":"123"}',
        }

        result = await adapter.parse(raw_data)
        assert result is not None
        assert result.content == "test"

    @pytest.mark.asyncio
    async def test_parse_with_context(self, adapter):
        """测试带上下文信息解析"""
        raw_data = {
            "method": "WebcastChatMessage",
            "payload": b'{"Content":"with context","User":{"Nickname":"context user"}}',
        }

        context = {"room_id": "999999"}
        result = await adapter.parse(raw_data, context=context)

        assert result is not None
        assert result.room_id == "999999"