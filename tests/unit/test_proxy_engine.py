"""代理引擎测试

验证代理模式的流量拦截和消息解析功能。
包含原有基础测试 + Task-08 ProxyEngine 完整实现测试。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_settings(**overrides):
    """构造 mock Settings 对象"""
    defaults = {
        "used_proxy": True,
        "cert_dir": "~/.mitmproxy",
        "process_filter": "chrome,msedge",
        "force_polling": False,
        "auto_pause": False,
        "ssl_decrypt_hostnames": "",
        "process_filter_list": ["chrome", "msedge"],
        "ssl_decrypt_extra_hostnames": [],
        "proxy_port": 8827,
        "listen_any": False,
        "proxy_host": "127.0.0.1",
        "proxy_address": "127.0.0.1:8827",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ===== 原有基础测试 =====

class TestProxyEngine:
    """代理引擎基础测试"""

    @pytest.fixture
    def engine(self):
        """创建代理引擎实例"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        return ProxyEngine(settings=_make_mock_settings())

    def test_platform_property(self, engine):
        """测试平台标识"""
        assert engine.platform == "douyin"

    def test_initial_status(self, engine):
        """测试初始状态为 STOPPED"""
        from danmaku_listener.engines.base import EngineStatus
        assert engine.status == EngineStatus.STOPPED

    @pytest.mark.asyncio
    async def test_start_sets_status_to_running(self, engine):
        """测试启动后状态变为 RUNNING"""
        from danmaku_listener.engines.base import EngineStatus
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            await engine.start("test_room_123")
            assert engine.status == EngineStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop_sets_status_to_stopped(self, engine):
        """测试停止后状态变为 STOPPED"""
        from danmaku_listener.engines.base import EngineStatus
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock):
                await engine.start("test_room_123")
                await engine.stop("test_room_123")
                assert engine.status == EngineStatus.STOPPED

    @pytest.mark.asyncio
    async def test_restart_calls_stop_and_start(self, engine):
        """测试重启调用 stop 和 start"""
        with patch.object(engine, 'stop', new_callable=AsyncMock) as mock_stop, \
             patch.object(engine, 'start', new_callable=AsyncMock) as mock_start:
            await engine.restart("test_room_123")
            mock_stop.assert_called_once_with("test_room_123")
            mock_start.assert_called_once_with("test_room_123")

    @pytest.mark.asyncio
    async def test_on_message_registers_callback(self, engine):
        """测试消息回调注册"""
        callback = AsyncMock()
        engine.on_message(callback)
        assert callback in engine._message_callbacks

    @pytest.mark.asyncio
    async def test_on_error_registers_callback(self, engine):
        """测试错误回调注册"""
        callback = AsyncMock()
        engine.on_error(callback)
        assert callback in engine._error_callbacks

    @pytest.mark.asyncio
    async def test_emit_message_calls_callbacks(self, engine):
        """测试消息触发回调"""
        callback = AsyncMock()
        engine.on_message(callback)

        await engine._emit_message({"type": "chat", "content": "hello"})

        callback.assert_called_once_with({"type": "chat", "content": "hello"})

    @pytest.mark.asyncio
    async def test_emit_error_calls_callbacks(self, engine):
        """测试错误触发回调"""
        callback = AsyncMock()
        engine.on_error(callback)

        error = Exception("test error")
        await engine._emit_error(error)

        callback.assert_called_once_with(error)

    @pytest.mark.asyncio
    async def test_emit_message_handles_callback_exception(self, engine):
        """测试回调异常不影响其他回调"""
        good_callback = AsyncMock()
        bad_callback = AsyncMock(side_effect=Exception("callback error"))

        engine.on_message(bad_callback)
        engine.on_message(good_callback)

        await engine._emit_message({"type": "test"})

        good_callback.assert_called_once()

    def test_set_status(self, engine):
        """测试状态设置"""
        from danmaku_listener.engines.base import EngineStatus
        engine._set_status(EngineStatus.RUNNING)
        assert engine.status == EngineStatus.RUNNING


# ===== Task-08: ProxyEngine 完整实现测试 =====

class TestProxyEngineInit:
    """ProxyEngine 初始化测试"""

    def test_initial_status_stopped(self):
        """ProxyEngine() 初始状态为 STOPPED"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.base import EngineStatus
        engine = ProxyEngine(settings=_make_mock_settings())
        assert engine.status == EngineStatus.STOPPED

    def test_has_system_proxy_manager(self):
        """ProxyEngine 包含 SystemProxyManager 实例"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        engine = ProxyEngine(settings=_make_mock_settings())
        assert isinstance(engine._system_proxy, SystemProxyManager)

    def test_system_proxy_enabled_by_default(self):
        """默认 used_proxy=True → SystemProxyManager.enabled=True"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=True))
        assert engine._system_proxy.enabled is True

    def test_system_proxy_disabled(self):
        """used_proxy=False → SystemProxyManager.enabled=False"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=False))
        assert engine._system_proxy.enabled is False

    def test_has_addon(self):
        """ProxyEngine 包含 DanmakuAddon 实例"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        engine = ProxyEngine(settings=_make_mock_settings())
        assert isinstance(engine._addon, DanmakuAddon)

    def test_not_started_initially(self):
        """ProxyEngine._started 初始为 False"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        engine = ProxyEngine(settings=_make_mock_settings())
        assert engine._started is False


class TestProxyEngineStart:
    """ProxyEngine.start() 测试 → AC-001"""

    @pytest.mark.asyncio
    async def test_start_sets_status_running(self):
        """start() → status=RUNNING → AC-001"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.base import EngineStatus

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            await engine.start("123456")
            assert engine.status == EngineStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_calls_start_proxy(self):
        """start() 调用 _start_proxy(room_id)"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock) as mock_start:
            await engine.start("123456")
            mock_start.assert_called_once_with("123456")

    @pytest.mark.asyncio
    async def test_start_idempotent_same_room(self):
        """重复 start 同一 room_id 不报错（幂等）"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.base import EngineStatus

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock) as mock_start:
            await engine.start("123456")
            # 模拟 _start_proxy 设置 _started 标志
            engine._started = True
            await engine.start("123456")
            # _start_proxy 只调用一次（第二次因 _started=True 跳过）
            assert mock_start.call_count == 1
            assert engine.status == EngineStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_multiple_rooms_shared_proxy(self):
        """多个 room_id 共享同一 mitmproxy 实例（单例模式）"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock) as mock_start:
            await engine.start("111")
            # 模拟 _start_proxy 设置 _started 标志
            engine._started = True
            await engine.start("222")
            # _start_proxy 应只被调用一次（单例）
            assert mock_start.call_count == 1

    @pytest.mark.asyncio
    async def test_start_registers_system_proxy(self):
        """_start_proxy 内部注册系统代理"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=True))
        mock_master = MagicMock()
        mock_master.run = AsyncMock()

        with patch('danmaku_listener.engines.proxy_engine.Master', return_value=mock_master):
            with patch.object(engine._system_proxy, 'register', return_value=True) as mock_reg:
                with patch('asyncio.create_task', return_value=MagicMock()):
                    await engine._start_proxy("123456")
                    mock_reg.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_skips_system_proxy_when_disabled(self):
        """used_proxy=False 时 SystemProxyManager.enabled=False，不修改注册表"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=False))
        # 验证 SystemProxyManager 的 enabled=False
        assert engine._system_proxy.enabled is False
        # register() 被调用但不修改注册表（enabled=False 时直接返回 True）
        result = engine._system_proxy.register("127.0.0.1", 8827)
        assert result is True


class TestProxyEngineStop:
    """ProxyEngine.stop() 测试 → AC-008, AC-013"""

    @pytest.mark.asyncio
    async def test_stop_sets_status_stopped(self):
        """stop() → status=STOPPED → AC-008"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine
        from danmaku_listener.engines.base import EngineStatus

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock):
                await engine.start("123456")
                await engine.stop("123456")
                assert engine.status == EngineStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_calls_stop_proxy(self):
        """stop() 调用 _stop_proxy(room_id)"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock) as mock_stop:
                await engine.start("123456")
                await engine.stop("123456")
                mock_stop.assert_called_once_with("123456")

    @pytest.mark.asyncio
    async def test_stop_closes_system_proxy(self):
        """stop() 时关闭系统代理 → AC-013"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=True))
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock):
                with patch.object(engine._system_proxy, 'close', return_value=True) as mock_close:
                    await engine.start("123456")
                    await engine.stop("123456")
                    mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_always_closes_system_proxy_even_on_error(self):
        """stop() 即使 _stop_proxy 异常也关闭系统代理 → AC-013"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings(used_proxy=True))
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock, side_effect=Exception("proxy error")):
                with patch.object(engine._system_proxy, 'close', return_value=True) as mock_close:
                    await engine.start("123456")
                    try:
                        await engine.stop("123456")
                    except Exception:
                        pass
                    # 系统代理恢复必须执行
                    mock_close.assert_called_once()


class TestProxyEngineStartProxy:
    """_start_proxy 内部实现测试"""

    @pytest.mark.asyncio
    async def test_start_proxy_creates_master(self):
        """_start_proxy 创建 mitmproxy Master"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        mock_master.run = AsyncMock()

        with patch('danmaku_listener.engines.proxy_engine.Master', return_value=mock_master):
            with patch.object(engine._system_proxy, 'register', return_value=True):
                with patch('asyncio.create_task', return_value=MagicMock()):
                    await engine._start_proxy("123456")
                    assert engine._master is mock_master

    @pytest.mark.asyncio
    async def test_start_proxy_registers_addon(self):
        """_start_proxy 将 DanmakuAddon 注册到 Master"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        mock_master.run = AsyncMock()
        mock_addons = MagicMock()
        mock_master.addons = mock_addons

        with patch('danmaku_listener.engines.proxy_engine.Master', return_value=mock_master):
            with patch.object(engine._system_proxy, 'register', return_value=True):
                with patch('asyncio.create_task', return_value=MagicMock()):
                    await engine._start_proxy("123456")
                    mock_addons.add.assert_called_once_with(engine._addon)

    @pytest.mark.asyncio
    async def test_start_proxy_sets_started_flag(self):
        """_start_proxy 设置 _started=True"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        mock_master.run = AsyncMock()

        with patch('danmaku_listener.engines.proxy_engine.Master', return_value=mock_master):
            with patch.object(engine._system_proxy, 'register', return_value=True):
                with patch('asyncio.create_task', return_value=MagicMock()):
                    await engine._start_proxy("123456")
                    assert engine._started is True

    @pytest.mark.asyncio
    async def test_start_proxy_idempotent(self):
        """_start_proxy 已启动时直接返回（单例）"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        engine._started = True

        with patch('danmaku_listener.engines.proxy_engine.Master') as mock_master_cls:
            await engine._start_proxy("123456")
            mock_master_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_proxy_port_conflict_raises_error(self):
        """端口冲突时 _start_proxy 抛出 ProxyStartError"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine, ProxyStartError

        engine = ProxyEngine(settings=_make_mock_settings())

        with patch('danmaku_listener.engines.proxy_engine.Master', side_effect=OSError("Address already in use")):
            with patch.object(engine._system_proxy, 'register', return_value=True):
                with pytest.raises(ProxyStartError):
                    await engine._start_proxy("123456")

    @pytest.mark.asyncio
    async def test_start_proxy_cert_failure_only_warning(self):
        """证书信任失败时 start 仍成功（仅警告日志）→ AC-009"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        mock_master.run = AsyncMock()

        with patch('danmaku_listener.engines.proxy_engine.Master', return_value=mock_master):
            with patch.object(engine._system_proxy, 'register', return_value=True):
                with patch.object(engine, '_trust_certificate', return_value=False):
                    with patch('asyncio.create_task', return_value=MagicMock()):
                        await engine._start_proxy("123456")
                        # 证书失败不应阻止启动
                        assert engine._started is True


class TestProxyEngineStopProxy:
    """_stop_proxy 内部实现测试"""

    @pytest.mark.asyncio
    async def test_stop_proxy_shuts_down_master(self):
        """_stop_proxy 调用 master.shutdown()"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        engine._master = mock_master
        engine._started = True

        await engine._stop_proxy("123456")
        mock_master.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_proxy_clears_started_flag(self):
        """_stop_proxy 设置 _started=False"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        engine._master = mock_master
        engine._started = True

        await engine._stop_proxy("123456")
        assert engine._started is False

    @pytest.mark.asyncio
    async def test_stop_proxy_no_master_no_error(self):
        """_stop_proxy 在 master 为 None 时不报错"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        engine._master = None
        engine._started = False

        # 不应抛异常
        await engine._stop_proxy("123456")

    @pytest.mark.asyncio
    async def test_stop_proxy_handles_shutdown_error(self):
        """_stop_proxy 在 master.shutdown() 异常时不崩溃"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        mock_master = MagicMock()
        mock_master.shutdown.side_effect = Exception("shutdown error")
        engine._master = mock_master
        engine._started = True

        # 不应抛异常，应被内部 try/except 捕获
        await engine._stop_proxy("123456")
        assert engine._started is False
        assert engine._master is None


class TestProxyEngineRoomTracking:
    """房间追踪测试"""

    @pytest.mark.asyncio
    async def test_start_tracks_room_id(self):
        """start() 记录 room_id"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            await engine.start("111")
            assert "111" in engine._room_ids

    @pytest.mark.asyncio
    async def test_multiple_rooms_tracked(self):
        """多个 room_id 都被记录"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            await engine.start("111")
            await engine.start("222")
            assert "111" in engine._room_ids
            assert "222" in engine._room_ids

    @pytest.mark.asyncio
    async def test_stop_removes_room_id(self):
        """stop() 移除 room_id"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock):
                await engine.start("111")
                await engine.stop("111")
                assert "111" not in engine._room_ids

    @pytest.mark.asyncio
    async def test_stop_last_room_stops_proxy(self):
        """最后一个 room stop 时才真正停止代理"""
        from danmaku_listener.engines.proxy_engine import ProxyEngine

        engine = ProxyEngine(settings=_make_mock_settings())
        with patch.object(engine, '_start_proxy', new_callable=AsyncMock):
            with patch.object(engine, '_stop_proxy', new_callable=AsyncMock) as mock_stop:
                await engine.start("111")
                await engine.start("222")
                # 停止第一个房间，代理不应停止
                await engine.stop("111")
                mock_stop.assert_not_called()
                # 停止最后一个房间，代理应停止
                await engine.stop("222")
                mock_stop.assert_called_once()
