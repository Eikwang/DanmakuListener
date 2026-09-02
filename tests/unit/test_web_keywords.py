"""Task-10: 关键词屏蔽 — 单元测试

验证标准：
1. GET /api/keywords → {"keywords": [], "enabled": true}
2. POST /api/keywords {"keyword": "广告"} → {"success": true, "keywords": ["广告"]}
3. DELETE /api/keywords/广告 → {"success": true, "keywords": []}
4. PUT /api/keywords/toggle {"enabled": false} → {"success": true, "enabled": false}
5. 关键词持久化：添加后保存到文件
6. 关键词长度超过 50 字符 → 400
7. 重复添加同一关键词 → 不重复
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from web.bridge import DanmakuBridge
from web.app import create_app


# ── 辅助工具 ──────────────────────────────────────────────

def _make_bridge_with_mocked_listener():
    """创建 mock listener 的桥接器"""
    bridge = DanmakuBridge()
    bridge._listener = MagicMock()
    bridge._listener.start = AsyncMock()
    bridge._listener.stop = AsyncMock()
    return bridge


# ── DanmakuBridge 关键词方法测试 ──────────────────────────────


class TestGetKeywords:
    """验证标准 1: GET /api/keywords"""

    def test_get_keywords_empty(self):
        """空关键词列表 → {"keywords": [], "enabled": true}"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = []
        bridge._keyword_filter_enabled = True
        result = bridge.get_keywords()
        assert result == {"keywords": [], "enabled": True}

    def test_get_keywords_with_items(self):
        """有关键词 → {"keywords": ["广告", "代练"], "enabled": true}"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = ["广告", "代练"]
        bridge._keyword_filter_enabled = True
        result = bridge.get_keywords()
        assert result == {"keywords": ["广告", "代练"], "enabled": True}

    def test_get_keywords_filter_disabled(self):
        """过滤禁用 → enabled: false"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = ["广告"]
        bridge._keyword_filter_enabled = False
        result = bridge.get_keywords()
        assert result == {"keywords": ["广告"], "enabled": False}


class TestAddKeyword:
    """验证标准 2, 6, 7: POST /api/keywords"""

    def test_add_keyword_success(self):
        """添加关键词 → {"success": true, "keywords": ["广告"]}"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = []
        result = bridge.add_keyword("广告")
        assert result["success"] is True
        assert "广告" in result["keywords"]
        assert "广告" in bridge._blocked_keywords

    def test_add_keyword_too_long(self):
        """关键词长度超过 50 → 抛 ValueError"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = []
        with pytest.raises(ValueError, match="50"):
            bridge.add_keyword("a" * 51)

    def test_add_keyword_duplicate(self):
        """重复添加同一关键词 → 不重复"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = ["广告"]
        result = bridge.add_keyword("广告")
        assert result["success"] is True
        assert bridge._blocked_keywords.count("广告") == 1
        assert len(result["keywords"]) == 1

    def test_add_keyword_saves_to_file(self):
        """添加关键词后调用 _save_blocked_keywords"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = []
        with patch.object(bridge, '_save_blocked_keywords') as mock_save:
            bridge.add_keyword("广告")
            mock_save.assert_called_once()


class TestRemoveKeyword:
    """验证标准 3: DELETE /api/keywords/{keyword}"""

    def test_remove_keyword_success(self):
        """删除关键词 → {"success": true, "keywords": []}"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = ["广告"]
        result = bridge.remove_keyword("广告")
        assert result["success"] is True
        assert "广告" not in result["keywords"]
        assert "广告" not in bridge._blocked_keywords

    def test_remove_keyword_not_found(self):
        """删除不存在的关键词 → 仍返回成功（幂等）"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = []
        result = bridge.remove_keyword("广告")
        assert result["success"] is True

    def test_remove_keyword_saves_to_file(self):
        """删除关键词后调用 _save_blocked_keywords"""
        bridge = DanmakuBridge()
        bridge._blocked_keywords = ["广告"]
        with patch.object(bridge, '_save_blocked_keywords') as mock_save:
            bridge.remove_keyword("广告")
            mock_save.assert_called_once()


class TestToggleKeywordFilter:
    """验证标准 4: PUT /api/keywords/toggle"""

    def test_toggle_enable(self):
        """开启过滤 → {"success": true, "enabled": true}"""
        bridge = DanmakuBridge()
        bridge._keyword_filter_enabled = False
        result = bridge.toggle_keyword_filter(True)
        assert result["success"] is True
        assert result["enabled"] is True
        assert bridge._keyword_filter_enabled is True

    def test_toggle_disable(self):
        """关闭过滤 → {"success": true, "enabled": false}"""
        bridge = DanmakuBridge()
        bridge._keyword_filter_enabled = True
        result = bridge.toggle_keyword_filter(False)
        assert result["success"] is True
        assert result["enabled"] is False
        assert bridge._keyword_filter_enabled is False


# ── API 路由测试 ──────────────────────────────────────────────


class TestKeywordsAPI:
    """API 路由集成测试"""

    @pytest.mark.asyncio
    async def test_get_keywords_api(self):
        """GET /api/keywords → 200"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/keywords")
            assert resp.status == 200
            data = await resp.json()
            assert "keywords" in data
            assert "enabled" in data

    @pytest.mark.asyncio
    async def test_add_keyword_api(self):
        """POST /api/keywords → 200"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/keywords", json={"keyword": "广告"})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert "广告" in data["keywords"]

    @pytest.mark.asyncio
    async def test_add_keyword_too_long_api(self):
        """POST /api/keywords 超长 → 400"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/keywords", json={"keyword": "a" * 51})
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_remove_keyword_api(self):
        """DELETE /api/keywords/{keyword} → 200"""
        bridge = _make_bridge_with_mocked_listener()
        bridge._blocked_keywords = ["广告"]
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/keywords/广告")
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_toggle_keyword_filter_api(self):
        """PUT /api/keywords/toggle → 200"""
        bridge = _make_bridge_with_mocked_listener()
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            resp = await client.put("/api/keywords/toggle", json={"enabled": False})
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["enabled"] is False
