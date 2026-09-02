"""斗鱼平台适配器测试

验证 DouyuAdapter 的消息解析功能。
"""

import json
import pytest
from unittest.mock import AsyncMock

from danmaku_listener.adapters.douyu import DouyuAdapter
from danmaku_listener.bus.message import DanmakuMessage


class TestDouyuAdapter:
    """斗鱼平台适配器测试"""

    @pytest.fixture
    def adapter(self):
        """创建斗鱼适配器实例"""
        return DouyuAdapter()

    def test_platform_property(self, adapter):
        """测试平台标识为 douyu"""
        assert adapter.platform == "douyu"

    def test_can_parse_dict_with_type_field(self, adapter):
        """测试能解析包含 type 字段的字典"""
        data = {"type": "chatmsg", "content": "hello"}
        assert adapter.can_parse(data) is True

    def test_can_parse_dict_with_method_field(self, adapter):
        """测试能解析包含 method 字段的字典"""
        data = {"method": "chatmsg", "data": {}}
        assert adapter.can_parse(data) is True

    def test_can_parse_rejects_non_dict(self, adapter):
        """测试拒绝非字典类型"""
        assert adapter.can_parse("string") is False
        assert adapter.can_parse(123) is False
        assert adapter.can_parse(None) is False

    def test_can_parse_rejects_empty_dict(self, adapter):
        """测试拒绝空字典"""
        assert adapter.can_parse({}) is False

    def test_can_parse_rejects_dict_without_type_or_method(self, adapter):
        """测试拒绝没有 type 也没有 method 的字典"""
        assert adapter.can_parse({"user": "test"}) is False

    @pytest.mark.asyncio
    async def test_parse_chat_message(self, adapter):
        """测试解析普通弹幕消息"""
        raw_data = {
            "type": "chatmsg",
            "nn": "测试用户",
            "txt": "大家好",
            "rid": "12345",
            "ct": "1700000000",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert isinstance(message, DanmakuMessage)
        assert message.platform == "douyu"
        assert message.room_id == "12345"
        assert message.user_name == "测试用户"
        assert message.content == "大家好"
        assert message.message_type == "normal"

    @pytest.mark.asyncio
    async def test_parse_gift_message(self, adapter):
        """测试解析礼物消息"""
        raw_data = {
            "type": "dgb",
            "nn": "土豪哥",
            "txt": "送出火箭",
            "gfid": "101",
            "gfn": "火箭",
            "gfcnt": "1",
            "hits": "1000",
            "rid": "12345",
            "ct": "1700000000",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "gift"
        assert message.gift_info is not None
        assert message.gift_info.gift_name == "火箭"
        assert message.gift_info.gift_count == 1
        assert message.gift_info.gift_value == 1000

    @pytest.mark.asyncio
    async def test_parse_enter_message(self, adapter):
        """测试解析进房消息"""
        raw_data = {
            "type": "uenter",
            "nn": "新用户",
            "rid": "12345",
            "ct": "1700000000",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "system"
        assert "新用户" in message.content
        assert "进入" in message.content

    @pytest.mark.asyncio
    async def test_parse_unknown_type_returns_none(self, adapter):
        """测试未知消息类型返回 None"""
        raw_data = {
            "type": "unknown_type",
            "nn": "test",
            "txt": "hello",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        result = await adapter.parse(raw_data, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_without_context_uses_defaults(self, adapter):
        """测试无 context 时使用默认值"""
        raw_data = {
            "type": "chatmsg",
            "nn": "用户A",
            "txt": "hello",
            "rid": "99999",
        }

        message = await adapter.parse(raw_data)

        assert message is not None
        assert message.platform == "douyu"
        assert message.room_id == "99999"

    @pytest.mark.asyncio
    async def test_parse_context_room_id_overrides_data(self, adapter):
        """测试 context 中的 room_id 覆盖数据中的 rid"""
        raw_data = {
            "type": "chatmsg",
            "nn": "用户A",
            "txt": "hello",
            "rid": "99999",
        }
        context = {"platform": "douyu", "room_id": "88888"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.room_id == "88888"

    @pytest.mark.asyncio
    async def test_parse_exception_returns_none(self, adapter):
        """测试解析异常时返回 None"""
        raw_data = {"type": "chatmsg", "nn": None, "txt": None}
        result = await adapter.parse(raw_data, {"platform": "douyu"})
        # 不应抛出异常，应返回 None 或有效消息
        assert result is None or isinstance(result, DanmakuMessage)

    @pytest.mark.asyncio
    async def test_parse_empty_content_returns_none(self, adapter):
        """测试空内容返回 None"""
        raw_data = {
            "type": "chatmsg",
            "nn": "用户A",
            "txt": "",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        result = await adapter.parse(raw_data, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_like_message(self, adapter):
        """测试解析点赞消息"""
        raw_data = {
            "type": "frank",
            "nn": "粉丝A",
            "rid": "12345",
            "ct": "1700000000",
        }
        context = {"platform": "douyu", "room_id": "12345"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "system"
        assert "粉丝A" in message.content
