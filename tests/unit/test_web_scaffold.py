"""Task-01: 项目脚手架 测试

验证 web/ 目录结构、aiohttp 服务启动、静态文件路由、blocked_keywords.json 存在。
"""

import json
import pytest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
WEB_DIR = PROJECT_ROOT / "web"


class TestWebDirectoryStructure:
    """验证 web/ 目录结构完整"""

    def test_web_dir_exists(self):
        """web/ 目录存在"""
        assert WEB_DIR.is_dir(), f"web/ directory does not exist at {WEB_DIR}"

    def test_web_init_exists(self):
        """web/__init__.py 存在"""
        assert (WEB_DIR / "__init__.py").is_file()

    def test_web_app_exists(self):
        """web/app.py 存在"""
        assert (WEB_DIR / "app.py").is_file()

    def test_web_bridge_exists(self):
        """web/bridge.py 存在"""
        assert (WEB_DIR / "bridge.py").is_file()

    def test_static_dir_exists(self):
        """web/static/ 目录存在"""
        assert (WEB_DIR / "static").is_dir()

    def test_index_html_exists(self):
        """web/static/index.html 存在"""
        assert (WEB_DIR / "static" / "index.html").is_file()

    def test_app_js_exists(self):
        """web/static/app.js 存在"""
        assert (WEB_DIR / "static" / "app.js").is_file()

    def test_style_css_exists(self):
        """web/static/style.css 存在"""
        assert (WEB_DIR / "static" / "style.css").is_file()

    def test_blocked_keywords_json_exists(self):
        """web/blocked_keywords.json 存在且内容为空数组"""
        kw_file = WEB_DIR / "blocked_keywords.json"
        assert kw_file.is_file(), f"blocked_keywords.json does not exist at {kw_file}"
        with open(kw_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == [], f"Expected empty array, got {data}"


class TestWebAppCreation:
    """验证 aiohttp Application 可创建"""

    def test_create_app(self):
        """web.create_app() 返回 aiohttp Application"""
        from web.app import create_app
        app = create_app()
        assert isinstance(app, web.Application)

    def test_app_has_routes(self):
        """Application 至少有路由注册"""
        from web.app import create_app
        app = create_app()
        assert len(app.router.routes()) > 0


class TestStaticFileServing:
    """验证静态文件可访问"""

    @pytest.mark.asyncio
    async def test_index_page_returns_200(self):
        """GET / 返回 200，内容为 HTML"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "<html" in text.lower() or "<!doctype" in text.lower()

    @pytest.mark.asyncio
    async def test_style_css_returns_200(self):
        """GET /static/style.css 返回 200"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/static/style.css")
            assert resp.status == 200

    @pytest.mark.asyncio
    async def test_app_js_returns_200(self):
        """GET /static/app.js 返回 200"""
        from web.app import create_app
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/static/app.js")
            assert resp.status == 200


class TestWebAppModuleEntry:
    """验证 web.app 有启动入口"""

    def test_main_function_exists(self):
        """web.app 模块有 main 函数"""
        from web.app import main
        assert callable(main)
