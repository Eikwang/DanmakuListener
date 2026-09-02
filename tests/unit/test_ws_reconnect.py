"""Task-13: WebSocket 断线重连 测试

验证 DanmakuAddon.websocket_end() 和 ProxyEngine 断线重连集成：
- websocket_end 匹配弹幕域名 → callback({type:"ws_disconnect", room_id}) → AC-012
- 不匹配弹幕域名 → 不触发
- ProxyEngine 收到 ws_disconnect → _handle_error_with_reconnect
- 重连成功 → emit reconnect_success
- 重连失败 → _emit_error
- room_id 从 flow URL 提取，断线和重连使用同一 room_id
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_settings(**overrides):
    defaults = {
        "used_proxy": True,
        "cert_dir": "~/.mitmproxy",
        "process_filter": "chrome,msedge",
        "force_polling": False,
        "auto_pause": False,
        "ssl_decrypt_hostnames": "",
        "process_filter_list": ["chrome", "msedge"],
        "ssl_decrypt_extra_hostnames": [],
        "dedup_window_size": 300,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_ws_end_flow(
    host="webcast3-ws-web-1.douyin.com",
    url="wss://webcast3-ws-web-1.douyin.com/webcast/im/push/v2/?room_id=123456",
    flow_id="test-flow-id-001",
):
    """构造 mock WebSocket 关闭的 HTTPFlow"""
    flow = MagicMock()
    flow.id = flow_id
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.pretty_url = url
    return flow


class TestWebsocketEndDanmakuDisconnect:
    """websocket_end 匹配弹幕域名 → 触发断线事件 → AC-012"""

    @pytest.mark.asyncio
    async def test_danmaku_ws_disconnect_triggers_callback(self):
        """弹幕域名 WS 断开 → callback 收到 ws_disconnect 消息"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        # 先注册该 flow 为活跃弹幕流（模拟 websocket_start 已触发）
        addon._active_ws_flows["test-flow-id-001"] = "123456"

        flow = _make_ws_end_flow()
        addon.websocket_end(flow)

        # 等待 asyncio.create_task 执行
        import asyncio
        await asyncio.sleep(0)

        # 应调用 _message_callback，传入 ws_disconnect 消息
        cb.assert_called_once()
        call_args = cb.call_args[0][0]
        assert call_args["type"] == "ws_disconnect"
        assert call_args["room_id"] == "123456"

    @pytest.mark.asyncio
    async def test_danmaku_ws_disconnect_removes_active_flow(self):
        """弹幕 WS 断开 → 从 _active_ws_flows 中移除该 flow"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        addon._active_ws_flows["test-flow-id-001"] = "123456"

        flow = _make_ws_end_flow()
        addon.websocket_end(flow)

        # pop 是同步操作，不需要 await
        assert "test-flow-id-001" not in addon._active_ws_flows

    @pytest.mark.asyncio
    async def test_non_danmaku_ws_disconnect_no_callback(self):
        """非弹幕域名 WS 断开 → 不触发 callback"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        # 非弹幕域名 — 不注册到 _active_ws_flows
        flow = _make_ws_end_flow(
            host="api.example.com",
            url="wss://api.example.com/ws/",
        )
        addon.websocket_end(flow)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_flow_no_callback(self):
        """flow 不在 _active_ws_flows 中 → 不触发 callback"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        # 弹幕域名但 flow_id 未注册（不在 _active_ws_flows 中）
        flow = _make_ws_end_flow(flow_id="unknown-flow-id")
        addon.websocket_end(flow)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_with_empty_room_id(self):
        """弹幕域名 WS 断开但 room_id 为空 → 仍触发 callback（room_id=""）"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        # 注册 flow 但 room_id 为空
        addon._active_ws_flows["test-flow-id-002"] = ""

        flow = _make_ws_end_flow(
            url="wss://webcast3-ws-web-1.douyin.com/webcast/im/push/v2/",
            flow_id="test-flow-id-002",
        )
        addon.websocket_end(flow)

        import asyncio
        await asyncio.sleep(0)

        cb.assert_called_once()
        call_args = cb.call_args[0][0]
        assert call_args["type"] == "ws_disconnect"
        assert call_args["room_id"] == ""


class TestProxyEngineReconnectOnDisconnect:
    """ProxyEngine 收到 ws_disconnect → 触发重连逻辑"""

    @pytest.mark.asyncio
    async def test_proxy_engine_handles_ws_disconnect(self):
        """ProxyEngine 收到 ws_disconnect → 调用 _handle_error_with_reconnect"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        settings = _make_mock_settings()
        engine = ProxyEngine(settings=settings)

        # Mock _handle_error_with_reconnect
        engine._handle_error_with_reconnect = AsyncMock(return_value=False)

        # 模拟 addon 发送 ws_disconnect 消息
        await engine._on_addon_message({
            "type": "ws_disconnect",
            "room_id": "123456",
        })

        engine._handle_error_with_reconnect.assert_called_once()
        call_args = engine._handle_error_with_reconnect.call_args
        assert call_args[0][0] == "123456"  # room_id
        assert isinstance(call_args[0][1], ConnectionError)

    @pytest.mark.asyncio
    async def test_proxy_engine_reconnect_success(self):
        """重连成功 → _handle_error_with_reconnect 返回 True"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        settings = _make_mock_settings()
        engine = ProxyEngine(settings=settings)

        # Mock _handle_error_with_reconnect 返回 True（重连成功）
        engine._handle_error_with_reconnect = AsyncMock(return_value=True)

        # 注册消息回调
        msg_cb = AsyncMock()
        engine.on_message(msg_cb)

        await engine._on_addon_message({
            "type": "ws_disconnect",
            "room_id": "123456",
        })

        # _handle_error_with_reconnect 被调用且返回 True
        engine._handle_error_with_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_engine_reconnect_failure(self):
        """重连失败 → _handle_error_with_reconnect 返回 False"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        settings = _make_mock_settings()
        engine = ProxyEngine(settings=settings)

        # Mock _handle_error_with_reconnect 返回 False（重连失败）
        engine._handle_error_with_reconnect = AsyncMock(return_value=False)

        await engine._on_addon_message({
            "type": "ws_disconnect",
            "room_id": "123456",
        })

        engine._handle_error_with_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_engine_no_reconnect_manager_emits_error(self):
        """无 ReconnectManager → _handle_error_with_reconnect 直接 _emit_error"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        settings = _make_mock_settings()
        engine = ProxyEngine(settings=settings)

        # 确保 _reconnect_manager 为 None
        engine._reconnect_manager = None

        # Mock _emit_error
        engine._emit_error = AsyncMock()

        # 直接调用 _handle_error_with_reconnect（真实方法，非 mock）
        result = await engine._handle_error_with_reconnect("123456", ConnectionError("test"))
        assert result is False
        engine._emit_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_engine_non_disconnect_message_passthrough(self):
        """非 ws_disconnect 消息 → 正常转发到 _emit_message"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        settings = _make_mock_settings()
        engine = ProxyEngine(settings=settings)

        # Mock _emit_message
        engine._emit_message = AsyncMock()

        await engine._on_addon_message({
            "type": "danmaku",
            "room_id": "123456",
            "method": "WebcastChatMessage",
        })

        engine._emit_message.assert_called_once()


class TestReconnectRoomIdMatching:
    """断线和重连使用同一 room_id 匹配"""

    @pytest.mark.asyncio
    async def test_reconnect_success_on_same_room_id(self):
        """重连成功：restart 成功 → emit reconnect_success"""
        from danmaku_listener.engines.base import BaseEngine, EngineStatus
        from danmaku_listener.managers.reconnect_manager import ReconnectManager

        class TestEngine(BaseEngine):
            def __init__(self):
                super().__init__()
                self._restart_called = False

            async def start(self, room_id):
                self._set_status(EngineStatus.RUNNING)

            async def stop(self, room_id):
                self._set_status(EngineStatus.STOPPED)

            async def restart(self, room_id):
                self._restart_called = True
                self._set_status(EngineStatus.RUNNING)

        engine = TestEngine()

        # 设置 ReconnectManager（max_retries=1, base_delay=0.01 加速测试）
        rm = ReconnectManager(max_retries=1, base_delay=0.01)
        engine.set_reconnect_manager(rm)

        # 注册消息回调
        msg_cb = AsyncMock()
        engine.on_message(msg_cb)

        # 触发断线重连
        result = await engine._handle_error_with_reconnect(
            "123456", ConnectionError("disconnected")
        )

        # 重连应成功（restart 不会抛异常）
        assert result is True
        assert engine._restart_called

        # 应 emit reconnect_success
        msg_cb.assert_called_once()
        call_args = msg_cb.call_args[0][0]
        assert call_args["type"] == "reconnect_success"
        assert call_args["room_id"] == "123456"

    @pytest.mark.asyncio
    async def test_reconnect_failure_after_max_retries(self):
        """重连失败：超过 max_retries → _emit_error"""
        from danmaku_listener.engines.base import BaseEngine, EngineStatus
        from danmaku_listener.managers.reconnect_manager import ReconnectManager

        class FailingEngine(BaseEngine):
            async def start(self, room_id):
                pass

            async def stop(self, room_id):
                pass

            async def restart(self, room_id):
                raise ConnectionError("still disconnected")

        engine = FailingEngine()
        rm = ReconnectManager(max_retries=2, base_delay=0.01)
        engine.set_reconnect_manager(rm)

        # 注册错误回调
        err_cb = AsyncMock()
        engine.on_error(err_cb)

        result = await engine._handle_error_with_reconnect(
            "123456", ConnectionError("disconnected")
        )

        assert result is False
        err_cb.assert_called_once()
        assert isinstance(err_cb.call_args[0][0], ConnectionError)
