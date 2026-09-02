"""断线重连机制集成测试

验证 ReconnectManager 与引擎的错误处理集成。
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from danmaku_listener.engines.proxy_engine import ProxyEngine
from danmaku_listener.engines.browser_engine import BrowserEngine
from danmaku_listener.engines.base import EngineStatus
from danmaku_listener.managers.reconnect_manager import ReconnectManager
from danmaku_listener.listener import DanmakuListener


class TestProxyEngineReconnect:
    """ProxyEngine 断线重连测试"""

    @pytest.fixture
    def engine(self):
        """创建代理引擎实例"""
        return ProxyEngine()

    @pytest.mark.asyncio
    async def test_engine_error_triggers_reconnect(self, engine):
        """测试引擎错误触发重连流程"""
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        # Mock restart 作为重连回调
        with patch.object(engine, 'restart', new_callable=AsyncMock) as mock_restart:
            mock_restart.return_value = None
            # 模拟重连成功
            result = await engine._handle_error_with_reconnect(
                "room1", Exception("connection lost")
            )
            assert result is True
            mock_restart.assert_called_once_with("room1")

    @pytest.mark.asyncio
    async def test_engine_reconnect_failure_emits_error(self, engine):
        """测试重连失败后触发错误回调"""
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        error_callback = AsyncMock()
        engine.on_error(error_callback)

        # Mock restart 抛出异常（重连失败）
        with patch.object(engine, 'restart', new_callable=AsyncMock, side_effect=Exception("restart failed")):
            result = await engine._handle_error_with_reconnect(
                "room1", Exception("connection lost")
            )
            assert result is False
            # 重连失败后应触发错误回调
            error_callback.assert_called()

    @pytest.mark.asyncio
    async def test_engine_reconnect_success_publishes_reconnect_event(self, engine):
        """测试重连成功后发布重连事件"""
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        message_callback = AsyncMock()
        engine.on_message(message_callback)

        with patch.object(engine, 'restart', new_callable=AsyncMock):
            await engine._handle_error_with_reconnect(
                "room1", Exception("connection lost")
            )
            # 重连成功后应发布状态消息
            message_callback.assert_called_once()
            msg_data = message_callback.call_args[0][0]
            assert msg_data.get("type") == "reconnect_success"
            assert msg_data.get("room_id") == "room1"

    @pytest.mark.asyncio
    async def test_engine_without_reconnect_manager_just_emits_error(self, engine):
        """测试无重连管理器时直接触发错误回调"""
        error_callback = AsyncMock()
        engine.on_error(error_callback)

        error = Exception("connection lost")
        await engine._handle_error_with_reconnect("room1", error)

        error_callback.assert_called_once_with(error)

    def test_set_reconnect_manager(self, engine):
        """测试设置重连管理器"""
        mgr = ReconnectManager(max_retries=5, base_delay=2.0)
        engine.set_reconnect_manager(mgr)
        assert engine._reconnect_manager is mgr


class TestBrowserEngineReconnect:
    """BrowserEngine 断线重连测试"""

    @pytest.fixture
    def engine(self):
        """创建浏览器引擎实例"""
        return BrowserEngine()

    @pytest.mark.asyncio
    async def test_page_crash_triggers_recovery_with_reconnect(self, engine):
        """测试页面崩溃触发恢复+重连"""
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        mock_page = AsyncMock()
        mock_page.reload = AsyncMock()  # 恢复成功
        engine._pages = {"room1": mock_page}

        with patch.object(engine, '_inject_script', new_callable=AsyncMock):
            await engine._recover_page("room1")
            mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_failure_triggers_reconnect(self, engine):
        """测试恢复失败后触发重连"""
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        mock_page = AsyncMock()
        mock_page.reload = AsyncMock(side_effect=Exception("page crashed"))
        engine._pages = {"room1": mock_page}

        error_callback = AsyncMock()
        engine.on_error(error_callback)

        with patch.object(engine, 'restart', new_callable=AsyncMock) as mock_restart:
            await engine._recover_page("room1")
            # 恢复失败后应尝试 restart
            mock_restart.assert_called_once_with("room1")

    def test_set_reconnect_manager(self, engine):
        """测试设置重连管理器"""
        mgr = ReconnectManager(max_retries=5, base_delay=2.0)
        engine.set_reconnect_manager(mgr)
        assert engine._reconnect_manager is mgr


class TestListenerReconnectIntegration:
    """DanmakuListener 重连集成测试"""

    @pytest.fixture
    def listener(self):
        """创建监听器实例"""
        return DanmakuListener()

    @pytest.mark.asyncio
    async def test_engine_error_triggers_reconnect_via_listener(self, listener):
        """测试引擎错误通过 listener 触发重连"""
        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        engine = listener._engines["123456"]
        reconnect_mgr = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(reconnect_mgr)

        # 模拟引擎错误回调
        error_callback = listener._create_engine_error_callback("123456")

        with patch.object(engine, '_handle_error_with_reconnect', new_callable=AsyncMock) as mock_handle:
            await error_callback(Exception("connection lost"))
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_event_published_to_bus(self, listener):
        """测试重连事件发布到事件总线"""
        listener._bus.publish = AsyncMock()

        # 模拟引擎发送重连成功消息
        raw_msg = {
            "type": "reconnect_success",
            "room_id": "123456",
        }

        callback = listener._create_engine_message_callback("123456")
        await callback(raw_msg)

        listener._bus.publish.assert_called_once_with("raw_message", raw_msg)

    @pytest.mark.asyncio
    async def test_reconnect_callback_invoked_on_reconnect_event(self, listener):
        """测试重连事件触发用户注册的回调"""
        reconnect_callback = AsyncMock()
        listener.on_reconnect(reconnect_callback)

        with patch.object(ProxyEngine, 'start', new_callable=AsyncMock):
            await listener.start(["douyin:123456"])

        # 发布重连事件
        await listener._bus.publish("reconnect", "123456")
        reconnect_callback.assert_called_once_with("123456")
