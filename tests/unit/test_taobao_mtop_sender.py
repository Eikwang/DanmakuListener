"""TaobaoMtopSender 单元测试（AutoDanmu T2——ret 五路径映射 CEO-F4/DX-D5 + E5 锁纪律）

T1 判定形态：sender 经瞬态页 evaluate 调页面 mtop 库（页面 JS 现生成 bx-ua）——
本测试用 fake page/context/engine 全离线验证映射与锁行为，不触网。
"""

import asyncio

import pytest

from danmaku_listener.contract.models import SendStatus
from danmaku_listener.senders.taobao_mtop import TaobaoMtopSender


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
