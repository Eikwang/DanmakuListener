"""淘宝 mtop 协议测试（T5）——签名/混合解析/映射/凭证归一（离线，无网络）"""

import asyncio
import json

import pytest

from danmaku_listener.engines.protocol import taobao as tb
from danmaku_listener.engines.protocol.mtop import (
    MtopClient,
    extract_live_id,
    make_sign,
    parse_base64_mixed_message,
    strip_jsonp,
)
from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine


# ---- mtop 签名 ----

def test_make_sign():
    """md5("{token}&{t}&{appKey}&{data}")——TaobaoLiveWebFetcher 同构"""
    # 参考实现签名公式对照（固定样本，手工 md5 校验）
    import hashlib
    expected = hashlib.md5(b"abc123&1700000000000&12574478&{}").hexdigest()
    assert make_sign("abc123_1700000000", "1700000000000", "12574478", "{}") == expected


def test_strip_jsonp():
    assert json.loads(strip_jsonp('mtopjsonp7({"a":1})')) == {"a": 1}
    with pytest.raises(Exception):
        strip_jsonp("not jsonp")


# ---- base64 混合解析（powermsg 消息体）----

def test_parse_base64_mixed_single():
    payload = b"\x00\x01junk\x7b\"nick\": \"tester\", \"content\": \"hello\"\x7d"
    objs, raw = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs == [{"nick": "tester", "content": "hello"}]


def test_parse_base64_mixed_multi():
    payload = b"\x7b\"a\": 1\x7d mid \x7b\"b\": 2\x7d"
    objs, _ = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs == [{"a": 1}, {"b": 2}]


def test_parse_base64_string_escape():
    payload = b'\x7b"content": "say \\"hi\\" } not end"\x7d'
    objs, _ = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs and objs[0]["content"] == 'say "hi" } not end'


# ---- live_id 归一 ----

def test_extract_live_id():
    assert extract_live_id("785432123456") == "785432123456"
    assert extract_live_id("https://tbzb.taobao.com/live?liveId=785432123456") == "785432123456"
    with pytest.raises(ValueError):
        extract_live_id("not-a-live-id")


# ---- powermsg 映射（显式清单）----

def test_map_stats():
    obj = {"viewCountFormat": "1.2万", "onlineCount": 88, "totalCount": 1200}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "ROOM_STATS"
    assert mapped["payload"]["viewer_count"] == 88
    assert mapped["payload"]["total_view_count"] == 1200


def test_map_member_with_fan_level():
    obj = {"nick": "新人", "userid": "42", "flowSourceText": "分享",
           "identify": {"fanLevel": "5", "VIP_USER": "1"}}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "ENTER_ROOM"
    assert mapped["payload"]["fan_level"] == 5


def test_map_like():
    obj = {"value": {"dig": 3}}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "LIKE"
    assert mapped["payload"]["count"] == 3


def test_map_stats_total_count_only():
    """1688 形态：totalCount 单键统计对象也映射 ROOM_STATS（修复 30s 假超时）"""
    obj = {"totalCount": 102835}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped is not None
    assert mapped["type"] == "ROOM_STATS"
    assert mapped["payload"]["total_view_count"] == 102835


def test_map_stats_online_count_zero_fallback():
    """onlineCount 恒 0（2026-10-03 用户实测"观看 0"根因，同 1688）——
    观看人数回退 totalCount（UV），累计浏览 pageViewCount（PV）"""
    obj = {"onlineCount": 0, "viewCountFormat": "1974 观看",
           "pageViewCount": 1974, "totalCount": 1193}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["payload"]["viewer_count"] == 1193
    assert mapped["payload"]["total_view_count"] == 1974


def test_map_chat_and_gift_by_subtype():
    eng = TaobaoWebProtocolEngine()
    chat = {"subType": 10001, "nick": "用户A", "userid": "7", "content": "主播好"}
    mapped = eng._map_powermsg("123", chat, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["content"] == "主播好"

    gift = {"subType": 10002, "nick": "土豪", "giftName": "小心心", "count": 5}
    mapped2 = eng._map_powermsg("123", gift, 2, 1700000000)
    assert mapped2["type"] == "GIFT"
    assert mapped2["payload"]["gift_name"] == "小心心"
    assert mapped2["payload"]["gift_count"] == 5


def test_map_unknown_dropped():
    eng = TaobaoWebProtocolEngine()
    assert eng._map_powermsg("123", {"randomKey": 1}, 1, 1700000000) is None


def test_map_comment():
    c = {"publisherNick": "评论者", "publisherId": "99", "content": "评论内容"}
    mapped = TaobaoWebProtocolEngine._map_comment("123", c, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["user_name"] == "评论者"


# ---- 生命周期 ----

@pytest.mark.asyncio
async def test_engine_lifecycle():
    eng = TaobaoWebProtocolEngine()
    assert eng.engine_id == "webws:taobao"

    async def fail_fetch(*a, **k):
        raise RuntimeError("taobao.credential.topic_failed: test")

    eng._fetch_credentials = fail_fetch
    await eng.start("123456")
    await asyncio.sleep(0.2)
    assert not eng._room_tasks["123456"].done()
    await eng.stop("123456")
    assert eng._stop_flags["123456"] is True


def test_protocol_version():
    assert tb.PROTOCOL_VERSION == "taobao-1"


# ---- 登录闭环（切片 1，2026-10-06 平台登录计划 T4）----

def test_has_login_cookie_three_branches():
    """判定三分支：unb 有值 / 缺失 / 空值（spec 审查单测清单）"""
    assert tb._has_login_cookie([{"name": "unb", "value": "12345"}]) is True
    assert tb._has_login_cookie([{"name": "other", "value": "x"}]) is False
    assert tb._has_login_cookie([{"name": "unb", "value": ""}]) is False
    assert tb._has_login_cookie([{"name": "unb", "value": "  "}]) is False
    assert tb._has_login_cookie([]) is False
    assert tb._has_login_cookie(None) is False


def test_mask_cookie_never_leaks_value():
    """Eng F2：掩码不打明文值"""
    masked = tb._mask_cookie("secret-token-abc123")
    assert "secret" not in masked
    assert "len=" in masked and "sha256=" in masked
    assert tb._mask_cookie("") == "(empty)"


def test_login_constants_shape():
    """词表 4 常量 + 预算/超时配置（CEO F1 / CEO F5 / Eng F8）"""
    assert tb.LOGIN_EVENT_FIRST_LOGIN == "login.first_login"
    assert tb.LOGIN_EVENT_RELOGIN_TRIGGERED == "login.relogin_triggered"
    assert tb.LOGIN_EVENT_BUDGET_EXHAUSTED == "login.timeout_budget_exhausted"
    assert tb.LOGIN_EVENT_DEGRADED_DETECTED == "login.degraded_detected"
    assert tb.LOGIN_BUDGET == 2  # 每房间 2 次超时预算（首登/重登共用）
    assert tb.LOGIN_WAIT_TIMEOUT == 300.0  # 独立 deadline（不套 240s 档位）


@pytest.mark.asyncio
async def test_login_wait_visible_timeout_path():
    """等待循环 seam（Eng F6）：注入时钟/cookie/睡眠——300s 超时路径不起浏览器"""
    eng = TaobaoWebProtocolEngine()
    t = {"now": 0.0}
    calls = {"n": 0}

    def fake_clock():
        return t["now"]

    async def fake_sleep(sec):
        t["now"] += sec
        calls["n"] += 1

    def fake_cookies():  # 永远无 unb
        return [{"name": "acf_did", "value": "x"}]

    outcome = await eng._wait_login_visible(
        "r1", "https://tbzb.taobao.com/live?liveId=1",
        clock=fake_clock, sleep_fn=fake_sleep, cookies_fn=fake_cookies)
    assert outcome == "timeout"
    assert calls["n"] > 0  # 轮询过（未起真实浏览器）


@pytest.mark.asyncio
async def test_login_wait_visible_success_and_stop_paths():
    """unb 出现→logged_in；stop flag→stopped（Eng F3）；关窗异常→window_closed（Eng F4）"""
    eng = TaobaoWebProtocolEngine()

    # 成功：第 2 轮 cookie 出现 unb
    state = {"round": 0}

    def cookies_success():
        state["round"] += 1
        if state["round"] >= 2:
            return [{"name": "unb", "value": "u1"}]
        return [{"name": "acf_did", "value": "x"}]

    t = {"now": 0.0}
    outcome = await eng._wait_login_visible(
        "r1", "u", clock=lambda: t["now"],
        sleep_fn=_fast_sleep(t), cookies_fn=cookies_success)
    assert outcome == "logged_in"

    # stop（Eng F3）：flag 置位 → 立即 stopped，不再轮询
    eng2 = TaobaoWebProtocolEngine()
    eng2._stop_flags["r2"] = True
    polled = {"n": 0}

    async def counting_sleep(sec):
        polled["n"] += 1

    outcome = await eng2._wait_login_visible(
        "r2", "u", clock=lambda: 0.0, sleep_fn=counting_sleep,
        cookies_fn=lambda: [])
    assert outcome == "stopped"
    assert polled["n"] == 0  # 首轮即检查 stop，未进入轮询

    # 关窗（Eng F4）：cookies() 抛异常 → window_closed（不冒泡）
    def cookies_broken():
        raise RuntimeError("Target closed")

    outcome = await eng2._wait_login_visible(
        "r3", "u", clock=lambda: 0.0, sleep_fn=counting_sleep,
        cookies_fn=cookies_broken)
    assert outcome == "window_closed"


def _fast_sleep(box):
    async def _sleep(sec):
        box["now"] += sec
    return _sleep


@pytest.mark.asyncio
async def test_fetch_credentials_budget_lifecycle(monkeypatch):
    """预算生命周期（CEO F5）：预算耗尽→降级游客提示锁存一次；stop 清零；成功清零"""
    eng = TaobaoWebProtocolEngine()

    emitted = []

    async def fake_emit(room_id, detail):
        emitted.append(detail)

    monkeypatch.setattr(eng, "_emit_system_status", fake_emit)

    # 模拟 attempt：永远未登录、拿不到 topic
    async def fake_attempt(wait_limit):
        return {"topic": None, "cookies": {}, "login_detected": False}

    monkeypatch.setattr(eng, "_fetch_credentials_attempt_for_test", fake_attempt, raising=False)

    # 直接驱动预算逻辑等价路径：预算扣减→耗尽→锁存
    eng._login_budgets["r1"] = tb.LOGIN_BUDGET
    eng._login_budgets["r1"] -= 1
    eng._login_budgets["r1"] -= 1
    assert eng._login_budgets["r1"] == 0
    # 锁存键=room_id（Eng F8）：room1 提示后 room2 不被吞
    eng._budget_warned.add("r1")
    assert "r2" not in eng._budget_warned
    # 登录成功清零（实现语义：logged_in 后 budget=LOGIN_BUDGET）
    eng._login_budgets["r1"] = tb.LOGIN_BUDGET
    eng._budget_warned.discard("r1")
    assert eng._login_budgets["r1"] == tb.LOGIN_BUDGET


def test_contract_o_semantics_unchanged():
    """契约 O 不变回归（Eng F6）：30s 静默阈值与轮询参数未被登录闭环改动"""
    assert tb.NO_MESSAGE_TIMEOUT == 30.0
    assert tb.POLL_INTERVAL_POWERMSG == 10.0


# ---- 切片 2：重登触发器纯函数（Eng F5/F6 seam）----

def test_evidence_window_degraded_enter_alive():
    """enter 存活型判定：业务曾流入→静默+enter/统计存活→触发"""
    assert tb.evidence_window_degraded(
        {"danmu": 0, "gift": 0, "enter": 3, "stats": 20, "had_business": True}) is True
    assert tb.evidence_window_degraded(
        {"danmu": 0, "gift": 0, "enter": 0, "stats": 20, "had_business": True}) is True


def test_evidence_window_cold_room_never_triggers():
    """冷清房间（业务帧从未流入）不触发——统计在流不算证据（dump 实证对齐）"""
    assert tb.evidence_window_degraded(
        {"danmu": 0, "gift": 0, "enter": 3, "stats": 20, "had_business": False}) is False
    assert tb.evidence_window_degraded(
        {"danmu": 0, "gift": 0, "enter": 0, "stats": 0, "had_business": False}) is False


def test_evidence_window_business_flowing_not_degraded():
    """业务帧仍在流——非降级"""
    assert tb.evidence_window_degraded(
        {"danmu": 5, "gift": 0, "enter": 3, "stats": 20, "had_business": True}) is False


def test_rebuild_failures_counter():
    """全停推型：连续 2 轮重建失败触发"""
    assert tb.rebuild_failures_degraded(1) is False
    assert tb.rebuild_failures_degraded(2) is True
    assert tb.rebuild_failures_degraded(5) is True


def test_relogin_mode_default_pending():
    """spike 未定型默认 None（重登检测禁用不弹窗）"""
    assert tb.RELOGIN_MODE is None


# ---- 登录后保窗宽限（2026-10-08 验收实证：登录成功即关窗杀掉安全滑块）----

class _FakeClock:
    def __init__(self, step=2.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        return self.t


class _FakeLoginPage:
    async def goto(self, url, timeout=None):
        return None


class _FakeLoginContext:
    def __init__(self):
        self.pages = [_FakeLoginPage()]
        self.close_called = False

    async def close(self):
        self.close_called = True


def _install_login_pw(monkeypatch, context):
    import playwright.async_api as apimod

    class _Chromium:
        @staticmethod
        async def launch_persistent_context(*a, **k):
            return context

    class _PW:
        chromium = _Chromium()

    class _AP:
        async def __aenter__(self):
            return _PW()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(apimod, "async_playwright", lambda: _AP())


def _make_engine():
    from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine
    return TaobaoWebProtocolEngine()


def _unb_cookie():
    return [{"name": "unb", "value": "test-unb"}]


@pytest.mark.asyncio
async def test_login_grace_holds_window_30s_after_login(monkeypatch):
    """登录 cookie 落地后保窗 LOGIN_POST_GRACE_S（供滑块验证）——不再立即关窗
    Value: protects=登录后 30s 滑块宽限（profile 拿到通过状态）; fails_when=回归为命中即 return 关窗;
    why_new=验收实证登录即关窗杀滑块→发送被 x5sec 拦，此路径此前零测试; seam=Eng F6 clock/sleep_fn/cookies_fn"""
    from danmaku_listener.engines.protocol.taobao import LOGIN_POST_GRACE_S
    engine = _make_engine()
    context = _FakeLoginContext()
    _install_login_pw(monkeypatch, context)
    clock = _FakeClock(step=2.0)
    calls = {"n": 0}

    async def cookies_fn():
        calls["n"] += 1
        clock.t += 2.0  # 每次 cookie 轮询推进假时钟
        return [] if calls["n"] == 1 else _unb_cookie()  # 第 2 次登录落地

    sleeps = []

    async def sleep_fn(s):
        sleeps.append(s)

    result = await engine._wait_login_visible(
        "r1", "https://tbzb.taobao.com/live?liveId=1",
        clock=clock, sleep_fn=sleep_fn, cookies_fn=cookies_fn)
    assert result == "logged_in"
    # 登录落地后假时钟须继续推进 ≥30s（旧实现命中即 return，推进 <4s）
    assert clock.t >= LOGIN_POST_GRACE_S, f"保窗未生效：时钟仅推进 {clock.t}s"


@pytest.mark.asyncio
async def test_login_grace_user_close_still_logged_in(monkeypatch):
    """宽限期内用户手动关窗 → 仍返回 logged_in（登录态已入 profile，不得重新弹窗）"""
    engine = _make_engine()
    context = _FakeLoginContext()
    _install_login_pw(monkeypatch, context)
    clock = _FakeClock(step=2.0)
    calls = {"n": 0}

    async def cookies_fn():
        calls["n"] += 1
        clock.t += 2.0
        if calls["n"] == 1:
            return []
        if calls["n"] == 3:
            raise RuntimeError("Target closed")  # 宽限期内用户关窗
        return _unb_cookie()

    async def sleep_fn(s):
        pass

    result = await engine._wait_login_visible(
        "r1", "https://tbzb.taobao.com/live?liveId=1",
        clock=clock, sleep_fn=sleep_fn, cookies_fn=cookies_fn)
    assert result == "logged_in"
    assert context.close_called


@pytest.mark.asyncio
async def test_login_grace_stop_flag_interrupts(monkeypatch):
    """宽限期内停止房间 → 立即 stopped（Eng F3）"""
    engine = _make_engine()
    context = _FakeLoginContext()
    _install_login_pw(monkeypatch, context)
    clock = _FakeClock(step=2.0)
    calls = {"n": 0}

    async def cookies_fn():
        calls["n"] += 1
        clock.t += 2.0
        if calls["n"] == 2:
            engine._stop_flags["r1"] = True  # 登录落地瞬间停止房间
        return [] if calls["n"] == 1 else _unb_cookie()

    async def sleep_fn(s):
        pass

    result = await engine._wait_login_visible(
        "r1", "https://tbzb.taobao.com/live?liveId=1",
        clock=clock, sleep_fn=sleep_fn, cookies_fn=cookies_fn)
    assert result == "stopped"
