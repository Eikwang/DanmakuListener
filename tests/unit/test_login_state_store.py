"""F1 登录态快照共享层 + 虎牙无感会话接线 单元测试（2026-10-10 XHS 经验移植回归）

探针实证背景（cards/xhs-persist-*、cards/huya-bg-*）：
- huya yyuid 为持久 cookie（监听侧文件至 2026-10-24）——"会话级"误判废除
- huya_login_profile 目录从未存在（发送侧登录从未落盘）——快照恢复补链
- headless=new + STEALTH_JS（7 信号伪装）+ 登录态：实发回显命中——
  10-09"headless 被吞"回退的混杂因素（缺 stealth 接线 + 登录态）复查通过
- #UDBSdkLgn-mask 节点 DOM 常驻：count 判定假阳性，须可见性判定
"""
import json

import pytest

from danmaku_listener.engines import login_state_store
from danmaku_listener.senders import huya as huya_mod
from danmaku_listener.senders.huya import HuyaResidentSender, STEALTH_JS
from danmaku_listener.senders.resident_session import (
    MODE_HEADLESS_NEW,
    ResidentSendSession,
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
    return {"name": name, "value": value, "domain": ".huya.com", "path": "/"}


NAMES = ("yyuid", "hicl_imid", "huya_uid")


# ---- login_state_store 共享层 ----

@pytest.mark.asyncio
async def test_store_snapshot_only_with_login_cookie(tmp_path):
    path = str(tmp_path / "huya_login_profile_login_state.json")
    guest = _FakeCtx([_cookie("huya_uid_decoy")])
    assert await login_state_store.snapshot_login_state(
        guest, names=NAMES, path=path, label="t") is False
    logged = _FakeCtx([_cookie("yyuid", "u123"), _cookie("a1", "x")])
    assert await login_state_store.snapshot_login_state(
        logged, names=NAMES, path=path, label="t") is True
    state = json.loads((tmp_path / "huya_login_profile_login_state.json")
                       .read_text(encoding="utf-8"))
    assert any(c["name"] == "yyuid" for c in state["cookies"])


@pytest.mark.asyncio
async def test_store_restore_injects_when_profile_lost_login(tmp_path):
    path = str(tmp_path / "p_login_state.json")
    (tmp_path / "p_login_state.json").write_text(
        json.dumps({"cookies": [_cookie("yyuid", "snap"), _cookie("a1", "x")]}),
        encoding="utf-8")
    ctx = _FakeCtx([])  # 空 profile（huya_login_profile 现状——从未落盘）
    assert await login_state_store.restore_login_state(
        ctx, names=NAMES, path=path, label="t") is True
    assert {c["name"] for c in ctx.added[0]} == {"yyuid", "a1"}


@pytest.mark.asyncio
async def test_store_restore_skipped_when_profile_logged_in(tmp_path):
    path = str(tmp_path / "p_login_state.json")
    (tmp_path / "p_login_state.json").write_text(
        json.dumps({"cookies": [_cookie("yyuid", "snap")]}), encoding="utf-8")
    ctx = _FakeCtx([_cookie("huya_uid", "profile")])
    assert await login_state_store.restore_login_state(
        ctx, names=NAMES, path=path, label="t") is False
    assert ctx.added == []


# ---- ResidentSendSession F1 接线 ----

def _session(tmp_path, **kw) -> ResidentSendSession:
    return ResidentSendSession("t", str(tmp_path / "huya_login_profile"),
                               login_cookie_names=NAMES, **kw)


@pytest.mark.asyncio
async def test_session_restore_delegates_with_names(tmp_path):
    s = _session(tmp_path)
    (tmp_path / "huya_login_profile_login_state.json").write_text(
        json.dumps({"cookies": [_cookie("yyuid", "snap")]}), encoding="utf-8")
    ctx = _FakeCtx([])
    assert await s._restore_login(ctx) is True
    assert len(ctx.added) == 1


@pytest.mark.asyncio
async def test_session_snapshot_uses_live_context(tmp_path):
    s = _session(tmp_path)
    s._context = _FakeCtx([_cookie("hicl_imid", "i1")])
    assert await s._snapshot_login() is True
    state = json.loads(
        (tmp_path / "huya_login_profile_login_state.json").read_text(encoding="utf-8"))
    assert any(c["name"] == "hicl_imid" for c in state["cookies"])


@pytest.mark.asyncio
async def test_session_f1_disabled_without_names(tmp_path):
    s = ResidentSendSession("t", str(tmp_path / "p"))  # 未传 login_cookie_names
    ctx = _FakeCtx([])
    assert await s._restore_login(ctx) is False
    assert await s._snapshot_login() is False


# ---- 虎牙 sender 接线（纯后台默认 + stealth + F1 cookie 名）----

def test_huya_sender_wiring(monkeypatch):
    monkeypatch.setattr(huya_mod, "_session", None)  # 重置单例
    sender = HuyaResidentSender(None)
    s = sender._session
    assert s._window_mode == MODE_HEADLESS_NEW  # 纯后台默认（用户验收后终态）
    assert s._init_scripts == [f"({STEALTH_JS})()"]  # stealth 接线（备而未接 → 实接）
    assert s._login_cookie_names == ("yyuid", "hicl_imid", "huya_uid")
    assert s._login_state_path == "cookie/huya_login_profile_login_state.json"
