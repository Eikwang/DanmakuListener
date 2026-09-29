"""Task-04: 系统状态 API 测试

验证 GET /api/status 路由（mitmproxy 代理 API 已随 2026-09-29 原生切换移除）。
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
        """返回体包含 backend_connected、rooms_count、keyword_filter"""
        app = _create_app_with_bridge()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert "backend_connected" in data
            assert "rooms_count" in data
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
