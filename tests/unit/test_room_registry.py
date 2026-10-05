"""房间注册表持久化 + 选项式添加 + 启停 API 测试（2026-10-05 R2/R3）

覆盖：
- platform_parser.extract_from_link 链接识别（6 平台 + 负例）
- bridge rooms.json 持久化 round-trip（add → 文件 → 新实例恢复 stopped）
- POST /api/rooms/{p}/{r}/start|stop 状态迁移
- stop_all 保留列表（语义变化：全部暂停而非清空）
- 选项模式添加 {platform, room}（纯房号 / 链接 / 提取失败 400）
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from danmaku_listener.utils.platform_parser import extract_from_link, parse_room_spec
from danmaku_listener.web.bridge import DanmakuBridge


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """rooms.json 为 cwd 相对路径（persistence_data/rooms.json）——
    chdir 到临时目录隔离读/写；登录门槛统一视为已登录
    （登录闭环行为由登录专项测试覆盖）"""
    monkeypatch.chdir(tmp_path)
    for mod_path in ("danmaku_listener.engines.bilibili_login",
                     "danmaku_listener.engines.kuaishou_login",
                     "danmaku_listener.engines.douyin_login"):
        monkeypatch.setattr(f"{mod_path}.has_login_cookie", lambda p: True)


def _make_bridge():
    """构造桥接器（listener mock；引擎在测试内按需 patch build_engine）"""
    bridge = DanmakuBridge()
    bridge._listener = MagicMock()
    bridge._listener.start = AsyncMock()
    bridge._listener.stop = AsyncMock()
    return bridge


def _make_engine():
    engine = MagicMock()
    engine.start = AsyncMock()
    engine.stop = AsyncMock()
    engine.engine_id = "mock:engine"
    return engine


class TestExtractFromLink:
    """链接识别（2026-10-05 R2）"""

    def test_douyin(self):
        spec = extract_from_link("https://live.douyin.com/55814568")
        assert spec is not None and spec.platform == "douyin"
        assert spec.room_id == "55814568"

    def test_douyu(self):
        spec = extract_from_link("https://www.douyu.com/74960")
        assert spec is not None and spec.platform == "douyu"
        assert spec.room_id == "74960"

    def test_bilibili(self):
        spec = extract_from_link("https://live.bilibili.com/23058")
        assert spec is not None and spec.platform == "bilibili"
        assert spec.room_id == "23058"

    def test_huya(self):
        spec = extract_from_link("https://www.huya.com/29330704")
        assert spec is not None and spec.platform == "huya"
        assert spec.room_id == "29330704"

    def test_jd_liveid(self):
        spec = extract_from_link("https://zhibo.jd.com/liveroom?liveId=3612345&from=share")
        assert spec is not None and spec.platform == "jd"
        assert spec.room_id == "3612345"

    def test_1688_feedid(self):
        spec = extract_from_link(
            "https://live.1688.com/zb/play.html?feedId=2720839874018747&foo=bar")
        assert spec is not None and spec.platform == "1688"
        assert spec.room_id == "2720839874018747"

    def test_plain_room_id_returns_none(self):
        assert extract_from_link("55814568") is None

    def test_unknown_link_returns_none(self):
        assert extract_from_link("https://example.com/live/123") is None

    def test_empty_returns_none(self):
        assert extract_from_link("") is None

    def test_parse_room_spec_unchanged(self):
        """旧格式解析不受影响（additive）"""
        spec = parse_room_spec("douyin:55814568")
        assert spec.platform == "douyin" and spec.room_id == "55814568"


class TestRegistryPersistence:
    """rooms.json 持久化 round-trip（2026-10-05 R3）"""

    @pytest.mark.asyncio
    async def test_add_writes_registry(self):
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            await bridge.add_room("bilibili:23058")
        # 注册表文件落盘
        with open(bridge._rooms_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["platform"] == "bilibili"
        assert data[0]["room_id"] == "23058"

    @pytest.mark.asyncio
    async def test_new_instance_restores_stopped(self):
        """新 bridge 实例从注册表恢复——全部 stopped（按需启动语义）"""
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            await bridge.add_room("bilibili:23058")
            await bridge.add_room("douyu:74960")

        bridge2 = DanmakuBridge()  # 同 cwd：读同一注册表
        assert len(bridge2._rooms) == 2
        for room in bridge2._rooms.values():
            assert room["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_remove_deletes_registry(self):
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            await bridge.add_room("bilibili:23058")
            await bridge.remove_room("bilibili", "23058")
        with open(bridge._rooms_file, "r", encoding="utf-8") as f:
            assert json.load(f) == []

    def test_corrupted_registry_fallback_empty(self, tmp_path):
        """注册表损坏 → 回退空列表不崩溃"""
        import os
        os.makedirs("persistence_data", exist_ok=True)
        with open("persistence_data/rooms.json", "w", encoding="utf-8") as f:
            f.write("{broken json!!")
        bridge = DanmakuBridge()  # 不应抛异常
        assert bridge._rooms == {}


class TestStartStopRoom:
    """start/stop 单房间 API（2026-10-05 R3）"""

    @pytest.mark.asyncio
    async def test_stop_then_start_roundtrip(self):
        bridge = _make_bridge()
        engine = _make_engine()
        with patch("danmaku_listener.engines.registry.build_engine", return_value=engine):
            await bridge.add_room("bilibili:23058")
            assert bridge._rooms["bilibili:23058"]["status"] == "running"

            await bridge.stop_room("bilibili", "23058")
            assert bridge._rooms["bilibili:23058"]["status"] == "stopped"
            # 注册表保留（未删除）
            assert "bilibili:23058" in bridge._rooms

            await bridge.start_room("bilibili", "23058")
            assert bridge._rooms["bilibili:23058"]["status"] == "running"
            assert engine.start.call_count == 2
            assert engine.stop.call_count == 1

    @pytest.mark.asyncio
    async def test_stop_not_found_404(self):
        bridge = _make_bridge()
        from danmaku_listener.web.bridge import RoomError
        with pytest.raises(RoomError) as ei:
            await bridge.stop_room("bilibili", "999999")
        assert ei.value.status == 404

    @pytest.mark.asyncio
    async def test_start_not_found_404(self):
        bridge = _make_bridge()
        from danmaku_listener.web.bridge import RoomError
        with pytest.raises(RoomError) as ei:
            await bridge.start_room("bilibili", "999999")
        assert ei.value.status == 404

    @pytest.mark.asyncio
    async def test_stop_all_preserves_list(self):
        """全部暂停：列表保留、全转 stopped（语义变化，2026-10-05 R3）"""
        bridge = _make_bridge()
        engine = _make_engine()
        with patch("danmaku_listener.engines.registry.build_engine", return_value=engine):
            await bridge.add_room("bilibili:111")
            await bridge.add_room("bilibili:222")
            await bridge.stop_all()
        assert len(bridge._rooms) == 2  # 列表保留
        for room in bridge._rooms.values():
            assert room["status"] == "stopped"
        assert engine.stop.call_count == 2

    @pytest.mark.asyncio
    async def test_re_add_after_restart_restarts(self):
        """serve 重启后（stopped 恢复）重新添加同一房间 → 重新启动而非 409"""
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            await bridge.add_room("bilibili:23058")
        bridge2 = DanmakuBridge()  # 模拟重启：注册表恢复为 stopped
        assert bridge2._rooms["bilibili:23058"]["status"] == "stopped"
        with patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            result = await bridge2.add_room("bilibili:23058")  # 不应 409
        assert result["room"]["status"] == "running"


class TestOptionModeAdd:
    """选项模式添加 {platform, room}（2026-10-05 R2）"""

    @pytest.mark.asyncio
    async def test_add_with_platform_plain_id(self):
        """{platform: douyin, room: 55814568} → running"""
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.douyin_login.has_login_cookie",
                   return_value=True), \
             patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            result = await bridge.add_room("55814568", platform="douyin")
        assert result["success"] is True
        assert result["room"]["status"] == "running"
        assert bridge._rooms["douyin:55814568"]["room_id"] == "55814568"

    @pytest.mark.asyncio
    async def test_add_with_platform_link(self):
        """{platform: douyin, room: 链接} → 提取房号"""
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.douyin_login.has_login_cookie",
                   return_value=True), \
             patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            result = await bridge.add_room(
                "https://live.douyin.com/55814568", platform="douyin")
        assert result["success"] is True
        assert bridge._rooms["douyin:55814568"]["room_id"] == "55814568"

    @pytest.mark.asyncio
    async def test_add_with_platform_unextractable_link_400(self):
        """链接无法提取房号 → 整链交引擎归一（2026-10-05 按钮失效修复）"""
        bridge = _make_bridge()
        engine = _make_engine()
        # 美团引擎归一：dpurl.cn 短链 302 → live_id（mock 引擎行为）
        engine.normalize_room_id = AsyncMock(return_value="14566624")
        with patch("danmaku_listener.engines.registry.build_engine", return_value=engine):
            result = await bridge.add_room("http://dpurl.cn/FTcRbc2z", platform="meituan")
        assert result["success"] is True
        # 注册表 room_id 为归一后的 live_id（不含 ://，REST 路径安全）
        assert bridge._rooms["meituan:14566624"]["room_id"] == "14566624"
        engine.normalize_room_id.assert_awaited_once_with("http://dpurl.cn/FTcRbc2z")
        engine.start.assert_called_once_with("14566624")

    @pytest.mark.asyncio
    async def test_add_with_platform_link_normalize_rejected_400(self):
        """引擎归一失败（短链失效）→ 400"""
        bridge = _make_bridge()
        engine = _make_engine()
        engine.normalize_room_id = AsyncMock(side_effect=ValueError("短链跳转未含 liveid"))
        from danmaku_listener.web.bridge import RoomError
        with patch("danmaku_listener.engines.registry.build_engine", return_value=engine):
            with pytest.raises(RoomError) as ei:
                await bridge.add_room("http://dpurl.cn/deadlink", platform="meituan")
        assert ei.value.status == 400

    @pytest.mark.asyncio
    async def test_add_with_platform_unknown_link_rejected_by_validator(self):
        """引擎 validate_room_id 不认的链接 → 400（拒绝路径不消失）"""
        bridge = _make_bridge()
        engine = _make_engine()
        engine.validate_room_id = MagicMock(
            side_effect=ValueError("无法解析房间号"))
        from danmaku_listener.web.bridge import RoomError
        with patch("danmaku_listener.engines.registry.build_engine", return_value=engine):
            with pytest.raises(RoomError) as ei:
                await bridge.add_room("https://example.com/x/1", platform="bilibili")
        assert ei.value.status == 400

    @pytest.mark.asyncio
    async def test_add_with_platform_empty_room_400(self):
        bridge = _make_bridge()
        from danmaku_listener.web.bridge import RoomError
        with pytest.raises(RoomError) as ei:
            await bridge.add_room("  ", platform="douyin")
        assert ei.value.status == 400

    @pytest.mark.asyncio
    async def test_legacy_format_still_works(self):
        """旧格式 {room: "douyin:123"} 兼容保留"""
        bridge = _make_bridge()
        with patch("danmaku_listener.engines.douyin_login.has_login_cookie",
                   return_value=True), \
             patch("danmaku_listener.engines.registry.build_engine",
                   return_value=_make_engine()):
            result = await bridge.add_room("douyin:55814568")
        assert result["room"]["platform"] == "douyin"


class TestEncodedRoomIdRoute:
    """链接型 room_id 的 REST 路由匹配（2026-10-05 按钮失效防御层）

    存量注册表可能仍有链接型 room_id（修复前入库）——前端编码
    （encodeURIComponent）后 aiohttp {room_id} 必须能匹配并解码。
    """

    @pytest.mark.asyncio
    async def test_encoded_link_room_id_stop_and_delete(self):
        from aiohttp import web as _web

        from danmaku_listener.web.app import create_app
        bridge = _make_bridge()
        engine = _make_engine()
        link = "http://dpurl.cn/FTcRbc2z"
        bridge._rooms[f"meituan:{link}"] = {
            "platform": "meituan", "room_id": link,
            "status": "running", "engine_type": "poll:meituan",
        }
        bridge._engine_instances["meituan"] = engine
        app = create_app()
        app["bridge"] = bridge
        async with TestClient(TestServer(app)) as client:
            # 前端 encodeURIComponent 后的形态
            from urllib.parse import quote
            encoded = quote(link, safe="")
            resp = await client.post(f"/api/rooms/meituan/{encoded}/stop")
            assert resp.status == 200, await resp.text()
            assert bridge._rooms[f"meituan:{link}"]["status"] == "stopped"

            resp = await client.delete(f"/api/rooms/meituan/{encoded}")
            assert resp.status == 200
            assert f"meituan:{link}" not in bridge._rooms
