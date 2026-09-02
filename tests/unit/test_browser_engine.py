"""浏览器引擎测试

验证 Playwright 浏览器模式的核心功能。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from danmaku_listener.engines.browser_engine import BrowserEngine
from danmaku_listener.engines.base import EngineStatus


class TestBrowserEngine:
    """浏览器引擎测试"""

    @pytest.fixture
    def engine(self):
        """创建浏览器引擎实例"""
        return BrowserEngine()

    def test_platform_property(self, engine):
        """测试平台标识"""
        assert engine.platform == "browser"

    def test_initial_status(self, engine):
        """测试初始状态为 STOPPED"""
        assert engine.status == EngineStatus.STOPPED

    @pytest.mark.asyncio
    async def test_start_sets_status_to_running(self, engine):
        """测试启动后状态变为 RUNNING"""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock) as mock_launch, \
             patch.object(engine, '_create_context', new_callable=AsyncMock) as mock_context, \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock) as mock_nav:
            await engine.start("test_room_123")
            assert engine.status == EngineStatus.RUNNING
            mock_launch.assert_called_once()
            mock_context.assert_called_once_with("test_room_123")
            mock_nav.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_sets_status_to_stopped(self, engine):
        """测试停止后状态变为 STOPPED"""
        engine._status = EngineStatus.RUNNING
        with patch.object(engine, '_close_context', new_callable=AsyncMock) as mock_close, \
             patch.object(engine, '_save_context_cookies', new_callable=AsyncMock) as mock_save:
            await engine.stop("test_room_123")
            assert engine.status == EngineStatus.STOPPED
            mock_save.assert_called_once_with("test_room_123")
            mock_close.assert_called_once_with("test_room_123")

    @pytest.mark.asyncio
    async def test_restart_calls_stop_and_start(self, engine):
        """测试重启调用 stop 和 start"""
        engine._status = EngineStatus.RUNNING
        with patch.object(engine, 'stop', new_callable=AsyncMock) as mock_stop, \
             patch.object(engine, 'start', new_callable=AsyncMock) as mock_start:
            await engine.restart("test_room_123")
            mock_stop.assert_called_once_with("test_room_123")
            mock_start.assert_called_once_with("test_room_123")

    @pytest.mark.asyncio
    async def test_start_reuses_existing_browser(self, engine):
        """测试多个房间共享浏览器实例"""
        mock_browser = MagicMock()
        engine._browser = mock_browser

        with patch.object(engine, '_create_context', new_callable=AsyncMock) as mock_context, \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock):
            await engine.start("room1")
            # 不应重新启动浏览器
            assert engine._browser is mock_browser

    @pytest.mark.asyncio
    async def test_start_creates_browser_if_none(self, engine):
        """测试首次启动时创建浏览器实例"""
        assert engine._browser is None

        with patch.object(engine, '_launch_browser', new_callable=AsyncMock) as mock_launch, \
             patch.object(engine, '_create_context', new_callable=AsyncMock), \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock):
            await engine.start("room1")
            mock_launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_pool_isolation(self, engine):
        """测试每个房间使用独立的 BrowserContext"""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock), \
             patch.object(engine, '_create_context', new_callable=AsyncMock) as mock_context, \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock):
            await engine.start("room1")
            await engine.start("room2")

            # 两次调用 _create_context，参数不同
            assert mock_context.call_count == 2
            calls = mock_context.call_args_list
            assert calls[0][0][0] == "room1"
            assert calls[1][0][0] == "room2"

    @pytest.mark.asyncio
    async def test_stop_saves_cookies_before_closing(self, engine):
        """测试停止时先保存 Cookie 再关闭 Context"""
        engine._status = EngineStatus.RUNNING
        call_order = []

        async def mock_save(room_id):
            call_order.append("save")

        async def mock_close(room_id):
            call_order.append("close")

        with patch.object(engine, '_save_context_cookies', side_effect=mock_save), \
             patch.object(engine, '_close_context', side_effect=mock_close):
            await engine.stop("room1")

        assert call_order == ["save", "close"]

    @pytest.mark.asyncio
    async def test_stop_all_closes_browser(self, engine):
        """测试 stop_all 关闭所有 Context 和浏览器"""
        engine._status = EngineStatus.RUNNING
        mock_browser = AsyncMock()
        engine._browser = mock_browser
        mock_ctx1 = AsyncMock()
        mock_ctx2 = AsyncMock()
        engine._contexts = {"room1": mock_ctx1, "room2": mock_ctx2}

        with patch.object(engine, '_save_context_cookies', new_callable=AsyncMock):
            await engine.stop_all()

        # 验证所有 Context 被关闭
        mock_ctx1.close.assert_called_once()
        mock_ctx2.close.assert_called_once()
        # 验证浏览器被关闭
        mock_browser.close.assert_called_once()
        assert engine._browser is None

    @pytest.mark.asyncio
    async def test_load_cookies_on_context_creation(self, engine):
        """测试创建 Context 时加载 Cookie"""
        mock_cookie_mgr = MagicMock()
        mock_cookie_mgr.load_cookies.return_value = {"cookies": [{"name": "session", "value": "abc"}]}
        engine._cookie_manager = mock_cookie_mgr

        mock_browser = AsyncMock()
        engine._browser = mock_browser
        mock_context = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        await engine._create_context("room_with_cookies")

        # 验证 new_context 被调用时传入了 storage_state
        mock_browser.new_context.assert_called_once()
        call_kwargs = mock_browser.new_context.call_args[1]
        assert "storage_state" in call_kwargs

    @pytest.mark.asyncio
    async def test_create_context_without_cookies(self, engine):
        """测试无 Cookie 时仍能创建 Context"""
        mock_cookie_mgr = MagicMock()
        mock_cookie_mgr.load_cookies.return_value = None
        engine._cookie_manager = mock_cookie_mgr

        mock_browser = AsyncMock()
        engine._browser = mock_browser
        mock_context = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        await engine._create_context("room_no_cookies")

        mock_browser.new_context.assert_called_once()
        call_kwargs = mock_browser.new_context.call_args[1]
        assert "storage_state" not in call_kwargs

    @pytest.mark.asyncio
    async def test_inject_script(self, engine):
        """测试脚本注入"""
        mock_page = AsyncMock()
        engine._pages = {"room1": mock_page}

        script_content = "console.log('test');"
        await engine._inject_script("room1", script_content)

        mock_page.add_script_tag.assert_called_once_with(content=script_content)

    @pytest.mark.asyncio
    async def test_expose_callback(self, engine):
        """测试暴露回调函数到页面"""
        mock_page = AsyncMock()
        engine._pages = {"room1": mock_page}

        callback = AsyncMock()
        await engine._expose_callback("room1", "onDanmaku", callback)

        mock_page.expose_function.assert_called_once_with("onDanmaku", callback)

    @pytest.mark.asyncio
    async def test_navigate_to_url(self, engine):
        """测试导航到直播间 URL"""
        mock_page = AsyncMock()
        engine._pages = {"room1": mock_page}

        url = "https://live.douyin.com/123456"
        await engine._navigate("room1", url)

        mock_page.goto.assert_called_once_with(url, wait_until="domcontentloaded")

    @pytest.mark.asyncio
    async def test_get_page_for_room(self, engine):
        """测试获取指定房间的 Page"""
        mock_page = MagicMock()
        engine._pages = {"room1": mock_page}

        page = engine.get_page("room1")
        assert page is mock_page

    def test_get_page_for_nonexistent_room(self, engine):
        """测试获取不存在房间的 Page 返回 None"""
        page = engine.get_page("nonexistent")
        assert page is None

    @pytest.mark.asyncio
    async def test_start_with_headless_config(self):
        """测试 headless 配置传递"""
        engine = BrowserEngine(headless=False)
        assert engine._headless is False

    @pytest.mark.asyncio
    async def test_start_already_running_skips(self, engine):
        """测试已运行时重复 start 跳过浏览器启动"""
        engine._status = EngineStatus.RUNNING
        engine._browser = MagicMock()

        with patch.object(engine, '_launch_browser', new_callable=AsyncMock) as mock_launch, \
             patch.object(engine, '_create_context', new_callable=AsyncMock) as mock_context, \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock) as mock_nav:
            await engine.start("room1")
            # 浏览器已存在，不应重新启动
            mock_launch.assert_not_called()
            # 但仍应创建新的 context
            mock_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_heartbeat_monitor(self, engine):
        """测试启动时创建心跳监控"""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock), \
             patch.object(engine, '_create_context', new_callable=AsyncMock), \
             patch.object(engine, '_navigate_and_inject', new_callable=AsyncMock), \
             patch.object(engine, '_start_heartbeat', new_callable=AsyncMock) as mock_hb:
            await engine.start("room1")
            mock_hb.assert_called_once_with("room1")

    @pytest.mark.asyncio
    async def test_stop_stops_heartbeat_monitor(self, engine):
        """测试停止时关闭心跳监控"""
        engine._status = EngineStatus.RUNNING
        with patch.object(engine, '_save_context_cookies', new_callable=AsyncMock), \
             patch.object(engine, '_close_context', new_callable=AsyncMock), \
             patch.object(engine, '_stop_heartbeat', new_callable=AsyncMock) as mock_hb:
            await engine.stop("room1")
            mock_hb.assert_called_once_with("room1")

    @pytest.mark.asyncio
    async def test_heartbeat_health_check_uses_page(self, engine):
        """测试心跳健康检查使用 page.evaluate"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=1)
        engine._pages = {"room1": mock_page}

        is_healthy = await engine._check_page_health("room1")
        assert is_healthy is True
        mock_page.evaluate.assert_called_once_with("1")

    @pytest.mark.asyncio
    async def test_heartbeat_health_check_failure(self, engine):
        """测试心跳健康检查失败"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("page crashed"))
        engine._pages = {"room1": mock_page}

        is_healthy = await engine._check_page_health("room1")
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_reloads_page(self, engine):
        """测试心跳恢复时刷新页面"""
        mock_page = AsyncMock()
        engine._pages = {"room1": mock_page}

        await engine._recover_page("room1")
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_failure_emits_error(self, engine):
        """测试心跳恢复失败时触发错误回调"""
        mock_page = AsyncMock()
        mock_page.reload = AsyncMock(side_effect=Exception("reload failed"))
        engine._pages = {"room1": mock_page}

        error_callback = AsyncMock()
        engine.on_error(error_callback)

        await engine._recover_page("room1")
        error_callback.assert_called_once()
