"""Task-04: 系统状态 API 测试

验证 GET /api/status 和 GET /api/proxy/status 路由。
"""

import pytest
from unittest.mock import patch, MagicMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


def _create_app_with_bridge(bridge=None):
    """创建带桥接器的测试 app"""
    from danmaku_listener.web.app import create_app
    app = create_app()
    if bridge is not None:
        app["bridge"] = bridge
    return app


class TestGetApiStatus:
    """验证 GET /api/status"""

    @pytest.mark.asyncio
    async def test_status_returns_200(self):
        """GET /api/status 返回 200"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_status_contains_required_fields(self):
        """返回体包含 backend_connected、rooms_count、proxy、keyword_filter"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert "backend_connected" in data
            assert "rooms_count" in data
            assert "proxy" in data
            assert "keyword_filter" in data

    @pytest.mark.asyncio
    async def test_status_default_values(self):
        """默认状态：connected=true, rooms_count=0"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert data["backend_connected"] is True
            assert data["rooms_count"] == 0

    @pytest.mark.asyncio
    async def test_status_proxy_object(self):
        """proxy 对象包含 enabled 字段"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert "enabled" in data["proxy"]

    @pytest.mark.asyncio
    async def test_status_keyword_filter_object(self):
        """keyword_filter 对象包含 enabled 和 count"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert "enabled" in data["keyword_filter"]
            assert "count" in data["keyword_filter"]

    @pytest.mark.asyncio
    async def test_status_rooms_count_after_adding_room(self):
        """添加房间后 rooms_count 增加"""
        from danmaku_listener.web.bridge import DanmakuBridge
        bridge = DanmakuBridge()
        # 模拟添加房间
        bridge._rooms["douyin:123456"] = {
            "platform": "douyin",
            "room_id": "123456",
            "status": "running",
            "engine_type": "proxy",
        }
        app = _create_app_with_bridge(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert data["rooms_count"] == 1


class TestGetProxyStatus:
    """验证 GET /api/proxy/status"""

    @pytest.mark.asyncio
    async def test_proxy_status_returns_200(self):
        """GET /api/proxy/status 返回 200"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/proxy/status")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_proxy_status_default_disabled(self):
        """默认状态：代理未启用"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/proxy/status")
            data = await resp.json()
            assert data["enabled"] is False

    @pytest.mark.asyncio
    async def test_proxy_status_contains_host_port(self):
        """返回体包含 host 和 port 字段"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/proxy/status")
            data = await resp.json()
            assert "host" in data
            assert "port" in data

    @pytest.mark.asyncio
    async def test_proxy_status_enabled_when_registry_set(self):
        """系统代理已开启时，返回 enabled: true"""
        from danmaku_listener.web.bridge import DanmakuBridge
        bridge = DanmakuBridge()
        # mock _get_proxy_status 返回启用状态
        bridge._get_proxy_status = lambda: {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8827,
        }
        app = _create_app_with_bridge(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/proxy/status")
            data = await resp.json()
            assert data["enabled"] is True
            assert data["host"] == "127.0.0.1"
            assert data["port"] == 8827
