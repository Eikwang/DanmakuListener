"""手动重新登录流程单元测试 v2（2026-10-13 会话刷新编排——/autoplan 批准计划）

覆盖：载体清理（子集覆写/逃逸防护/清单完整性）+ 编排同步段回执形状 + 多房间
恢复 + supersede 停房集合转移 + 空集合等 send_refresh 落定（防 completed 吞
refresh_failed）+ 抖音单窗双喂（域白名单导出/导出失败语义/登录超时）+ 虎牙
takeover 失败部分成功语义 + 注册表生命周期（淘汰/404）+ fence 查表。
"""
import asyncio
import uuid

import pytest

from danmaku_listener.web import relogin as rl
from danmaku_listener.web.relogin import (
    PLATFORM_LOGIN_CARRIERS,
    RELOGIN_CLEAN_SUBSETS,
    ReloginUnsupported,
    clear_login_state,
    get_active_relogin,
    get_relogin_status,
    run_relogin_flow,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """注册表/任务表/平台锁每用例重置（模块级单例隔离）"""
    rl.REGISTRY = rl.ReloginRegistry()
    rl._active_tasks = {}
    rl._platform_locks = {}
    yield
    for task in rl._active_tasks.values():
        task.cancel()


# ---- 载体清理 ----

def test_clear_login_state_removes_profile_and_files(tmp_path):
    (tmp_path / "xhs_profile" / "Default").mkdir(parents=True)
    (tmp_path / "xhs_profile" / "Default" / "Cookies").write_text("x")
    (tmp_path / "xhs_profile_login_state.json").write_text("{}")
    deleted = clear_login_state("xiaohongshu", cookie_dir=str(tmp_path))
    assert "xhs_profile" in deleted and "xhs_profile_login_state.json" in deleted
    assert not (tmp_path / "xhs_profile").exists()


def test_clear_login_state_subset_override(tmp_path):
    """S1 预定清理子集：douyin 只清监听 cookie 文件，发送 profile 不预清"""
    (tmp_path / "douyin_profile").mkdir()
    (tmp_path / "douyin_cookies.json").write_text("[]")
    deleted = clear_login_state("douyin", cookie_dir=str(tmp_path),
                                carriers=RELOGIN_CLEAN_SUBSETS["douyin"])
    assert deleted == ["douyin_cookies.json"]
    assert (tmp_path / "douyin_profile").exists()  # 发送 profile 未动


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


def test_all_sendable_platforms_have_carriers():
    expected = {"taobao", "1688", "xiaohongshu", "jd", "huya", "douyin",
                "bilibili", "kuaishou", "douyu", "wechat_channels", "pdd"}
    assert expected <= set(PLATFORM_LOGIN_CARRIERS)


# ---- FakeBridge（v2：start_room 可模拟成功恢复/失败）----

class FakeBridge:
    def __init__(self, start_fails=False):
        self._rooms = {
            "taobao:123": {"platform": "taobao", "room_id": "123", "status": "running"},
            "taobao:789": {"platform": "taobao", "room_id": "789", "status": "running"},
            "taobao:456": {"platform": "taobao", "room_id": "456", "status": "stopped"},
            "jd:485": {"platform": "jd", "room_id": "485", "status": "running"},
        }
        self.started: list = []
        self.stopped: list = []
        self.start_fails = start_fails

    async def start_room(self, platform, room_id):
        if self.start_fails:
            raise RuntimeError("engine launch failed")
        self.started.append((platform, room_id))
        self._rooms[f"{platform}:{room_id}"]["status"] = "running"

    async def stop_room(self, platform, room_id):
        self.stopped.append((platform, room_id))
        self._rooms[f"{platform}:{room_id}"]["status"] = "stopped"


async def _await_platform_task(platform, timeout=8.0):
    task = rl._active_tasks.get(platform)
    assert task is not None, "后台编排任务未创建"
    await asyncio.wait_for(task, timeout=timeout)


# ---- 编排同步段 + 多房间恢复（T1/T3-D 修复验证）----

@pytest.mark.asyncio
async def test_sync_payload_shape_and_multi_room_recovery(tmp_path):
    """同步段回执形状（计划 §3.1-6）+ 多房间全量恢复（D 修复）+ 终态 completed"""
    bridge = FakeBridge()
    (tmp_path / "taobao_profile").mkdir()
    result = await run_relogin_flow(bridge, "taobao", "123", cookie_dir=str(tmp_path))
    assert result["success"] is True
    assert uuid.UUID(result["relogin_id"])  # uuid4 级熵（Eng 发现11-1）
    assert result["platform"] == "taobao"
    assert sorted(result["rooms_stopped"]) == ["123", "789"]  # 全平台 running 房间
    assert "taobao_profile" in result["carriers_cleared"]
    assert result["send_refresh"] == "not_applicable"  # 单载体终值
    kinds = {(f["side"], f["kind"]) for f in result["login_flows"]}
    assert ("listen", "login_gate") in kinds
    assert result["status_url"].startswith("/api/relogin/status?id=")
    # 仅停该平台 running 房间（stopped 态的 456 与跨平台 jd 不动）
    assert bridge.stopped == [("taobao", "123"), ("taobao", "789")]
    # 后台编排：登录门触发 + watcher 判定 completed
    await _await_platform_task("taobao")
    assert sorted(bridge.started) == [("taobao", "123"), ("taobao", "789")]
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "completed"
    assert status["interruption_window"]["ended_at"] is not None
    assert all(r["status"] == "running" for r in status["rooms"].values())


@pytest.mark.asyncio
async def test_start_room_failure_marks_recovery_error(tmp_path):
    """start_room 失败计入房间恢复失败（rooms[].recovery_error）→ failed 终局"""
    bridge = FakeBridge(start_fails=True)
    (tmp_path / "taobao_profile").mkdir()
    result = await run_relogin_flow(bridge, "taobao", "123", cookie_dir=str(tmp_path))
    await _await_platform_task("taobao")
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "failed"
    assert "房间恢复失败" in status["error"]  # 早停终局（全部 failed 无可等待）
    assert any(r.get("recovery_error") for r in status["rooms"].values())


@pytest.mark.asyncio
async def test_supersede_transfers_stopped_rooms(tmp_path, monkeypatch):
    """E6：supersede 取消+join、旧记录 superseded、停房集合转移给新记录"""
    import danmaku_listener.engines.douyin_login as dl

    release = asyncio.Event()

    async def slow_login(*args, **kwargs):
        await asyncio.wait_for(release.wait(), timeout=5.0)
        return {"status": "ok", "profile_dir": "cookie/douyin_profile", "export": "ok"}

    monkeypatch.setattr(dl, "run_profile_login_flow", slow_login)
    bridge = FakeBridge()
    bridge._rooms["douyin:1"] = {"platform": "douyin", "room_id": "1", "status": "running"}
    bridge._rooms["douyin:2"] = {"platform": "douyin", "room_id": "2", "status": "running"}
    (tmp_path / "douyin_cookies.json").write_text("[]")

    first = await run_relogin_flow(bridge, "douyin", "1", cookie_dir=str(tmp_path))
    first_id = first["relogin_id"]
    await asyncio.sleep(0.05)  # 让旧任务进入登录等待
    second = await run_relogin_flow(bridge, "douyin", "2", cookie_dir=str(tmp_path))
    second_id = second["relogin_id"]
    assert first_id != second_id
    old = get_relogin_status(first_id)
    assert old["state"] == "superseded"
    assert old["superseded_by"] == second_id
    # 停房集合转移：新记录 rooms 覆盖旧记录未恢复的房间（1/2 都在恢复集合）
    assert {"1", "2"} <= set(second["rooms_stopped"])
    release.set()  # 放行新登录流程
    await _await_platform_task("douyin")
    final = get_relogin_status(second_id)
    assert final["state"] == "completed"


@pytest.mark.asyncio
async def test_douyin_empty_rooms_waits_send_refresh_then_login_required(tmp_path, monkeypatch):
    """E6/发现5：空停房集合只豁免房间等待——state 等 send_refresh 落定；
    登录超时 → login_required（不得提前 completed 吞掉失败）"""
    import danmaku_listener.engines.douyin_login as dl

    async def timeout_login(*args, **kwargs):
        return {"status": "timeout_or_closed", "profile_dir": "x", "export": "failed"}

    monkeypatch.setattr(dl, "run_profile_login_flow", timeout_login)
    bridge = FakeBridge()
    bridge._rooms.pop("taobao:123"), bridge._rooms.pop("taobao:789")
    (tmp_path / "douyin_cookies.json").write_text("[]")
    result = await run_relogin_flow(bridge, "douyin", "1", cookie_dir=str(tmp_path))
    await _await_platform_task("douyin")
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "login_required"
    assert status["send_refresh"] == "refresh_failed"
    assert "旧态保留" in (status["error"] or "")


@pytest.mark.asyncio
async def test_douyin_export_failed_partial_success(tmp_path, monkeypatch):
    """Eng 发现12：导出失败 → refresh_failed 不翻转整体 state（completed+error）"""
    import danmaku_listener.engines.douyin_login as dl

    async def ok_but_export_failed(*args, **kwargs):
        return {"status": "ok", "profile_dir": "x", "export": "failed"}

    monkeypatch.setattr(dl, "run_profile_login_flow", ok_but_export_failed)
    bridge = FakeBridge()
    (tmp_path / "douyin_cookies.json").write_text("[]")
    result = await run_relogin_flow(bridge, "douyin", "1", cookie_dir=str(tmp_path))
    await _await_platform_task("douyin")
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "completed"  # 部分成功语义
    assert status["send_refresh"] == "refresh_failed"
    assert "导出失败" in (status["error"] or "")


@pytest.mark.asyncio
async def test_douyin_ok_recovers_rooms_with_whitelist_export(tmp_path, monkeypatch):
    """S2 全链（mock）：登录 ok+导出 ok → refresh_ok + 房间恢复 → completed"""
    import danmaku_listener.engines.douyin_login as dl

    async def ok_login(*args, **kwargs):
        return {"status": "ok", "profile_dir": "x", "export": "ok"}

    monkeypatch.setattr(dl, "run_profile_login_flow", ok_login)
    bridge = FakeBridge()
    bridge._rooms["douyin:1"] = {"platform": "douyin", "room_id": "1", "status": "running"}
    (tmp_path / "douyin_cookies.json").write_text("[]")
    result = await run_relogin_flow(bridge, "douyin", "1", cookie_dir=str(tmp_path))
    assert result["send_refresh"] == "close_ok"  # 同步段中间值（登录结果异步→refresh_*）
    assert result["login_flows"][0]["kind"] == "profile_login"
    await _await_platform_task("douyin")
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "completed"
    assert status["send_refresh"] == "refresh_ok"


# ---- 虎牙（S3：takeover 失败=refresh_failed，监听恢复不依赖发送侧）----

class FakeHuyaSession:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False
        self.takeover_calls: list = []

    async def login_takeover(self, room_id, url, cookie_names, grace_s=30.0):
        self.takeover_calls.append((room_id, url))
        if self.fail:
            from danmaku_listener.senders.resident_session import LoginTakeoverError
            raise LoginTakeoverError("登录未完成（超时/关窗）")
        return None

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_huya_takeover_fail_listen_still_recovers(tmp_path, monkeypatch):
    """S3：takeover 失败 → refresh_failed 不翻转 state；监听直启恢复照常"""
    import danmaku_listener.senders.huya as huya_mod

    fake = FakeHuyaSession(fail=True)
    monkeypatch.setattr(huya_mod, "_session", fake)
    bridge = FakeBridge()
    bridge._rooms["huya:9"] = {"platform": "huya", "room_id": "9", "status": "running"}
    result = await run_relogin_flow(bridge, "huya", "9", cookie_dir=str(tmp_path))
    assert result["send_refresh"] == "close_ok"  # 存在才关：fake 会话被 close
    assert result["login_flows"][0]["kind"] == "takeover"
    await _await_platform_task("huya")  # 先等后台编排（create_task 仅排队——断言时序）
    assert fake.takeover_calls == [("9", "https://www.huya.com/")]  # S3 参数装配
    status = get_relogin_status(result["relogin_id"])
    assert status["state"] == "completed"  # 部分成功语义
    assert status["send_refresh"] == "refresh_failed"
    assert any(r["status"] == "running" for r in status["rooms"].values())


# ---- 注册表生命周期（淘汰=404 语义）----

def _mk_finished(platform="taobao", i=0):
    rec = rl.REGISTRY.create(platform, str(i), [], [], [], "not_applicable", [])
    rl.REGISTRY.finish(rec["relogin_id"], "completed")
    return rec


def test_registry_gc_drops_oldest_beyond_keep_max():
    ids = [_mk_finished(i=i)["relogin_id"] for i in range(rl.REGISTRY_KEEP_MAX + 3)]
    assert get_relogin_status(ids[0]) is None  # 最旧被淘汰 → 404 语义
    assert get_relogin_status(ids[-1]) is not None


def test_get_relogin_status_unknown_id_none():
    assert get_relogin_status("00000000-0000-0000-0000-000000000000") is None


def test_get_active_relogin_fence_lookup():
    rec = rl.REGISTRY.create("taobao", "1", ["1"], [], [], "not_applicable", [])
    rl.REGISTRY.bind_active("taobao", rec["relogin_id"])
    active = get_active_relogin("taobao")
    assert active and active["relogin_id"] == rec["relogin_id"]
    assert get_active_relogin("jd") is None


# ---- 抖音域白名单导出（Eng 发现11/E8）----

class FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    async def storage_state(self):
        return {"cookies": self._cookies}


@pytest.mark.asyncio
async def test_douyin_export_domain_whitelist(tmp_path, monkeypatch):
    """域白名单：仅留 douyin.com 系；ttwid/msToken 排除；原子落盘"""
    from danmaku_listener.engines.douyin_login import _export_listen_cookies

    ctx = FakeContext([
        {"name": "sessionid", "value": "s1", "domain": ".douyin.com"},
        {"name": "sessionid_ss", "value": "s2", "domain": "live.douyin.com"},
        {"name": "ttwid", "value": "t1", "domain": ".douyin.com"},       # 排除约定
        {"name": "msToken", "value": "m1", "domain": ".douyin.com"},     # 排除约定
        {"name": "unrelated", "value": "u1", "domain": ".bytedance.com"},  # 白名单外
        {"name": "empty", "value": "", "domain": ".douyin.com"},         # 空值剔除
    ])
    out = str(tmp_path / "douyin_cookies.json")
    status = await _export_listen_cookies(ctx, out)
    assert status == "ok"
    import json as _json
    saved = _json.load(open(out, encoding="utf-8"))
    names = {c["name"] for c in saved}
    assert names == {"sessionid", "sessionid_ss"}
    assert not (tmp_path / "douyin_cookies.json.tmp").exists()  # 原子替换无残留


@pytest.mark.asyncio
async def test_douyin_export_failure_returns_failed(tmp_path, monkeypatch):
    """导出异常不抛（不阻断关窗 finally）→ failed"""
    from danmaku_listener.engines.douyin_login import _export_listen_cookies

    class BoomContext:
        async def storage_state(self):
            raise RuntimeError("storage_state crashed")

    status = await _export_listen_cookies(BoomContext(), str(tmp_path / "x.json"))
    assert status == "failed"
