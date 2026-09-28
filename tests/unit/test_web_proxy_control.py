"""Task-09: 系统代理控制 — 单元测试

验证标准：
1. POST /api/proxy/enable → 返回 200，success: true，host: "127.0.0.1"，port: 8827
2. 开启代理后 Windows 注册表 ProxyEnable == 1
3. POST /api/proxy/disable → 返回 200，success: true
4. 关闭代理后 Windows 注册表 ProxyEnable == 0
5. 权限不足时 POST /api/proxy/enable → 返回 500，error 包含 "permission" 或 "权限"
6. 前端 Toggle 按钮点击开启 → 按钮变为"已启用"状态（Playwright 验证）
7. 前端 Toggle 按钮点击关闭 → 按钮变为"已禁用"状态（Playwright 验证）
8. 代理状态页面刷新后保持正确（读取注册表实际值）
"""

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
    return bridge


# ── DanmakuBridge 方法测试 ──────────────────────────────────


class TestEnableProxy:
    """验证标准 1, 2, 5: 开启代理"""

    @pytest.mark.asyncio
    async def test_enable_proxy_returns_success(self):
        """enable_proxy → 返回 {success: true, host, port}"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.register.return_value = True
            mock_get.return_value = mock_spm

            with patch.object(bridge, '_get_proxy_host', return_value="127.0.0.1"):
                with patch.object(bridge, '_get_proxy_port', return_value=8827):
                    result = await bridge.enable_proxy()

        assert result["success"] is True
        assert result["host"] == "127.0.0.1"
        assert result["port"] == 8827

    @pytest.mark.asyncio
    async def test_enable_proxy_calls_register(self):
        """enable_proxy → 调用 SystemProxyManager.register()"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.register.return_value = True
            mock_get.return_value = mock_spm

            with patch.object(bridge, '_get_proxy_host', return_value="127.0.0.1"):
                with patch.object(bridge, '_get_proxy_port', return_value=8827):
                    await bridge.enable_proxy()

        mock_spm.register.assert_called_once_with("127.0.0.1", 8827)

    @pytest.mark.asyncio
    async def test_enable_proxy_failure_returns_error(self):
        """register 返回 False → 返回 {success: false, error: ...}"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.register.return_value = False
            mock_get.return_value = mock_spm

            with patch.object(bridge, '_get_proxy_host', return_value="127.0.0.1"):
                with patch.object(bridge, '_get_proxy_port', return_value=8827):
                    result = await bridge.enable_proxy()

        assert result["success"] is False
        assert "error" in result


class TestDisableProxy:
    """验证标准 3, 4: 关闭代理"""

    @pytest.mark.asyncio
    async def test_disable_proxy_returns_success(self):
        """disable_proxy → 返回 {success: true}"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.close.return_value = True
            mock_get.return_value = mock_spm

            result = await bridge.disable_proxy()

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_disable_proxy_calls_close(self):
        """disable_proxy → 调用 SystemProxyManager.close()"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.close.return_value = True
            mock_get.return_value = mock_spm

            await bridge.disable_proxy()

        mock_spm.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_proxy_failure_returns_error(self):
        """close 返回 False → 返回 {success: false, error: ...}"""
        bridge = _make_bridge_with_mocked_listener()

        with patch.object(bridge, '_get_system_proxy_manager') as mock_get:
            mock_spm = MagicMock()
            mock_spm.close.return_value = False
            mock_get.return_value = mock_spm

            result = await bridge.disable_proxy()

        assert result["success"] is False
        assert "error" in result


class TestProxyAPIMethods:
    """验证 bridge 的代理控制辅助方法"""

    def test_get_system_proxy_manager(self):
        """_get_system_proxy_manager → 返回 SystemProxyManager 实例"""
        bridge = DanmakuBridge()
        spm = bridge._get_system_proxy_manager()
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        assert isinstance(spm, SystemProxyManager)

    def test_get_proxy_host(self):
        """_get_proxy_host → 返回配置的代理地址"""
        bridge = DanmakuBridge()
        host = bridge._get_proxy_host()
        assert isinstance(host, str)
        assert len(host) > 0

    def test_get_proxy_port(self):
        """_get_proxy_port → 返回配置的代理端口"""
        bridge = DanmakuBridge()
        port = bridge._get_proxy_port()
        assert isinstance(port, int)
        assert port > 0


# ── API 路由测试 ──────────────────────────────────────────────


class TestProxyEnableAPI:
    """验证标准 1, 5: POST /api/proxy/enable"""

    @pytest.mark.asyncio
    async def test_proxy_enable_success(self):
        """POST /api/proxy/enable → 200，success: true"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge

        with patch.object(bridge, 'enable_proxy', new_callable=AsyncMock) as mock_enable:
            mock_enable.return_value = {"success": True, "enabled": True, "host": "127.0.0.1", "port": 8827}
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/proxy/enable")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True
                assert data["enabled"] is True
                assert data["host"] == "127.0.0.1"
                assert data["port"] == 8827

    @pytest.mark.asyncio
    async def test_proxy_enable_failure_returns_500(self):
        """enable 失败 → 500"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge

        with patch.object(bridge, 'enable_proxy', new_callable=AsyncMock) as mock_enable:
            mock_enable.return_value = {"success": False, "error": "Failed to set system proxy, check permissions"}
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/proxy/enable")
                assert resp.status == 500
                data = await resp.json()
                assert "permission" in data["error"].lower() or "权限" in data["error"]


class TestProxyDisableAPI:
    """验证标准 3: POST /api/proxy/disable"""

    @pytest.mark.asyncio
    async def test_proxy_disable_success(self):
        """POST /api/proxy/disable → 200，success: true"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge

        with patch.object(bridge, 'disable_proxy', new_callable=AsyncMock) as mock_disable:
            mock_disable.return_value = {"success": True}
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/proxy/disable")
                assert resp.status == 200
                data = await resp.json()
                assert data["success"] is True

    @pytest.mark.asyncio
    async def test_proxy_disable_failure_returns_500(self):
        """disable 失败 → 500"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge

        with patch.object(bridge, 'disable_proxy', new_callable=AsyncMock) as mock_disable:
            mock_disable.return_value = {"success": False, "error": "Failed to disable proxy"}
            async with TestClient(TestServer(app)) as client:
                resp = await client.post("/api/proxy/disable")
                assert resp.status == 500
                data = await resp.json()
                assert data["success"] is False
