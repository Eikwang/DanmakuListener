"""B站平台适配器测试

验证 BilibiliAdapter 的消息解析功能。
"""

import json
import pytest
from unittest.mock import AsyncMock

from danmaku_listener.adapters.bilibili import BilibiliAdapter
from danmaku_listener.bus.message import DanmakuMessage


class TestBilibiliAdapter:
    """B站平台适配器测试"""

    @pytest.fixture
    def adapter(self):
        """创建B站适配器实例"""
        return BilibiliAdapter()

    def test_platform_property(self, adapter):
        """测试平台标识为 bilibili"""
        assert adapter.platform == "bilibili"

    def test_can_parse_dict_with_cmd_field(self, adapter):
        """测试能解析包含 cmd 字段的字典"""
        data = {"cmd": "DANMU_MSG", "info": [["0", "1", "25", "16777215", "1700000000", "0", "0", "0", "3", "用户A", "hello"]]}
        assert adapter.can_parse(data) is True

    def test_can_parse_rejects_non_dict(self, adapter):
        """测试拒绝非字典类型"""
        assert adapter.can_parse("string") is False
        assert adapter.can_parse(123) is False
        assert adapter.can_parse(None) is False

    def test_can_parse_rejects_empty_dict(self, adapter):
        """测试拒绝空字典"""
        assert adapter.can_parse({}) is False

    def test_can_parse_rejects_dict_without_cmd(self, adapter):
        """测试拒绝没有 cmd 字段的字典"""
        assert adapter.can_parse({"user": "test"}) is False

    @pytest.mark.asyncio
    async def test_parse_danmu_message(self, adapter):
        """测试解析普通弹幕消息"""
        raw_data = {
            "cmd": "DANMU_MSG",
            "info": [
                [0, 1, 25, 16777215, 1700000000, 0, 0, 0, 3],
                "大家好",
                "用户A",
            ],
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert isinstance(message, DanmakuMessage)
        assert message.platform == "bilibili"
        assert message.room_id == "789012"
        assert message.user_name == "用户A"
        assert message.content == "大家好"
        assert message.message_type == "normal"

    @pytest.mark.asyncio
    async def test_parse_gift_message(self, adapter):
        """测试解析礼物消息"""
        raw_data = {
            "cmd": "SEND_GIFT",
            "data": {
                "uname": "土豪哥",
                "giftName": "小电视",
                "num": 5,
                "coin_type": "gold",
                "total_coin": 5000,
                "roomid": "789012",
            },
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "gift"
        assert message.gift_info is not None
        assert message.gift_info.gift_name == "小电视"
        assert message.gift_info.gift_count == 5
        assert message.gift_info.gift_value == 5000

    @pytest.mark.asyncio
    async def test_parse_enter_message(self, adapter):
        """测试解析进房消息"""
        raw_data = {
            "cmd": "INTERACT_WORD",
            "data": {
                "uname": "新用户",
                "room_id": "789012",
            },
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "system"
        assert "新用户" in message.content
        assert "进入" in message.content

    @pytest.mark.asyncio
    async def test_parse_super_chat_message(self, adapter):
        """测试解析醒目留言消息"""
        raw_data = {
            "cmd": "SUPER_CHAT_MESSAGE",
            "data": {
                "user_info": {
                    "uname": "SC用户",
                },
                "message": "醒目留言内容",
                "price": 30,
                "room_id": "789012",
            },
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "normal"
        assert message.content == "醒目留言内容"
        assert message.user_name == "SC用户"

    @pytest.mark.asyncio
    async def test_parse_unknown_cmd_returns_none(self, adapter):
        """测试未知 cmd 返回 None"""
        raw_data = {
            "cmd": "UNKNOWN_CMD",
            "data": {},
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        result = await adapter.parse(raw_data, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_without_context_uses_defaults(self, adapter):
        """测试无 context 时使用默认值"""
        raw_data = {
            "cmd": "DANMU_MSG",
            "info": [
                [0, 1, 25, 16777215, 1700000000, 0, 0, 0, 3],
                "hello",
                "用户A",
            ],
        }

        message = await adapter.parse(raw_data)

        assert message is not None
        assert message.platform == "bilibili"

    @pytest.mark.asyncio
    async def test_parse_context_room_id_overrides_data(self, adapter):
        """测试 context 中的 room_id 覆盖数据中的 roomid"""
        raw_data = {
            "cmd": "SEND_GIFT",
            "data": {
                "uname": "test",
                "giftName": "flower",
                "num": 1,
                "total_coin": 100,
                "roomid": "99999",
            },
        }
        context = {"platform": "bilibili", "room_id": "88888"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.room_id == "88888"

    @pytest.mark.asyncio
    async def test_parse_exception_returns_none(self, adapter):
        """测试解析异常时返回 None"""
        raw_data = {"cmd": "DANMU_MSG", "info": None}
        result = await adapter.parse(raw_data, {"platform": "bilibili"})
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_empty_danmu_returns_none(self, adapter):
        """测试空弹幕内容返回 None"""
        raw_data = {
            "cmd": "DANMU_MSG",
            "info": [
                [0, 1, 25, 16777215, 1700000000],
                "",
                "用户A",
            ],
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        result = await adapter.parse(raw_data, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_guard_buy_message(self, adapter):
        """测试解析上舰消息"""
        raw_data = {
            "cmd": "GUARD_BUY",
            "data": {
                "username": "舰长用户",
                "gift_name": "舰长",
                "num": 1,
                "price": 138000,
                "room_id": "789012",
            },
        }
        context = {"platform": "bilibili", "room_id": "789012"}

        message = await adapter.parse(raw_data, context)

        assert message is not None
        assert message.message_type == "gift"
        assert message.gift_info is not None
        assert message.gift_info.gift_name == "舰长"
