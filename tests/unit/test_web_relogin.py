"""手动重新登录流程单元测试（2026-10-10——发送按钮旁"登录"按钮）

覆盖：载体清理（profile 目录/快照/cookie 文件）+ 路径逃逸防护 + 平台清单
完整性 + 流程编排（停该平台在听房间→清载体→start_room 触发既有登录门）。
"""
import pytest

from danmaku_listener.web.relogin import (
    PLATFORM_LOGIN_CARRIERS,
    ReloginUnsupported,
    clear_login_state,
    run_relogin_flow,
)


# ---- 载体清理 ----

def test_clear_login_state_removes_profile_and_files(tmp_path):
    (tmp_path / "xhs_profile" / "Default").mkdir(parents=True)
    (tmp_path / "xhs_profile" / "Default" / "Cookies").write_text("x")
    (tmp_path / "xhs_profile_login_state.json").write_text("{}")
    deleted = clear_login_state("xiaohongshu", cookie_dir=str(tmp_path))
    assert "xhs_profile" in deleted and "xhs_profile_login_state.json" in deleted
    assert not (tmp_path / "xhs_profile").exists()


def test_clear_login_state_idempotent_when_missing(tmp_path):
    assert clear_login_state("xiaohongshu", cookie_dir=str(tmp_path)) == []


def test_clear_login_state_path_escape_guard(tmp_path, monkeypatch):
    (tmp_path.parent / "evil.txt").write_text("x")
    monkeypatch.setitem(PLATFORM_LOGIN_CARRIERS, "evil", ["../evil.txt"])
    deleted = clear_login_state("evil", cookie_dir=str(tmp_path))
    assert deleted == []  # 逃逸路径跳过
    assert (tmp_path.parent / "evil.txt").exists()


def test_clear_login_state_unsupported_platform(tmp_path):
    with pytest.raises(ReloginUnsupported):
        clear_login_state("meituan", cookie_dir=str(tmp_path))


# ---- 平台清单完整性（10 个可发送平台全覆盖）----

def test_all_sendable_platforms_have_carriers():
    expected = {"taobao", "1688", "xiaohongshu", "jd", "huya", "douyin",
                "bilibili", "kuaishou", "douyu", "wechat_channels", "pdd"}
    assert expected <= set(PLATFORM_LOGIN_CARRIERS)


# ---- 流程编排 ----

class FakeBridge:
    def __init__(self):
        self._rooms = {
            "taobao:123": {"platform": "taobao", "room_id": "123", "status": "running"},
            "taobao:456": {"platform": "taobao", "room_id": "456", "status": "stopped"},
            "jd:485": {"platform": "jd", "room_id": "485", "status": "running"},
        }
        self.started: list = []
        self.stopped: list = []

    async def start_room(self, platform, room_id):
        self.started.append((platform, room_id))

    async def stop_room(self, platform, room_id):
        self.stopped.append((platform, room_id))
        self._rooms[f"{platform}:{room_id}"]["status"] = "stopped"


@pytest.mark.asyncio
async def test_run_relogin_flow_stops_clears_and_restarts(tmp_path):
    bridge = FakeBridge()
    (tmp_path / "taobao_profile").mkdir()
    result = await run_relogin_flow(bridge, "taobao", "123", cookie_dir=str(tmp_path))
    assert result["success"] is True
    # 仅停该平台 running 房间（stopped 态的 456 与跨平台 jd 不动）
    assert bridge.stopped == [("taobao", "123")]
    assert bridge.started == [("taobao", "123")]
    assert "taobao_profile" in result["cleared"]


@pytest.mark.asyncio
async def test_run_relogin_flow_unsupported_platform(tmp_path):
    with pytest.raises(ReloginUnsupported):
        await run_relogin_flow(FakeBridge(), "meituan", "1", cookie_dir=str(tmp_path))
