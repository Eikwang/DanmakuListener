"""TaobaoMtopSender 单元测试（AutoDanmu T2——ret 五路径映射 CEO-F4/DX-D5 + E5 锁纪律）

T1 判定形态：sender 经瞬态页 evaluate 调页面 mtop 库（页面 JS 现生成 bx-ua）——
本测试用 fake page/context/engine 全离线验证映射与锁行为，不触网。
"""

import asyncio

import pytest

from danmaku_listener.contract.models import SendStatus
from danmaku_listener.senders.taobao_mtop import TaobaoMtopSender, plan_slider_drag


class FakeLock:
    """可控 profile 锁：记录占用、可注入超时"""

    def __init__(self, held: bool = False):
        self._lock = asyncio.Lock()
        if held:
            self._lock._locked = True  # 模拟被监听长动作占用

    async def acquire(self):
        await self._lock.acquire()

    def release(self):
        self._lock.release()


class FakeEngine:
    """E5：引擎引用（锁+profile 目录+URL 模板）"""

    def __init__(self):
        self._profile_lock = FakeLock()
        self.LIVE_URL_TEMPLATE = "https://tbzb.taobao.com/live?liveId={live_id}"
        self._user_agent = lambda: "UA"  # noqa: E731

    def _profile_dir(self):
        return "cookie/taobao_profile"


class FakePage:
    """可控 page：预设 evaluate 返回序列 + 可选 request 流"""

    def __init__(self, evaluate_results: list, lib_ready: bool = True,
                 topic_requests: bool = True):
        self._results = list(evaluate_results)
        self._lib_ready = lib_ready
        self._topic_requests = topic_requests
        self._listeners = []

    def on(self, event, handler):
        self._listeners.append(handler)
        if self._topic_requests and event == "request":
            # 异步喂一条 iliad 请求（带 topic）——模拟页面加载请求流
            class Req:
                url = "https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.query.latest/1.0/?data=%7B%22topic%22%3A%22topic-abc-123%22%7D"
                post_data = None

            asyncio.get_event_loop().call_later(0.05, lambda: handler(Req()))

    def remove_listener(self, event, handler):
        pass

    async def goto(self, url, timeout=None, wait_until=None):
        return None

    async def evaluate(self, js, args=None):
        # 分流：发送调用（EVAL_SEND_JS 含 args.api）vs 库探测（EVAL_LIB_PROBE_JS）
        if "args.api" in js:
            if self._results:
                item = self._results.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            raise AssertionError("evaluate 结果耗尽")
        return self._lib_ready  # 库探测


class FakeContext:
    def __init__(self, page: FakePage):
        self._page = page

    @property
    def pages(self):
        return [self._page]

    async def cookies(self):
        # 登录门槛（2026-10-09）：默认已登录（unb 在）——登录门槛直通
        return [{"name": "unb", "value": "test-unb"}]

    async def close(self):
        pass


class FakePlaywright:
    def __init__(self, context: FakeContext):
        self.chromium = self
        self._context = context

    async def launch_persistent_context(self, *args, **kwargs):
        return self._context


def make_sender(monkeypatch, evaluate_results: list, lib_ready: bool = True,
                lock_held: bool = False) -> TaobaoMtopSender:
    import danmaku_listener.senders.taobao_mtop as mod
    # 等待预算注入（测试 20s 真等→1s）
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 1.0)
    sender = TaobaoMtopSender(FakeEngine())
    if lock_held:
        sender._engine._profile_lock = FakeLock(held=True)
    page = FakePage(evaluate_results, lib_ready=lib_ready)
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False

            return _Ctx()

    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    return sender


# ---- ret 五路径映射（CEO-F4/DX-D5）----

@pytest.mark.asyncio
async def test_ret_success_maps_to_sent(monkeypatch):
    sender = make_sender(monkeypatch, [{"ret": ["SUCCESS::调用成功"]}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.SENT
    assert result.sent_at is not None


@pytest.mark.asyncio
async def test_ret_risk_maps_to_platform_rejected_not_login(monkeypatch):
    """RGV587 风控——禁止误导重扫码（CEO-F4）"""
    sender = make_sender(monkeypatch, [{"ret": ["FAIL_SYS_USER_VALIDATE", "RGV587_ERROR::SM::哎哟喂"]}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "风控" in (result.fix_hint or "")
    assert "勿重扫码" in (result.fix_hint or "")  # 否定指令存在=不误导重扫码（CEO-F4）


@pytest.mark.asyncio
async def test_ret_session_expired_maps_to_login_hint(monkeypatch):
    sender = make_sender(monkeypatch, [{"ret": ["FAIL_SYS_SESSION_EXPIRED::会话过期"]}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "登录" in (result.fix_hint or "")


@pytest.mark.asyncio
async def test_ret_param_error_maps_to_param_hint(monkeypatch):
    sender = make_sender(monkeypatch, [{"ret": ["FAIL_SYS_PARAM_ILLEGAL::参数错误"]}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "参数" in (result.fix_hint or "")


@pytest.mark.asyncio
async def test_ret_unknown_passes_through_raw_code(monkeypatch):
    """未知 ret 保守 FAIL + 原始码透传 detail（DX-D5 路径五）"""
    sender = make_sender(monkeypatch, [{"ret": ["FAIL_WEIRD_CODE::莫名其妙"]}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "FAIL_WEIRD_CODE" in (result.detail or "")


# ---- 边界路径 ----

@pytest.mark.asyncio
async def test_mtop_lib_missing_maps_to_route_unverified(monkeypatch):
    sender = make_sender(monkeypatch, [], lib_ready=False)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert result.reason_code == "ROUTE_UNVERIFIED"


@pytest.mark.asyncio
async def test_rejected_without_ret_maps_to_platform_rejected(monkeypatch):
    """evaluate reject 且无 ret（T1 实测的 Page.evaluate: Object 形态）"""
    sender = make_sender(monkeypatch, [{"rejected": True, "ret": None, "detail": "Page.evaluate: Object"}])
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "Page.evaluate" in (result.detail or "")


@pytest.mark.asyncio
async def test_lock_timeout_returns_busy(monkeypatch):
    """S4-1：监听重登长动作不饿死发送——锁超时回执 busy"""
    sender = make_sender(monkeypatch, [], lock_held=True)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "busy" in (result.fix_hint or "")


@pytest.mark.asyncio
async def test_topic_not_found_fails_with_hint(monkeypatch):
    """页面无 iliad 请求（未开播）→ topic 锚定失败→FAIL+fix_hint"""
    sender = TaobaoMtopSender(FakeEngine())
    page = FakePage([], lib_ready=True, topic_requests=False)
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False

            return _Ctx()

    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "topic" in (result.fix_hint or "")


# ---- T2 修复回归（2026-10-08 验收战役 CEO-1/3；根因卡 m0-send-probe-cards.md:39）----

def test_stage_budget_sum_within_ceo1_cap():
    """预算 tripwire（CEO-1）：goto+topic+lib+eval 合计 ≤55s——前端 60s 中止内闭环"""
    from danmaku_listener.senders import taobao_mtop as mod
    total = mod.PAGE_TIMEOUT_MS / 1000 + mod.TOPIC_WAIT_S + mod.MTOP_LIB_WAIT_S + mod.EVAL_TIMEOUT_S
    assert total <= 55.0, f"阶段预算和 {total}s 超过 CEO-1 上限 55s（前端 60s 中止内须闭环）"


def test_eval_js_timeout_synced_below_python_cap():
    """JS mtop timeout（12s）须先于 Python wait_for（15s）落地——错误路径保留 ret 细节"""
    from danmaku_listener.senders import taobao_mtop as mod
    assert "timeout: 12000" in mod.EVAL_SEND_JS
    assert "15000" not in mod.EVAL_SEND_JS


def test_is_risk_signal_url_patterns():
    from danmaku_listener.senders.taobao_mtop import is_risk_signal_url
    assert is_risk_signal_url("https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.publish/1.0/_____tmd_____/report?x5secdata=xgba")
    assert is_risk_signal_url("https://cf.aliyun.com/nocaptcha/initialize.jsonp?a=X82Y")
    assert not is_risk_signal_url("https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.publish/1.0/?callback=cb")


class HangingSendPage(FakePage):
    """send evaluate 永不 settle（复现 x5sec noCaptcha promise 永挂形态）"""

    def __init__(self, response_urls=None):
        super().__init__([])
        self._response_urls = list(response_urls or [])

    async def evaluate(self, js, args=None):
        if "args.api" in js:
            await asyncio.sleep(3600)  # 永挂（由 EVAL_TIMEOUT_S 兜底）
        return self._lib_ready

    def on(self, event, handler):
        self._listeners.append(handler)
        if event == "request" and self._topic_requests:
            class Req:
                url = "https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.query.latest/1.0/?data=%7B%22topic%22%3A%22topic-abc-123%22%7D"
                post_data = None
            asyncio.get_event_loop().call_later(0.05, lambda: handler(Req()))
        elif event == "response" and self._response_urls:
            for u in self._response_urls:
                class Resp:
                    url = u
                asyncio.get_event_loop().call_later(0.05, lambda h=handler, r=Resp(): h(r))


@pytest.mark.asyncio
async def test_eval_no_settle_maps_to_unknown_send_timeout(monkeypatch):
    """T2 挂点兜底：页面 promise 未决（无风控信号）→ UNKNOWN/SEND_TIMEOUT 回执而非永挂"""
    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "EVAL_TIMEOUT_S", 0.2)
    sender = TaobaoMtopSender(FakeEngine())
    page = HangingSendPage()
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False
            return _Ctx()

    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.UNKNOWN
    assert result.reason_code == "SEND_TIMEOUT"


@pytest.mark.asyncio
async def test_x5sec_signal_maps_to_manual_verify_hint(monkeypatch):
    """T2 x5sec 检测：eval 窗口内网络层风控信号 → FAILED「验证待人工」而非 UNKNOWN"""
    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "EVAL_TIMEOUT_S", 0.5)
    sender = TaobaoMtopSender(FakeEngine())
    page = HangingSendPage(response_urls=[
        "https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.publish/1.0/_____tmd_____/report?x5secdata=xgba5f12",
        "https://cf.aliyun.com/nocaptcha/initialize.jsonp?a=X82Y",
    ])
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False
            return _Ctx()

    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert result.reason_code == "PLATFORM_REJECTED"
    assert "勿盲目重试" in (result.fix_hint or "")
    assert "x5sec" in (result.detail or "")


@pytest.mark.asyncio
async def test_playwright_launch_failure_returns_structured_receipt(monkeypatch):
    """T2 E5 隔离：launch 失败（profile 冲突等）→ 结构化 FAILED 回执而非异常穿透（500）"""
    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 1.0)
    sender = TaobaoMtopSender(FakeEngine())

    class BoomPWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    raise RuntimeError("Target closed: profile in use")

                async def __aexit__(self, *exc):
                    return False
            return _Ctx()

    monkeypatch.setattr(mod, "async_playwright", BoomPWModule.async_playwright, raising=False)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.FAILED
    assert "Target closed" in (result.detail or "")


@pytest.mark.asyncio
async def test_lib_probe_hang_is_bounded(monkeypatch):
    """评审 P1（父验证）：lib 探针 evaluate 冻结页永挂→锁泄漏——「全部 await 有界」不变量回归锁
    Value: protects=_wait_mtop_lib 单次探针有界且超时计为 lib 不可用; fails_when=探针裸 await 回归;
    why_new=既有测试只锁发送 evaluate 的超时，探针路径无覆盖; seam=none"""
    import danmaku_listener.senders.taobao_mtop as mod

    class FrozenProbePage(FakePage):
        async def evaluate(self, js, args=None):
            if "args.api" in js:
                return {"ret": ["SUCCESS::调用成功"]}
            await asyncio.sleep(3600)  # lib 探针永挂（冻结页形态）

    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 0.5)
    sender = TaobaoMtopSender(FakeEngine())
    page = FrozenProbePage([])
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False
            return _Ctx()

    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    result = await asyncio.wait_for(sender.send("3101430810353885", "[M0] t"), timeout=5)
    assert result.status == SendStatus.FAILED
    assert result.reason_code == "ROUTE_UNVERIFIED"
    assert not sender._engine._profile_lock._lock._locked  # 锁须已释放（挂起不得泄漏锁）


@pytest.mark.asyncio
async def test_benign_response_during_eval_timeout_stays_unknown(monkeypatch):
    """testing #3 负路径：eval 窗口内良性 publish 响应不得误报 x5sec 风控（误报会误导「勿盲目重试」处置）
    Value: protects=x5sec 门的零误报（良性 URL→UNKNOWN 而非 FAILED）; fails_when=门误判良性 URL;
    why_new=既有测试只覆盖风险信号正例，无良性反例; seam=none"""
    import danmaku_listener.senders.taobao_mtop as mod
    monkeypatch.setattr(mod, "TOPIC_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "MTOP_LIB_WAIT_S", 1.0)
    monkeypatch.setattr(mod, "EVAL_TIMEOUT_S", 0.2)
    sender = TaobaoMtopSender(FakeEngine())
    page = HangingSendPage(response_urls=[
        "https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.publish/1.0/?callback=cb",
    ])
    context = FakeContext(page)

    class FakePWModule:
        @staticmethod
        def async_playwright():
            class _Ctx:
                async def __aenter__(self):
                    return FakePlaywright(context)

                async def __aexit__(self, *exc):
                    return False
            return _Ctx()

    monkeypatch.setattr(mod, "async_playwright", FakePWModule.async_playwright, raising=False)
    result = await sender.send("3101430810353885", "[M0] t")
    assert result.status == SendStatus.UNKNOWN
    assert result.reason_code == "SEND_TIMEOUT"


# ---- 自动滑块轨迹规划（2026-10-10——~12h 周期性简单滑块，人味轨迹自动通过）----

import random


def test_plan_slider_drag_reaches_track_end_with_overshoot():
    plan = plan_slider_drag(300.0, 40.0, rng=random.Random(42))
    assert plan and len(plan) >= 24  # 步数足够细（匀速直线是风控拦截特征）
    xs = [s[0] for s in plan]
    distance = 300.0 - 40.0 + 2.0    # track - knob + 2px
    assert abs(xs[-1] - distance) < 1.0        # 终点回正到轨道末端
    assert max(xs) <= distance + 5.0 + 0.01    # 过冲上界 5px
    assert xs[0] > 0.0                          # 首步即有位移


def test_plan_slider_drag_total_duration_bounded():
    plan = plan_slider_drag(300.0, 40.0, rng=random.Random(7))
    total = sum(s[2] for s in plan)
    assert 800.0 <= total <= 1450.0   # 0.8~1.3s 基础 + 微停顿上界（二轮加时——首版偏快被判机器）
    assert all(0.0 < s[2] for s in plan)


def test_plan_slider_drag_deterministic_with_seed():
    a = plan_slider_drag(300.0, 40.0, rng=random.Random(3))
    b = plan_slider_drag(300.0, 40.0, rng=random.Random(3))
    assert a == b


def test_plan_slider_drag_min_distance_floor():
    plan = plan_slider_drag(100.0, 80.0, rng=random.Random(1))  # 轨道<knob→兜底 120px
    assert plan[-1][0] >= 119.0
