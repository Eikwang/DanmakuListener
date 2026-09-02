"""消息总线模块测试

验证 EventBus、DanmakuMessage、DedupFilter 的核心功能。
"""

import time
import pytest
from unittest.mock import AsyncMock

from danmaku_listener.bus.event_bus import EventBus
from danmaku_listener.bus.message import DanmakuMessage, GiftInfo, MessageType
from danmaku_listener.bus.dedup_filter import DedupFilter


# ===== EventBus 测试 =====


class TestEventBus:
    """事件总线测试"""

    @pytest.fixture
    def bus(self):
        """创建事件总线实例"""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, bus):
        """测试订阅和发布事件"""
        callback = AsyncMock()
        await bus.subscribe("test_event", callback)

        await bus.publish("test_event", {"key": "value"})

        callback.assert_called_once_with({"key": "value"})

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        """测试多个订阅者"""
        cb1 = AsyncMock()
        cb2 = AsyncMock()

        await bus.subscribe("event", cb1)
        await bus.subscribe("event", cb2)

        await bus.publish("event", "data")

        cb1.assert_called_once_with("data")
        cb2.assert_called_once_with("data")

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self, bus):
        """测试无订阅者时发布不报错"""
        await bus.publish("nonexistent", "data")

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        """测试取消订阅"""
        callback = AsyncMock()
        await bus.subscribe("event", callback)
        await bus.unsubscribe("event", callback)

        await bus.publish("event", "data")

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_affect_others(self, bus):
        """测试回调异常不影响其他回调"""
        good_cb = AsyncMock()
        bad_cb = AsyncMock(side_effect=Exception("boom"))

        await bus.subscribe("event", bad_cb)
        await bus.subscribe("event", good_cb)

        await bus.publish("event", "data")

        good_cb.assert_called_once_with("data")

    def test_has_subscribers(self, bus):
        """测试检查订阅者"""
        assert bus.has_subscribers("event") is False

    @pytest.mark.asyncio
    async def test_has_subscribers_after_subscribe(self, bus):
        """测试订阅后检查订阅者"""
        await bus.subscribe("event", AsyncMock())
        assert bus.has_subscribers("event") is True

    def test_get_subscriber_count(self, bus):
        """测试获取订阅者数量"""
        assert bus.get_subscriber_count("event") == 0


# ===== DanmakuMessage 测试 =====


class TestDanmakuMessage:
    """弹幕消息模型测试"""

    def test_create_normal_message(self):
        """测试创建普通弹幕消息"""
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123456",
            user_name="test_user",
            content="hello",
            timestamp=1700000000,
            message_type="normal",
        )
        assert msg.platform == "douyin"
        assert msg.content == "hello"
        assert msg.message_type == "normal"
        assert msg.gift_info is None

    def test_create_gift_message(self):
        """测试创建礼物消息"""
        gift = GiftInfo(
            user_name="giver",
            gift_name="rocket",
            gift_count=2,
            gift_value=500,
        )
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123456",
            user_name="giver",
            content="sent rocket",
            timestamp=1700000000,
            message_type="gift",
            gift_info=gift,
        )
        assert msg.is_gift is True
        assert msg.gift_info.gift_name == "rocket"
        assert msg.gift_info.gift_count == 2

    def test_normal_message_is_not_gift(self):
        """测试普通消息 is_gift 为 False"""
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123",
            user_name="user",
            content="hi",
            timestamp=0,
            message_type="normal",
        )
        assert msg.is_gift is False

    def test_timestamp_negative_raises(self):
        """测试负时间戳抛出异常"""
        with pytest.raises(ValueError, match="positive"):
            DanmakuMessage(
                platform="douyin",
                room_id="123",
                user_name="user",
                content="hi",
                timestamp=-1,
                message_type="normal",
            )

    def test_timestamp_zero_is_valid(self):
        """测试时间戳 0 是合法的"""
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123",
            user_name="user",
            content="hi",
            timestamp=0,
            message_type="normal",
        )
        assert msg.timestamp == 0

    def test_formatted_time(self):
        """测试格式化时间"""
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123",
            user_name="user",
            content="hi",
            timestamp=1700000000,
            message_type="normal",
        )
        assert isinstance(msg.formatted_time, str)
        assert len(msg.formatted_time) > 0

    def test_to_dict(self):
        """测试转换为字典"""
        msg = DanmakuMessage(
            platform="douyin",
            room_id="123",
            user_name="user",
            content="hi",
            timestamp=1700000000,
            message_type="normal",
        )
        d = msg.to_dict()
        assert isinstance(d, dict)
        assert d["platform"] == "douyin"
        assert d["content"] == "hi"

    def test_extra_fields_forbidden(self):
        """测试额外字段被禁止"""
        with pytest.raises(Exception):
            DanmakuMessage(
                platform="douyin",
                room_id="123",
                user_name="user",
                content="hi",
                timestamp=0,
                message_type="normal",
                extra_field="not_allowed",
            )

    def test_message_type_enum(self):
        """测试消息类型枚举值"""
        assert MessageType.NORMAL == "normal"
        assert MessageType.GIFT == "gift"
        assert MessageType.SYSTEM == "system"


# ===== DedupFilter 测试 =====


class TestDedupFilter:
    """去重过滤器测试"""

    @pytest.fixture
    def dedup(self):
        """创建去重过滤器实例"""
        return DedupFilter(window_size=10)

    def test_first_message_not_filtered(self, dedup):
        """测试首次消息不被过滤"""
        assert dedup.should_filter("room1", "msg1") is False

    def test_duplicate_message_filtered(self, dedup):
        """测试重复消息被过滤"""
        dedup.should_filter("room1", "msg1")
        assert dedup.should_filter("room1", "msg1") is True

    def test_different_messages_not_filtered(self, dedup):
        """测试不同消息不被过滤"""
        dedup.should_filter("room1", "msg1")
        assert dedup.should_filter("room1", "msg2") is False

    def test_different_rooms_independent(self, dedup):
        """测试不同房间独立去重"""
        dedup.should_filter("room1", "msg1")
        assert dedup.should_filter("room2", "msg1") is False

    def test_empty_room_id_not_filtered(self, dedup):
        """测试空房间 ID 不被过滤"""
        assert dedup.should_filter("", "msg1") is False

    def test_empty_msg_id_not_filtered(self, dedup):
        """测试空消息 ID 不被过滤"""
        assert dedup.should_filter("room1", "") is False

    def test_clear_room(self, dedup):
        """测试清除指定房间缓存"""
        dedup.should_filter("room1", "msg1")
        dedup.clear_room("room1")
        # 清除后相同消息不再被过滤
        assert dedup.should_filter("room1", "msg1") is False

    def test_clear_all(self, dedup):
        """测试清除所有缓存"""
        dedup.should_filter("room1", "msg1")
        dedup.should_filter("room2", "msg2")
        dedup.clear_all()
        assert dedup.should_filter("room1", "msg1") is False
        assert dedup.should_filter("room2", "msg2") is False

    def test_get_stats(self, dedup):
        """测试获取统计信息"""
        dedup.should_filter("room1", "msg1")
        dedup.should_filter("room1", "msg2")
        dedup.should_filter("room2", "msg3")

        stats = dedup.get_stats()
        assert stats["rooms"] == 2
        assert stats["total_messages"] == 3

    def test_window_size_limit(self):
        """测试窗口大小限制"""
        dedup = DedupFilter(window_size=3)
        # 添加 4 条消息
        dedup.should_filter("room1", "msg1")
        dedup.should_filter("room1", "msg2")
        dedup.should_filter("room1", "msg3")
        dedup.should_filter("room1", "msg4")
        # msg1 已被移出窗口，不再被过滤
        assert dedup.should_filter("room1", "msg1") is False
