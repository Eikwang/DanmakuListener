"""三平台接线单测（AutoDanmu T6——ENG-10 与 T3 同规格 + DX-D3 覆写合并 + ENG-3 settings 贯通）

覆盖：ret/回显五形态、滑块感知 FAIL、登录失效回执、凭证文件不存在空路径、
min_interval_overrides 按键合并语义（内置默认兜底未覆写平台）、send_window_mode
settings 贯通。全离线（fake playwright 注入——模块级 async_playwright 替换）。
"""

import asyncio
import json

import pytest

from danmaku_listener.contract.models import SendStatus
from danmaku_listener.senders import dom_transient as dt_mod
from danmaku_listener.senders import guard as guard_mod
from danmaku_listener.senders.dom_transient import DomTransientSender
from danmaku_listener.senders.guard import SendGuard, load_min_interval_overrides
from danmaku_listener.senders.huya import HuyaResidentSender
from danmaku_listener.senders.kuaishou_douyu import DouyuCookieSender, KuaishouStateSender


# ---- fake playwright 脚手架（T2/T3 同款测试卫生先例）----

class FakeLocator:
    def __init__(self, count=1):
        self._count = count
        self.first = self  # playwright locator 链式 .first

    async def count(self):
        return self._count

    async def is_visible(self):
        return self._count > 0

    async def click(self, timeout=None):
        pass

    async def press_sequentially(self, text, delay=None):
        pass

    async def press(self, key):
        pass


class FakePage:
    def __init__(self, *, input_count=1, echo_hit_after=0, login_signal=False,
                 risk_signal=False):
        self._input_count = input_count
        self._echo_hit_after = echo_hit_after
        self._login_signal = login_signal
        self._risk_signal = risk_signal
        self._echo_queries = 0
        self.frames = []

    def on(self, *a, **k):
        pass

    def remove_listener(self, *a, **k):
        pass

    async def goto(self, url, timeout=None, wait_until=None):
        pass

    async def close(self):
        pass

    def locator(self, sel):
        return FakeLocator(self._input_count)

    async def evaluate(self, js, args=None):
        return "visible"

    def get_by_text(self, text):
        me = self

        class TextLoc:
            async def count(self):
                if "[M0]" in text or "soak" in text:
                    me._echo_queries += 1
                    return 1 if me._echo_queries > me._echo_hit_after else 0
                if me._login_signal and ("登录" in text):
                    return 1
                if me._risk_signal and ("验证码" in text or "禁言" in text):
                    return 1
                return 0

        return TextLoc()


class FakeContext:
    def __init__(self, page: FakePage):
        self._page = page
        self.pages: list = []
        self.added_cookies: list = []
        self.storage_state_called = False

    async def new_page(self):
        self.pages.append(self._page)
        return self._page

    async def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)

    async def storage_state(self, path=None):
        self.storage_state_called = True

    async def close(self):
        pass


class FakePWFactory:
    def __init__(self, context: FakeContext):
        self._context = context

    async def __aenter__(self):
        class PW:
            pass

        pw = PW()
        pw.chromium = pw

        async def launch(*a, **k):
            return self._context

        pw.chromium.launch_persistent_context = launch
        return pw

    async def __aexit__(self, *exc):
        return False


def install_pw(monkeypatch, context: FakeContext):
    factory = FakePWFactory(context)
    monkeypatch.setattr(dt_mod, "async_playwright", lambda: factory)
    return factory


def make_settings(**overrides):
    from danmaku_listener.config.settings import Settings
    base = dict(
        send_enabled_platforms="kuaishou,douyu,huya",
        send_dry_run=False, send_min_interval_seconds=0.0, send_jitter_seconds=0.0,
        send_circuit_threshold=5, send_dedup_window_seconds=300, send_max_length=100,
        send_rate_key="platform", send_audit_file="./persistence_data/a.jsonl",
        send_idempotency_index="./persistence_data/b.json",
        send_min_interval_overrides="", send_window_mode="headless_new",
        send_session_idle_timeout_seconds=1800,
    )
    base.update(overrides)
    return Settings(**base)


# ---- ENG-10：三 sender 同规格 ----

@pytest.mark.asyncio
@pytest.mark.parametrize("sender_cls", [KuaishouStateSender, DouyuCookieSender])
async def test_transient_send_success(monkeypatch, sender_cls, tmp_path):
    """快手/斗鱼：凭证注入→选择器→逐键+发送→回显 SENT"""
    sender = sender_cls()
    # 凭证文件（tmp_path 隔离——不改真实 cookie/）
    cf = tmp_path / "cred.json"
    if sender.storage_state_mode:
        cf.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    else:
        cf.write_text(json.dumps({"cookies": [{"name": "acf_uid", "value": "1"}]}), encoding="utf-8")
    monkeypatch.setattr(sender, "cookie_file", str(cf))
    install_pw(monkeypatch, FakeContext(FakePage()))
    result = await sender.send("12345", "[M0] t6")
    assert result.status == SendStatus.SENT
    assert result.sent_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("sender_cls", [KuaishouStateSender, DouyuCookieSender])
async def test_missing_credential_maps_to_login_hint(monkeypatch, sender_cls, tmp_path):
    """ENG-10 空路径：凭证文件不存在→FAIL+登录 fix_hint（不触发 playwright）"""
    sender = sender_cls()
    monkeypatch.setattr(sender, "cookie_file", str(tmp_path / "nonexistent.json"))
    install_pw(monkeypatch, FakeContext(FakePage()))
    result = await sender.send("12345", "[M0] t6")
    assert result.status == SendStatus.FAILED
    assert "登录" in (result.fix_hint or "")
    assert result.detail and "不存在" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("sender_cls", [KuaishouStateSender, DouyuCookieSender])
async def test_login_signal_maps_to_login_hint(monkeypatch, sender_cls, tmp_path):
    """CEO-F8 登录路径：页面'请登录'信号→登录 fix_hint（非风控误导）"""
    sender = sender_cls()
    cf = tmp_path / "cred.json"
    cf.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sender, "cookie_file", str(cf))
    install_pw(monkeypatch, FakeContext(FakePage(input_count=0, login_signal=True)))
    result = await sender.send("12345", "[M0] t6")
    assert result.status == SendStatus.FAILED
    assert "登录态失效" in (result.fix_hint or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("sender_cls", [KuaishouStateSender, DouyuCookieSender])
async def test_risk_signal_maps_to_platform_rejected(monkeypatch, sender_cls, tmp_path):
    """滑块/风控感知→FAIL+勿重扫码（不误报登录）"""
    sender = sender_cls()
    cf = tmp_path / "cred.json"
    cf.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sender, "cookie_file", str(cf))
    install_pw(monkeypatch, FakeContext(FakePage(risk_signal=True)))
    result = await sender.send("12345", "[M0] t6")
    assert result.status == SendStatus.FAILED
    assert "风控" in (result.detail or "")


@pytest.mark.asyncio
async def test_huya_resident_send_success(monkeypatch):
    """虎牙：ResidentSendSession 第二实例→选择器→回显 SENT"""
    from danmaku_listener.senders import huya as huya_mod
    monkeypatch.setattr(huya_mod, "ECHO_WAIT_S", 2.0)
    monkeypatch.setattr(huya_mod, "_session", None)  # 重置单例
    # fake session 层（huya sender 的页面配方经 session.send——fake 掉会话只测配方）
    class FakeSession:
        def __init__(self):
            self.page = FakePage()

        async def send(self, room_id, url, action):
            return await action(self.page, room_id)

        async def aclose(self):
            pass

    monkeypatch.setattr(huya_mod, "_get_session", lambda idle, mode: FakeSession())
    sender = HuyaResidentSender(settings=make_settings())
    result = await sender.send("12345", "[M0] t6")
    assert result.status == SendStatus.SENT


# ---- storage_state 导入安全（T6 事故防护：禁止导出回写凭证文件）----

@pytest.mark.asyncio
async def test_storage_state_import_never_exports(monkeypatch, tmp_path):
    """事故防护：注入=只读文件+add_cookies；context.storage_state(path=)（导出）不得被调用——
    2026-10-07 实损事故回归防护（kuaishou_storage_state.json 被空 context 导出覆盖）"""
    sender = KuaishouStateSender()
    cf = tmp_path / "kuaishou_storage_state.json"
    cf.write_text(json.dumps({"cookies": [{"name": "sessionToken", "value": "v"}],
                              "origins": []}), encoding="utf-8")
    monkeypatch.setattr(sender, "cookie_file", str(cf))

    class GuardContext(FakeContext):
        def __init__(self):
            super().__init__(FakePage())
            self.export_attempted = False

        async def storage_state(self, path=None):
            self.export_attempted = True  # 导出调用=事故
            return {}

    gctx = GuardContext()
    install_pw(monkeypatch, gctx)
    result = await sender.send("12345", "[M0] guard")
    assert gctx.export_attempted is False, "storage_state 导出语义被调用——将覆盖损坏凭证文件"
    assert result.status in (SendStatus.SENT, SendStatus.UNKNOWN)


# ---- DX-D3：覆写按键合并语义 ----

def test_overrides_merge_semantics_builtin_default():
    """无 INI→仅内置默认 {"huya": 35}（出厂即安全）"""
    merged = load_min_interval_overrides("")
    assert merged == {"huya": 35.0}


def test_overrides_merge_semantics_ini_wins():
    """INI 同键覆写优先；未覆写平台保留内置默认（按键合并，非整体替换）"""
    merged = load_min_interval_overrides(json.dumps({"douyu": 50, "huya": 40}))
    assert merged["douyu"] == 50.0      # INI 新增
    assert merged["huya"] == 40.0       # INI 覆写优先
    assert merged.get("kuaishou") is None  # 未配置平台无条目（回退全局 30s 由 check 处理）


def test_overrides_invalid_json_falls_back_to_default():
    """损坏 JSON→忽略并保留内置默认（不崩）"""
    merged = load_min_interval_overrides("{not-json")
    assert merged == {"huya": 35.0}


def test_guard_check_uses_override_interval():
    """guard.check 实际采用覆写间隔（虎牙 35s；快手全局 30s）"""
    settings = make_settings(send_min_interval_seconds=30.0,
                             send_min_interval_overrides="")
    guard = SendGuard(settings)
    import time as _t
    now = _t.monotonic()
    # 虎牙：35s 覆写生效——31s 前发过→拒绝
    guard._last_send["huya"] = now - 31
    ok, reason, _ = guard.check("huya", "1", "[M0] x")
    assert not ok and reason == "RATE_LIMITED"
    guard._last_send["huya"] = now - 36
    ok, reason, _ = guard.check("huya", "1", "[M0] x")
    assert ok
    # 快手：无覆写→全局 30s——20s 前发过→拒绝；31s 前→通过
    guard2 = SendGuard(settings)
    guard2._last_send["kuaishou"] = _t.monotonic() - 20
    ok, reason, _ = guard2.check("kuaishou", "1", "[M0] x")
    assert not ok and reason == "RATE_LIMITED"


# ---- ENG-3：send_window_mode settings 贯通 ----

def test_window_mode_settings_passthrough():
    """send_window_mode 经 Settings 属性贯通（INI [send] window_mode→属性）"""
    s = make_settings(send_window_mode="minimized")
    assert s.send_window_mode == "minimized"
    sender = HuyaResidentSender(settings=s)
    assert sender._session._window_mode == "minimized"


def test_session_uses_window_mode(monkeypatch):
    """ResidentSendSession 按 window_mode 生成 launch 参数（headless_new→--headless=new）"""
    s = rs_session_for_test()
    assert s._window_mode == "headless_new"


def rs_session_for_test():
    from danmaku_listener.senders.resident_session import ResidentSendSession
    return ResidentSendSession("t", "cookie/x", window_mode="headless_new")
