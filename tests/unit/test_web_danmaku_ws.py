"""Task-07: 弹幕 WebSocket 推送 — 单元测试

验证标准：
1. DanmakuListener 收到 DanmakuMessage → 所有 WS 客户端收到 {"type": "danmaku", "data": {...}}
2. 推送消息的 data 包含 platform, room_id, user_name, content, timestamp, message_type
3. 礼物消息推送 data.message_type == "gift" 且包含 gift_info
4. 关键词过滤启用时，normal 且 content 包含屏蔽词 → 不推送
5. 关键词过滤对 gift 不生效
6. 关键词过滤对 system 不生效
7. WS 客户端连接时收到当前状态消息 {"type": "status", ...}
8. 重连事件 → WS 客户端收到 {"type": "reconnect", "data": {"room_id": ..., "status": "reconnecting"}}
9. 多房间弹幕按时间顺序推送
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from danmaku_listener.web.bridge import DanmakuBridge
from danmaku_listener.web.app import create_app


# ── 辅助工具 ──────────────────────────────────────────────

def _make_bridge_with_mocked_listener():
    """创建 mock listener 的桥接器"""
    bridge = DanmakuBridge()
    bridge._listener = MagicMock()
    bridge._listener.start = AsyncMock()
    bridge._listener.stop = AsyncMock()
    bridge._listener.on_danmaku = MagicMock()
    bridge._listener.on_error = MagicMock()
    bridge._listener.on_reconnect = MagicMock()
    bridge._listener.on_status_change = MagicMock()
    return bridge


def _make_danmaku_message(**overrides):
    """构造真实 DanmakuMessage（契约 v1 桥接输入）"""
    from danmaku_listener.bus.message import DanmakuMessage
    data = {
        "platform": "douyin",
        "room_id": "123456",
        "user_name": "测试用户",
        "content": "你好",
        "timestamp": 1722000000,
        "message_type": "normal",
        "gift_info": None,
    }
    data.update(overrides)
    return DanmakuMessage(**data)


def _make_system_message(**overrides):
    """构造真实系统类 DanmakuMessage"""
    from danmaku_listener.bus.message import DanmakuMessage
    data = {
        "platform": "douyin",
        "room_id": "123456",
        "user_name": "",
        "content": "房间状态更新",
        "timestamp": 1722000000,
        "message_type": "system",
        "gift_info": None,
    }
    data.update(overrides)
    return DanmakuMessage(**data)


def _make_gift_message(**overrides):
    """构造真实礼物 DanmakuMessage"""
    from danmaku_listener.bus.message import DanmakuMessage, GiftInfo
    data = {
        "platform": "douyin",
        "room_id": "123456",
        "user_name": "送礼者",
        "content": "送出了 火箭 x2",
        "timestamp": 1722000000,
        "message_type": "gift",
        "gift_info": GiftInfo(
            user_name="送礼者",
            gift_name="火箭",
            gift_count=2,
            gift_value=100,
        ),
    }
    data.update(overrides)
    return DanmakuMessage(**data)


def _make_enter_message(**overrides):
    """构造真实进房 DanmakuMessage"""
    from danmaku_listener.bus.message import DanmakuMessage
    data = {
        "platform": "douyin",
        "room_id": "123456",
        "user_name": "用户A",
        "content": "进入了直播间",
        "timestamp": 1722000000,
        "message_type": "system",
        "gift_info": None,
    }
    data.update(overrides)
    return DanmakuMessage(**data)


# ── 测试类 ──────────────────────────────────────────────


class TestOnDanmakuHandler:
    """验证标准 1, 2, 3: 弹幕消息推送"""

    @pytest.mark.asyncio
    async def test_danmaku_broadcasts_to_all_ws_clients(self):
        """DanmakuMessage → 所有 WS 客户端收到 {"type": "danmaku", "data": {...}}"""
        bridge = _make_bridge_with_mocked_listener()
        # 模拟两个 WS 客户端
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await bridge.add_ws_client(ws1)
        await bridge.add_ws_client(ws2)

        msg = _make_danmaku_message()
        await bridge._on_danmaku_handler(msg)

        # 验证两个客户端都收到消息
        assert ws1.send_str.call_count == 1
        assert ws2.send_str.call_count == 1

        sent1 = json.loads(ws1.send_str.call_args[0][0])
        assert sent1["category"] == "business"
        assert sent1["type"] == "DANMU"
        assert sent1["platform"] == "douyin"
        assert sent1["payload"]["user_name"] == "测试用户"
        assert sent1["payload"]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_danmaku_data_contains_all_required_fields(self):
        """推送消息的 data 包含 platform, room_id, user_name, content, timestamp, message_type"""
        bridge = _make_bridge_with_mocked_listener()
        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_danmaku_message()
        await bridge._on_danmaku_handler(msg)

        sent = json.loads(ws.send_str.call_args[0][0])
        for field in ["platform", "room_id", "seq", "timestamp", "engine", "payload"]:
            assert field in sent, f"Missing envelope field: {field}"
        for field in ["user_name", "content"]:
            assert field in sent["payload"], f"Missing payload field: {field}"

    @pytest.mark.asyncio
    async def test_gift_message_includes_gift_info(self):
        """礼物消息推送 data.message_type == "gift" 且包含 gift_info"""
        bridge = _make_bridge_with_mocked_listener()
        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_gift_message()
        await bridge._on_danmaku_handler(msg)

        sent = json.loads(ws.send_str.call_args[0][0])
        assert sent["type"] == "GIFT"
        assert sent["payload"]["gift_name"] == "火箭"
        assert sent["payload"]["gift_count"] == 2


class TestKeywordFilter:
    """验证标准 4, 5, 6: 关键词过滤逻辑"""

    @pytest.mark.asyncio
    async def test_normal_danmaku_with_blocked_keyword_not_pushed(self):
        """关键词过滤启用时，normal 且 content 包含屏蔽词 → 不推送"""
        bridge = _make_bridge_with_mocked_listener()
        bridge._blocked_keywords = ["广告"]
        bridge._keyword_filter_enabled = True

        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_danmaku_message(content="这是广告内容")
        msg.content = "这是广告内容"

        await bridge._on_danmaku_handler(msg)

        # 不应推送
        ws.send_str.assert_not_called()

    @pytest.mark.asyncio
    async def test_gift_message_not_filtered_by_keyword(self):
        """关键词过滤对 gift 不生效 → 礼物消息始终推送"""
        bridge = _make_bridge_with_mocked_listener()
        bridge._blocked_keywords = ["火箭"]
        bridge._keyword_filter_enabled = True

        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_gift_message()
        await bridge._on_danmaku_handler(msg)

        # 礼物消息应推送
        assert ws.send_str.call_count == 1

    @pytest.mark.asyncio
    async def test_system_message_not_filtered_by_keyword(self):
        """关键词过滤对 system 不生效 → 系统消息始终推送"""
        bridge = _make_bridge_with_mocked_listener()
        bridge._blocked_keywords = ["进入"]
        bridge._keyword_filter_enabled = True

        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_system_message()
        msg.content = "进入了直播间"

        await bridge._on_danmaku_handler(msg)

        # 系统消息应推送
        assert ws.send_str.call_count == 1

    @pytest.mark.asyncio
    async def test_keyword_filter_disabled_passes_all(self):
        """关键词过滤禁用时，所有消息都推送"""
        bridge = _make_bridge_with_mocked_listener()
        bridge._blocked_keywords = ["广告"]
        bridge._keyword_filter_enabled = False

        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        msg = _make_danmaku_message(content="这是广告内容")
        msg.content = "这是广告内容"

        await bridge._on_danmaku_handler(msg)

        # 过滤禁用，应推送
        assert ws.send_str.call_count == 1


class TestOnErrorHandler:
    """验证标准: 错误事件广播"""

    @pytest.mark.asyncio
    async def test_error_broadcasts_to_ws_clients(self):
        """错误事件 → WS 客户端收到 {"type": "error", "data": {...}}"""
        bridge = _make_bridge_with_mocked_listener()
        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        error = Exception("连接超时")
        await bridge._on_error_handler(error)

        sent = json.loads(ws.send_str.call_args[0][0])
        assert sent["type"] == "ROUTE_FAILED"
        assert "连接超时" in sent["payload"]["failure"]["fix_hint"]


class TestOnReconnectHandler:
    """验证标准 8: 重连事件广播"""

    @pytest.mark.asyncio
    async def test_reconnect_broadcasts_to_ws_clients(self):
        """重连事件 → WS 客户端收到 {"type": "reconnect", "data": {"room_id": ..., "status": "reconnecting"}}"""
        bridge = _make_bridge_with_mocked_listener()
        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        await bridge._on_reconnect_handler("123456")

        sent = json.loads(ws.send_str.call_args[0][0])
        assert sent["type"] == "ENGINE_STATUS"
        assert sent["room_id"] == "123456"
        assert sent["payload"]["detail"] == "reconnecting"


class TestCallbackRegistration:
    """验证回调注册到 DanmakuListener"""

    @pytest.mark.asyncio
    async def test_setup_callbacks_registers_all_handlers(self):
        """_setup_callbacks 应注册 on_danmaku, on_error, on_reconnect, on_status_change"""
        bridge = DanmakuBridge()
        bridge._listener = MagicMock()
        bridge._listener.on_danmaku = MagicMock()
        bridge._listener.on_error = MagicMock()
        bridge._listener.on_reconnect = MagicMock()
        bridge._listener.on_status_change = MagicMock()

        bridge._setup_callbacks()

        bridge._listener.on_danmaku.assert_called_once()
        bridge._listener.on_error.assert_called_once()
        bridge._listener.on_reconnect.assert_called_once()
        bridge._listener.on_status_change.assert_called_once()


class TestMultiRoomDanmaku:
    """验证标准 9: 多房间弹幕按时间顺序推送"""

    @pytest.mark.asyncio
    async def test_multi_room_danmaku_pushed_in_order(self):
        """多房间弹幕按时间顺序推送（不按房间分组）"""
        bridge = _make_bridge_with_mocked_listener()
        ws = AsyncMock()
        await bridge.add_ws_client(ws)

        # 房间1的弹幕（时间戳较早）
        msg1 = _make_danmaku_message(room_id="111", content="房间1消息", timestamp=100)

        # 房间2的弹幕（时间戳较晚）
        msg2 = _make_danmaku_message(room_id="222", content="房间2消息", timestamp=200)

        await bridge._on_danmaku_handler(msg1)
        await bridge._on_danmaku_handler(msg2)

        # 验证两条消息按顺序推送
        assert ws.send_str.call_count == 2
        first = json.loads(ws.send_str.call_args_list[0][0][0])
        second = json.loads(ws.send_str.call_args_list[1][0][0])
        assert first["room_id"] == "111"
        assert second["room_id"] == "222"


class TestWSInitialStatus:
    """验证标准 7: WS 客户端连接时收到当前状态消息"""

    @pytest.mark.asyncio
    async def test_ws_client_receives_initial_status(self):
        """WS 连接时收到 {"type": "status", ...} 消息"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge

        async with TestClient(TestServer(app)) as client:
            ws = await client.ws_connect("/ws")
            msg = await ws.receive_json()
            assert msg["type"] == "status"
            assert "backend_connected" in msg["data"]
            await ws.close()
