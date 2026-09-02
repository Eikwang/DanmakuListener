"""DanmakuListener 主类集成测试

验证主类与引擎、适配器的集成逻辑。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.listener import DanmakuListener
from danmaku_listener.engines.proxy_engine import ProxyEngine
from danmaku_listener.engines.browser_engine import BrowserEngine
from danmaku_listener.engines.base import EngineStatus
from danmaku_listener.adapters.douyin import DouyinAdapter
from danmaku_listener.adapters.douyu import DouyuAdapter
from danmaku_listener.adapters.bilibili import BilibiliAdapter
from danmaku_listener.adapters.generic import GenericAdapter
from danmaku_listener.bus.message import DanmakuMessage, GiftInfo


class TestDanmakuListenerIntegration:
    """DanmakuListener 集成测试"""

    @pytest.fixture
    def listener(self):
        """创建监听器实例"""
        return DanmakuListener()

    def test_get_engine_returns_proxy_for_douyin(self, listener):
        """测试抖音平台返回 ProxyEngine"""
        engine = listener._get_engine("douyin")
        assert isinstance(engine, ProxyEngine)

    def test_get_engine_returns_browser_for_other_platforms(self, listener):
        """测试非抖音平台返回 BrowserEngine"""
        engine = listener._get_engine("bilibili")
        assert isinstance(engine, BrowserEngine)

    def test_get_engine_browser_singleton(self, listener):
        """测试浏览器引擎单例共享"""
        engine1 = listener._get_engine("bilibili")
        engine2 = listener._get_engine("taobao")
        assert engine1 is engine2

    def test_get_adapter_returns_douyin_for_douyin(self, listener):
        """测试抖音平台返回 DouyinAdapter"""
        adapter = listener._get_adapter("douyin")
        assert isinstance(adapter, DouyinAdapter)

    def test_get_adapter_returns_bilibili_for_bilibili(self, listener):
        """测试B站平台返回 BilibiliAdapter"""
        adapter = listener._get_adapter("bilibili")
        assert isinstance(adapter, BilibiliAdapter)

    def test_get_adapter_returns_douyu_for_douyu(self, listener):
        """测试斗鱼平台返回 DouyuAdapter"""
        adapter = listener._get_adapter("douyu")
        assert isinstance(adapter, DouyuAdapter)

    def test_get_adapter_returns_generic_for_other_browser_platforms(self, listener):
        """测试其他浏览器模式平台返回 GenericAdapter"""
        adapter = listener._get_adapter("taobao")
        assert isinstance(adapter, GenericAdapter)

    def test_get_adapter_raises_for_unknown_engine_type(self, listener):
        """测试未知引擎类型抛出异常"""
        # 直接调用 _get_adapter 绕过 parse_room_spec 的平台验证
        with patch('danmaku_listener.listener.get_default_engine', return_value="unknown_engine"):
            with pytest.raises(NotImplementedError, match="unknown_engine"):
                listener._get_adapter("fake_platform")

    @pytest.mark.asyncio
    async def test_start_creates_engine_for_douyin(self, listener):
        """测试启动抖音房间时创建 ProxyEngine"""
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock) as mock_start:
            await listener.start(["douyin:123456"])
            mock_start.assert_called_once_with("123456")
            assert "123456" in listener._engines
            assert isinstance(listener._engines["123456"], ProxyEngine)

    @pytest.mark.asyncio
    async def test_start_creates_browser_engine_for_bilibili(self, listener):
        """测试启动 B站房间时创建 BrowserEngine"""
        with patch.object(BrowserEngine, 'start', new_callable=AsyncMock) as mock_start:
            await listener.start(["bilibili:789012"])
            mock_start.assert_called_once_with("789012")
            assert "789012" in listener._engines
            assert isinstance(listener._engines["789012"], BrowserEngine)

    @pytest.mark.asyncio
    async def test_start_mixed_platforms(self, listener):
        """测试混合平台启动（代理+浏览器）"""
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock) as mock_proxy_start, \
             patch.object(BrowserEngine, 'start', new_callable=AsyncMock) as mock_browser_start:
            await listener.start(["douyin:123456", "bilibili:789012"])
            mock_proxy_start.assert_called_once_with("123456")
            mock_browser_start.assert_called_once_with("789012")

    @pytest.mark.asyncio
    async def test_start_rejects_too_many_rooms(self, listener):
        """测试超过最大房间数时抛出异常"""
        rooms = [f"douyin:{i}" for i in range(20)]
        with pytest.raises(ValueError, match="Maximum"):
            await listener.start(rooms)

    @pytest.mark.asyncio
    async def test_start_rejects_invalid_spec(self, listener):
        """测试无效房间规格被跳过"""
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456", "invalid_spec"])
            # 只有有效规格的房间被添加
            assert "123456" in listener._engines

    @pytest.mark.asyncio
    async def test_stop_stops_all_engines(self, listener):
        """测试停止时关闭所有引擎"""
        mock_engine1 = AsyncMock(spec=ProxyEngine)
        mock_engine2 = AsyncMock(spec=ProxyEngine)
        listener._engines = {"room1": mock_engine1, "room2": mock_engine2}
        listener._running = True

        await listener.stop()

        mock_engine1.stop.assert_called_once_with("room1")
        mock_engine2.stop.assert_called_once_with("room2")
        assert listener._running is False
        assert len(listener._engines) == 0

    @pytest.mark.asyncio
    async def test_stop_closes_browser_engine(self, listener):
        """测试停止时关闭浏览器引擎"""
        mock_browser = AsyncMock(spec=BrowserEngine)
        listener._browser_engine = mock_browser
        listener._engines = {"room1": mock_browser}
        listener._running = True

        await listener.stop()

        mock_browser.stop_all.assert_called_once()
        assert listener._browser_engine is None

    @pytest.mark.asyncio
    async def test_handle_raw_message_parses_and_publishes(self, listener):
        """测试原始消息经过适配器解析后发布到事件总线"""
        # Mock 适配器
        mock_adapter = AsyncMock(spec=DouyinAdapter)
        mock_message = DanmakuMessage(
            platform="douyin",
            room_id="123456",
            user_name="test_user",
            content="hello",
            timestamp=0,
            message_type="normal",
        )
        mock_adapter.parse.return_value = mock_message

        # Mock 去重过滤器
        listener._dedup.should_filter = MagicMock(return_value=False)

        # Mock 事件总线
        listener._bus.publish = AsyncMock()

        # 替换适配器获取
        with patch.object(listener, '_get_adapter', return_value=mock_adapter):
            raw_data = {
                "platform": "douyin",
                "room_id": "123456",
                "raw_data": {"method": "WebcastChatMessage", "payload": b'{}'},
                "msg_id": "msg_001",
            }
            await listener._handle_raw_message(raw_data)

        mock_adapter.parse.assert_called_once()
        listener._bus.publish.assert_called_once_with("danmaku", mock_message)

    @pytest.mark.asyncio
    async def test_handle_raw_message_dedup_filters(self, listener):
        """测试去重过滤器过滤重复消息"""
        listener._dedup.should_filter = MagicMock(return_value=True)
        mock_adapter = AsyncMock(spec=DouyinAdapter)

        with patch.object(listener, '_get_adapter', return_value=mock_adapter):
            raw_data = {
                "platform": "douyin",
                "room_id": "123456",
                "raw_data": {"method": "WebcastChatMessage"},
                "msg_id": "msg_001",
            }
            await listener._handle_raw_message(raw_data)

        # 重复消息不应调用适配器
        mock_adapter.parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_message_callback_routes_to_bus(self, listener):
        """测试引擎消息回调将原始消息路由到事件总线"""
        listener._bus.publish = AsyncMock()

        # 模拟引擎发送消息
        raw_msg = {
            "platform": "douyin",
            "room_id": "123456",
            "raw_data": {"method": "WebcastChatMessage", "payload": b'{}'},
            "msg_id": "msg_001",
        }

        # 获取引擎消息回调并调用
        callback = listener._create_engine_message_callback("123456")
        await callback(raw_msg)

        listener._bus.publish.assert_called_once_with("raw_message", raw_msg)

    @pytest.mark.asyncio
    async def test_engine_error_callback_routes_to_bus(self, listener):
        """测试引擎错误回调路由到事件总线"""
        listener._bus.publish = AsyncMock()

        error = Exception("connection lost")
        callback = listener._create_engine_error_callback("123456")
        await callback(error)

        listener._bus.publish.assert_called_once()
        call_args = listener._bus.publish.call_args
        assert call_args[0][0] == "error"

    @pytest.mark.asyncio
    async def test_context_manager(self, listener):
        """测试上下文管理器协议"""
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock), \
             patch.object(ProxyEngine, 'stop', new_callable=AsyncMock):
            async with listener as l:
                assert l is listener

    @pytest.mark.asyncio
    async def test_handle_raw_message_uses_bilibili_adapter_for_bilibili(self, listener):
        """测试B站平台使用 BilibiliAdapter 解析消息"""
        # Mock 去重过滤器
        listener._dedup.should_filter = MagicMock(return_value=False)

        # Mock 事件总线
        listener._bus.publish = AsyncMock()

        raw_data = {
            "platform": "bilibili",
            "room_id": "789012",
            "raw_data": {
                "cmd": "DANMU_MSG",
                "info": [[0, 1, 25, 16777215, 1700000000], "B站弹幕", "用户A"],
            },
            "msg_id": "msg_bili_001",
        }
        await listener._handle_raw_message(raw_data)

        # 验证消息被解析并发布
        listener._bus.publish.assert_called_once()
        call_args = listener._bus.publish.call_args
        assert call_args[0][0] == "danmaku"
        message = call_args[0][1]
        assert isinstance(message, DanmakuMessage)
        assert message.platform == "bilibili"
        assert message.content == "B站弹幕"
