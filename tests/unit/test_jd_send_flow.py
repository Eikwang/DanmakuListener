"""京东发送方案 B 移植回归测试（2026-10-10——F3 WS 回环/F4 自声回环/F2 互斥）

探针实证背景（cards/jd-dom-*）：游客发送区无输入框（"请先登录再发弹幕互动"
error wrapper 取代输入面）——cookie 判登录 + 可见窗等待；咚咚 IM 帧明文 JSON
（viewer_send_message）可作服务端回环真源；F2 上收基类公共件。
"""
import json

import pytest

from danmaku_listener.engines.protocol.jd import (
    JDProtocolEngine,
    jd_ws_echo_frame,
)
from danmaku_listener.engines.protocol.controlled_base import (
    SEND_BG_EXTRA_ARGS,
    ControlledPageEngine,
)


class _FakeCtx:
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
    return {"name": name, "value": value, "domain": ".jd.com", "path": "/"}


def _engine(tmp_path) -> JDProtocolEngine:
    return JDProtocolEngine(cookie_dir=str(tmp_path))


def _jd_send_frame(content: str, nick: str = "我") -> str:
    return json.dumps({"type": "chat_group_message",
                       "from": {"pinmd5": "abc"},
                       "body": {"type": "viewer_send_message",
                                "nickName": nick, "content": content}})


# ---- F3 WS 回环判定 ----

def test_jd_ws_echo_frame_matches_own_danmu():
    frame = _jd_send_frame("[M0] jd probe 1")
    assert jd_ws_echo_frame([frame], "[M0] jd probe 1") is not None


def test_jd_ws_echo_frame_ignores_noise_and_others():
    other = _jd_send_frame("别人的弹幕", nick="路人")
    assert jd_ws_echo_frame([other, None, "garbage", 42], "[M0] jd probe 1") is None
    assert jd_ws_echo_frame([], "x") is None


def test_jd_ws_echo_frame_ignores_non_send_business():
    stats = json.dumps({"type": "chat_group_message",
                        "body": {"type": "get_statistics_result",
                                 "current_viewer": 100}})
    # content 恰好同文但非 viewer_send_message——不算回显
    stats2 = json.dumps({"type": "chat_group_message",
                         "body": {"type": "get_statistics_result",
                                  "content": "[M0] jd probe 1"}})
    assert jd_ws_echo_frame([stats, stats2], "[M0] jd probe 1") is None


# ---- 基类公共件（F2 上收 + cookie 判登录）----

def test_f2_and_bg_args_on_base():
    assert ControlledPageEngine._send_active is False
    assert ControlledPageEngine._listen_ctx is None
    assert SEND_BG_EXTRA_ARGS == ["--headless=new", "--mute-audio"]


@pytest.mark.asyncio
async def test_ctx_has_login_jd_cookie_names(tmp_path):
    # 2026-10-10 磁盘取证：现代京东登录 = thor/pin（pt_key/pt_pin 老体系从未出现）
    eng = _engine(tmp_path)
    assert await eng._ctx_has_login(_FakeCtx([_cookie("thor", "t")])) is True
    assert await eng._ctx_has_login(_FakeCtx([_cookie("pin", "p")])) is True
    assert await eng._ctx_has_login(_FakeCtx([_cookie("pt_key", "k")])) is False
    assert await eng._ctx_has_login(_FakeCtx([_cookie("a1", "x")])) is False


@pytest.mark.asyncio
async def test_close_listen_ctx_none_safe(tmp_path):
    eng = _engine(tmp_path)
    eng._listen_ctx = None
    await eng._close_listen_ctx()  # 不抛
    assert eng._listen_ctx is None


# ---- F4 自发声回环 ----

def _capturing_engine(tmp_path):
    eng = _engine(tmp_path)
    captured: list = []

    async def _fake_emit(msg):
        captured.append(msg)

    eng._emit_message = _fake_emit
    eng.mark_received = lambda *a, **k: None
    return eng, captured


@pytest.mark.asyncio
async def test_emit_self_echo_injects_danmu_envelope(tmp_path):
    eng, captured = _capturing_engine(tmp_path)
    frame = json.loads(_jd_send_frame("你好京东"))
    await eng._emit_self_echo("48511841", frame)
    assert len(captured) == 1
    env = captured[0]
    assert env["type"] == "DANMU"
    assert env["payload"]["content"] == "你好京东"
    assert eng._self_echo_mark is not None


@pytest.mark.asyncio
async def test_listener_dedups_recent_self_echo(tmp_path):
    import time as _time
    eng, captured = _capturing_engine(tmp_path)
    eng._self_echo_mark = ("你好京东", _time.monotonic())
    await eng._on_ws_frame("48511841", {"payload": _jd_send_frame("你好京东")})
    assert captured == []           # 发送侧已注入——监听侧同帧跳过
    assert eng._self_echo_mark is None

    eng._self_echo_mark = ("别的", _time.monotonic() - 30)
    await eng._on_ws_frame("48511841", {"payload": _jd_send_frame("你好京东")})
    assert len(captured) == 1       # 窗口外照常 emit
