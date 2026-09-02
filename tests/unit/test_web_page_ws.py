"""Task-03: 前端页面骨架 测试

验证页面元素、WebSocket 路由、连接/断线/重连。
"""

import json
import pytest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


class TestPageElements:
    """验证 HTML 页面包含关键元素"""

    @pytest.mark.asyncio
    async def test_page_has_room_list_element(self):
        """页面包含 #room-list"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            text = await resp.text()
            assert 'id="room-list"' in text

    @pytest.mark.asyncio
    async def test_page_has_danmaku_container(self):
        """页面包含 #danmaku-container"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            text = await resp.text()
            assert 'id="danmaku-container"' in text

    @pytest.mark.asyncio
    async def test_page_has_proxy_toggle(self):
        """页面包含 #proxy-toggle"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            text = await resp.text()
            assert 'id="proxy-toggle"' in text

    @pytest.mark.asyncio
    async def test_page_has_keyword_list(self):
        """页面包含 #keyword-list"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            text = await resp.text()
            assert 'id="keyword-list"' in text

    @pytest.mark.asyncio
    async def test_page_loads_app_js(self):
        """页面引用 app.js"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            text = await resp.text()
            assert "app.js" in text


class TestWebSocketRoute:
    """验证 WebSocket 路由存在"""

    @pytest.mark.asyncio
    async def test_ws_route_exists(self):
        """GET /ws 可升级为 WebSocket"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            # 尝试 WebSocket 连接
            ws = await client.ws_connect("/ws")
            assert ws is not None
            await ws.close()

    @pytest.mark.asyncio
    async def test_ws_receives_status_on_connect(self):
        """WebSocket 连接后收到初始状态消息"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            ws = await client.ws_connect("/ws")
            msg = await ws.receive_json()
            # 应收到 status 消息
            assert msg.get("type") == "status"
            assert "data" in msg
            await ws.close()
