"""F1 登录态快照/恢复 + F3 WS 回环判定 单元测试（2026-10-10 小红书 profile 重测回归）

探针实证背景（tools/send_probes/cards/xhs-persist-*）：
- 登录 cookie 为持久型（id_token/web_session 1 年期），历史全丢根因=硬杀丢
  未提交窗口 + 登录从未落盘 → F1 快照（登录检测点立即落盘）+ 恢复（启动自愈）
- 同 profile 双 persistent context 必然 TargetClosedError → F2 发送/监听互斥
- 游客态 #input-area 可见（可见性判登录失真）→ cookie 判定
- DOM 列表回显受乐观渲染/虚拟列表影响（10-09 16:06 假 SENT 来源）→
  F3 WS text 帧服务端回环为唯一 SENT 真源
"""
import base64
import json

import pytest

from danmaku_listener.engines.protocol.xiaohongshu import (
    XiaohongshuEngine,
    ws_echo_frame,
    ws_echo_hit,
)


class _FakeCtx:
    """duck-typed context：cookies()/storage_state()/add_cookies()"""

    def __init__(self, cookies):
        self._cookies = cookies
        self.added: list = []

    async def cookies(self):
        return self._cookies

    async def storage_state(self):
        return {"cookies": list(self._cookies), "origins": []}

    async def add_cookies(self, cookies):
        self.added.append(list(cookies))


def _cookie(name: str, value: str = "v") -> dict:
    return {"name": name, "value": value,
            "domain": ".xiaohongshu.com", "path": "/"}


def _engine(tmp_path) -> XiaohongshuEngine:
    return XiaohongshuEngine(cookie_dir=str(tmp_path))


def _write_snapshot(tmp_path, cookies: list) -> None:
    (tmp_path / "xhs_profile_login_state.json").write_text(
        json.dumps({"cookies": cookies}, ensure_ascii=False), encoding="utf-8")


# ---- F1 快照 ----

@pytest.mark.asyncio
async def test_snapshot_writes_only_with_login_cookie(tmp_path):
    eng = _engine(tmp_path)
    # 游客 web_session 不算登录（login_gate 判定边界——游客也带 web_session）
    guest = _FakeCtx([_cookie("web_session", "anon"), _cookie("a1", "x")])
    assert await eng._snapshot_login_state(guest) is False
    assert not (tmp_path / "xhs_profile_login_state.json").exists()

    logged = _FakeCtx([_cookie("web_session", "u"), _cookie("id_token", "jwt")])
    assert await eng._snapshot_login_state(logged) is True
    state = json.loads(
        (tmp_path / "xhs_profile_login_state.json").read_text(encoding="utf-8"))
    assert any(c["name"] == "id_token" for c in state["cookies"])


@pytest.mark.asyncio
async def test_snapshot_failure_never_raises(tmp_path):
    eng = _engine(tmp_path)

    class _BoomCtx(_FakeCtx):
        async def storage_state(self):
            raise RuntimeError("pw dead")

    assert await eng._snapshot_login_state(_BoomCtx([_cookie("id_token")])) is False
    assert await eng._snapshot_login_state(_BoomCtx([])) is False


# ---- F1 恢复 ----

@pytest.mark.asyncio
async def test_restore_skipped_when_profile_has_login(tmp_path):
    eng = _engine(tmp_path)
    _write_snapshot(tmp_path, [_cookie("id_token", "snap")])
    ctx = _FakeCtx([_cookie("id_token", "profile")])
    assert await eng._restore_login_state(ctx) is False
    assert ctx.added == []  # profile 登录健在——不动 cookie


@pytest.mark.asyncio
async def test_restore_injects_snapshot_when_profile_lost_login(tmp_path):
    eng = _engine(tmp_path)
    snap = [_cookie("id_token", "snap"), _cookie("a1", "x")]
    _write_snapshot(tmp_path, snap)
    ctx = _FakeCtx([_cookie("web_session", "anon")])
    assert await eng._restore_login_state(ctx) is True
    assert len(ctx.added) == 1
    assert {c["name"] for c in ctx.added[0]} == {"id_token", "a1"}


@pytest.mark.asyncio
async def test_restore_noop_without_snapshot_or_guest_snapshot(tmp_path):
    eng = _engine(tmp_path)
    ctx = _FakeCtx([_cookie("web_session", "anon")])
    # 无快照
    assert await eng._restore_login_state(ctx) is False
    # 快照仅游客 cookie（无 id_token）——不注入
    _write_snapshot(tmp_path, [_cookie("web_session", "anon")])
    assert await eng._restore_login_state(ctx) is False
    assert ctx.added == []


# ---- F3 WS 回环判定 ----

def _ws_text_frame(desc: str, user_id: str = "u1") -> str:
    """构造 t==4 业务帧（parse_ws_frame 逆过程）"""
    custom = json.dumps({"type": "text", "desc": desc,
                         "profile": {"nickname": "我", "user_id": user_id}},
                        ensure_ascii=False)
    wrapper = json.dumps({"customData": custom})
    return json.dumps({"t": 4, "b": {"d": {"b": [
        {"d": base64.b64encode(wrapper.encode("utf-8")).decode("ascii")}]}
    }})


def test_ws_echo_hit_matches_own_danmu():
    frame = _ws_text_frame("[M0] probe 1")
    assert ws_echo_hit([frame], "[M0] probe 1") is True


# ---- F4 自发声回环 ----

@pytest.mark.asyncio
async def test_ws_echo_frame_returns_custom_data_for_injection():
    frame = _ws_text_frame("[M0] probe 1", user_id="me")
    cd = ws_echo_frame([frame], "[M0] probe 1")
    assert cd is not None
    assert cd["type"] == "text"
    assert cd["profile"]["user_id"] == "me"
    assert ws_echo_frame([frame], "别的") is None


def _capturing_engine(tmp_path):
    eng = _engine(tmp_path)
    captured: list = []

    async def _fake_emit(msg):
        captured.append(msg)

    eng._emit_message = _fake_emit       # 实例级 monkeypatch（引擎同款 await 契约）
    eng.mark_received = lambda *a, **k: None
    return eng, captured


@pytest.mark.asyncio
async def test_emit_self_echo_injects_danmu_envelope(tmp_path):
    eng, captured = _capturing_engine(tmp_path)
    cd = {"type": "text", "desc": "你好房间",
          "profile": {"nickname": "我", "user_id": "me"}}
    await eng._emit_self_echo("room1", cd)
    assert len(captured) == 1
    env = captured[0]
    assert env["category"] == "business"
    assert env["type"] == "DANMU"
    assert env["payload"]["content"] == "你好房间"
    assert env["room_id"] == "room1"
    assert eng._self_echo_mark is not None
    assert eng._self_echo_mark[0] == "你好房间"


@pytest.mark.asyncio
async def test_emit_self_echo_ignores_non_danmu(tmp_path):
    eng, captured = _capturing_engine(tmp_path)
    await eng._emit_self_echo("room1", {"type": "praise",
                                        "praise_info": {"count": 1}})
    assert captured == []
    assert eng._self_echo_mark is None


@pytest.mark.asyncio
async def test_listener_dedups_recent_self_echo(tmp_path):
    import time as _time
    eng, captured = _capturing_engine(tmp_path)
    eng._self_echo_mark = ("你好房间", _time.monotonic())
    frame = {"payload": _ws_text_frame("你好房间")}
    await eng._on_ws_frame("room1", frame)
    assert captured == []           # 发送侧已注入——监听侧同帧跳过
    assert eng._self_echo_mark is None  # 标记一次性消费

    # 窗口外/异内容照常 emit
    eng._self_echo_mark = ("别的", _time.monotonic() - 30)
    await eng._on_ws_frame("room1", frame)
    assert len(captured) == 1


def test_ws_echo_hit_ignores_other_text_and_noise():
    frame = _ws_text_frame("别人的弹幕")
    assert ws_echo_hit([frame], "[M0] probe 1") is False
    assert ws_echo_hit([None, "garbage", 42], "[M0] probe 1") is False
    assert ws_echo_hit([], "x") is False


def test_ws_echo_hit_ignores_non_text_business_frames():
    custom = json.dumps({"type": "praise", "praise_info": {"count": 1},
                         "profile": {"user_id": "u1"}})
    wrapper = json.dumps({"customData": custom})
    frame = json.dumps({"t": 4, "b": {"d": {"b": [
        {"d": base64.b64encode(wrapper.encode("utf-8")).decode("ascii")}]}
    }})
    # 点赞帧 profile 无 desc——文本内容恰好相同也不算回显
    assert ws_echo_hit([frame], "x") is False


# ---- F2 发送/监听互斥状态位 ----

def test_send_active_gate_defaults():
    eng = _engine(".")
    # 类属性默认：发送未激活、无监听 context（F2 门初始态）
    assert XiaohongshuEngine._send_active is False
    assert XiaohongshuEngine._listen_ctx is None
    assert eng._send_active is False
    assert eng._listen_ctx is None
