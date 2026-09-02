"""Task-14: Listener 集成与端到端验证 测试

验证 DanmakuListener 与 ProxyEngine 的完整集成：
- start(["douyin:123456"]) → ProxyEngine 单例创建并启动 → AC-001
- 两个 douyin 房间共享同一 ProxyEngine 实例
- WS 弹幕数据注入 → on_danmaku 收到 DanmakuMessage → AC-004
- 礼物消息注入 → DanmakuMessage(message_type="gift") → AC-005
- 重复 msgId → on_danmaku 只触发一次 → AC-019
- stop() → ProxyEngine 停止，系统代理恢复 → AC-008
- 混合模式 → ProxyEngine + BrowserEngine 各自启动
"""

import gzip
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
from danmaku_listener.adapters.protocols.proto.message_pb2 import (
    Response, Message, ChatMessage, GiftMessage, LikeMessage, MemberMessage, User,
)
from danmaku_listener.bus.message import DanmakuMessage


def _build_wss_response_with_chat(
    content: str = "你好",
    nickname: str = "测试用户",
    msg_id: int = 123,
) -> bytes:
    """构造包含 ChatMessage 的完整 WssResponse 序列化字节"""
    chat = ChatMessage(content=content)
    chat.user.nickname = nickname

    msg = Message(method="WebcastChatMessage", msgId=msg_id)
    msg.payload = chat.SerializeToString()

    response = Response()
    response.messages.append(msg)

    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    wss.payload = response.SerializeToString()
    return wss.SerializeToString()


def _build_wss_response_with_gift(
    nickname: str = "送礼者",
    gift_name: str = "火箭",
    diamond_count: int = 100,
    repeat_count: int = 2,
    msg_id: int = 456,
) -> bytes:
    """构造包含 GiftMessage 的 WssResponse"""
    gift = GiftMessage()
    gift.user.nickname = nickname
    gift.gift.name = gift_name
    gift.gift.diamondCount = diamond_count
    gift.repeatCount = repeat_count

    msg = Message(method="WebcastGiftMessage", msgId=msg_id)
    msg.payload = gift.SerializeToString()

    response = Response()
    response.messages.append(msg)

    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    wss.payload = response.SerializeToString()
    return wss.SerializeToString()


class TestProxyEngineSingleton:
    """ProxyEngine 单例模式测试 → AC-001"""

    @pytest.mark.asyncio
    async def test_single_douyin_room_creates_proxy_engine(self):
        """start(["douyin:123456"]) → ProxyEngine 单例创建并启动"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        # Mock ProxyEngine.start 避免真正启动 mitmproxy
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock) as mock_start:
            await listener.start(["douyin:123456"])

            # 应创建 ProxyEngine 实例
            assert "123456" in listener._engines
            assert isinstance(listener._engines["123456"], ProxyEngine)
            mock_start.assert_called_once_with("123456")

        await listener.stop()

    @pytest.mark.asyncio
    async def test_two_douyin_rooms_share_same_proxy_engine(self):
        """两个 douyin 房间共享同一 ProxyEngine 实例"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock) as mock_start:
            await listener.start(["douyin:111", "douyin:222"])

            # 两个房间应该是同一个 ProxyEngine 实例
            assert listener._engines["111"] is listener._engines["222"]
            assert isinstance(listener._engines["111"], ProxyEngine)

            # start 应被调用两次（每个房间一次）
            assert mock_start.call_count == 2

        await listener.stop()

    @pytest.mark.asyncio
    async def test_proxy_engine_stored_as_singleton_attribute(self):
        """ProxyEngine 单例存储在 listener._proxy_engine 属性"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

            # 应有 _proxy_engine 属性
            assert hasattr(listener, '_proxy_engine')
            assert listener._proxy_engine is not None
            assert isinstance(listener._proxy_engine, ProxyEngine)

            # _engines 中的实例应与 _proxy_engine 相同
            assert listener._engines["123456"] is listener._proxy_engine

        await listener.stop()


class TestDanmakuMessageRouting:
    """弹幕消息路由测试 → AC-004, AC-005"""

    @pytest.mark.asyncio
    async def test_chat_message_routes_to_on_danmaku(self):
        """WS 弹幕数据注入 → on_danmaku 收到 DanmakuMessage(normal) → AC-004"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        # 注册弹幕回调
        danmaku_cb = AsyncMock()
        listener.on_danmaku(danmaku_cb)

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        # 模拟 ProxyEngine 发送弹幕消息（Protobuf 解码后的格式）
        engine = listener._engines["123456"]
        await engine._emit_message({
            "type": "danmaku",
            "room_id": "123456",
            "method": "WebcastChatMessage",
            "payload": ChatMessage(content="你好").SerializeToString(),
            "msg_id": "123",
            "platform": "douyin",
        })

        # 等待异步事件传播
        import asyncio
        await asyncio.sleep(0.05)

        # on_danmaku 应收到 DanmakuMessage
        danmaku_cb.assert_called_once()
        msg = danmaku_cb.call_args[0][0]
        assert isinstance(msg, DanmakuMessage)
        assert msg.platform == "douyin"
        assert msg.content == "你好"
        assert msg.message_type == "normal"

        await listener.stop()

    @pytest.mark.asyncio
    async def test_gift_message_routes_to_on_danmaku(self):
        """礼物消息注入 → on_danmaku 收到 DanmakuMessage(gift) → AC-005"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        danmaku_cb = AsyncMock()
        listener.on_danmaku(danmaku_cb)

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        engine = listener._engines["123456"]

        # 构造礼物消息
        gift = GiftMessage()
        gift.user.nickname = "送礼者"
        gift.gift.name = "火箭"
        gift.gift.diamondCount = 100
        gift.repeatCount = 2

        await engine._emit_message({
            "type": "danmaku",
            "room_id": "123456",
            "method": "WebcastGiftMessage",
            "payload": gift.SerializeToString(),
            "msg_id": "456",
            "platform": "douyin",
        })

        import asyncio
        await asyncio.sleep(0.05)

        danmaku_cb.assert_called_once()
        msg = danmaku_cb.call_args[0][0]
        assert isinstance(msg, DanmakuMessage)
        assert msg.message_type == "gift"
        assert msg.gift_info is not None
        assert msg.gift_info.gift_name == "火箭"
        assert msg.gift_info.gift_count == 2
        assert msg.gift_info.gift_value == 100

        await listener.stop()


class TestDedupInIntegration:
    """去重集成测试 → AC-019"""

    @pytest.mark.asyncio
    async def test_duplicate_msg_id_only_triggers_once(self):
        """重复 msgId → on_danmaku 只触发一次 → AC-019"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        danmaku_cb = AsyncMock()
        listener.on_danmaku(danmaku_cb)

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        engine = listener._engines["123456"]

        # 发送相同 msg_id 的消息两次
        msg_data = {
            "type": "danmaku",
            "room_id": "123456",
            "method": "WebcastChatMessage",
            "payload": ChatMessage(content="你好").SerializeToString(),
            "msg_id": "dup-001",
            "platform": "douyin",
        }

        await engine._emit_message(msg_data)
        await engine._emit_message(msg_data)  # 重复

        import asyncio
        await asyncio.sleep(0.05)

        # 只应触发一次
        danmaku_cb.assert_called_once()

        await listener.stop()


class TestListenerStop:
    """停止监听测试 → AC-008"""

    @pytest.mark.asyncio
    async def test_stop_stops_proxy_engine(self):
        """stop() → ProxyEngine 停止"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        with patch.object(ProxyEngine, 'stop', new_callable=AsyncMock) as mock_stop:
            await listener.stop()

            mock_stop.assert_called_once_with("123456")

    @pytest.mark.asyncio
    async def test_stop_clears_engines(self):
        """stop() → _engines 被清空"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        with patch.object(ProxyEngine, 'stop', new_callable=AsyncMock):
            await listener.stop()

        assert len(listener._engines) == 0

    @pytest.mark.asyncio
    async def test_stop_clears_proxy_engine_singleton(self):
        """stop() → _proxy_engine 被清空"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        with patch.object(ProxyEngine, 'stop', new_callable=AsyncMock):
            await listener.stop()

        assert listener._proxy_engine is None


class TestMixedMode:
    """混合模式测试"""

    @pytest.mark.asyncio
    async def test_mixed_platforms_start_both_engines(self):
        """start(["douyin:111", "bilibili:222"]) → ProxyEngine + BrowserEngine 各自启动"""
        from danmaku_listener.listener import DanmakuListener
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.browser_engine import BrowserEngine

        listener = DanmakuListener()

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock) as mock_proxy_start, \
             patch.object(BrowserEngine, 'start', new_callable=AsyncMock) as mock_browser_start:

            await listener.start(["douyin:111", "bilibili:222"])

            # ProxyEngine 应启动
            mock_proxy_start.assert_called_once_with("111")
            assert isinstance(listener._engines["111"], ProxyEngine)

            # BrowserEngine 应启动
            mock_browser_start.assert_called_once_with("222")
            assert isinstance(listener._engines["222"], BrowserEngine)

            # 两个引擎不是同一个实例
            assert listener._engines["111"] is not listener._engines["222"]

        await listener.stop()
