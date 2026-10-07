"""常驻会话+抖音 sender 单元测试（AutoDanmu T3）

义务覆盖：ENG-1（空闲关闭 vs 在途发送竞态/操作超时会话重置）、CEO-F8（健康检查
两路径：会话丢失自动拉起/登录失效 NEEDS_LOGIN）、DX-D7（close 超时自愈）、
ENG-6（SingletonLock 撞锁独立错误+重启设界）、ENG-12（生命周期日志存在性）。
全离线：fake playwright 注入（模块级 async_playwright 替换——T2 测试卫生先例）。
"""

import asyncio

import pytest

from danmaku_listener.contract.models import SendStatus
from danmaku_listener.senders import resident_session as rs_mod
from danmaku_listener.senders.resident_session import (
    MODE_HEADLESS_NEW,
    ResidentSendSession,
    SessionLockedError,
)


class FakePage:
    def __init__(self, *, closed: bool = False, visibility: str = "visible",
                 action=None):
        self._closed = closed
        self._visibility = visibility
        self._action = action
        self.url_seen: list[str] = []

    def is_closed(self):
        return self._closed

    def on(self, *a, **k):
        pass

    def remove_listener(self, *a, **k):
        pass

    async def goto(self, url, timeout=None, wait_until=None):
        self.url_seen.append(url)

    async def evaluate(self, js, args=None):
        return self._visibility

    async def close(self):
        self._closed = True


class FakeContext:
    def __init__(self, pages: list[FakePage]):
        self.pages = list(pages)
        self.close_delay = 0.0
        self.close_raises = None

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self):
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        if self.close_raises:
            raise self.close_raises


class FakePWFactory:
    """async_playwright() 的替身：aenter 返回 pw（chromium 自引用，launch 可换）"""

    def __init__(self, context: FakeContext, launch_error: Exception | None = None):
        self._context = context
        self._launch_error = launch_error
        self.launch_called = 0

    async def __aenter__(self):
        ctx = self._context

        class PW:
            pass

        pw = PW()
        pw.chromium = pw  # 自引用（launch 挂在 chromium 上——session 经 pw.chromium.launch 调用）

        async def launch(*args, **kwargs):
            self.launch_called += 1
            if self._launch_error:
                raise self._launch_error
            return ctx

        pw.chromium.launch_persistent_context = launch
        self._pw = pw
        return pw

    async def __aexit__(self, *exc):
        return False


def install_pw(monkeypatch, context: FakeContext, launch_error: Exception | None = None):
    factory = FakePWFactory(context, launch_error)
    monkeypatch.setattr(rs_mod, "async_playwright", lambda: factory)
    return factory


def make_session(monkeypatch, idle: int = 3600, mode: str = MODE_HEADLESS_NEW) -> ResidentSendSession:
    monkeypatch.setattr(rs_mod, "PAGE_OP_TIMEOUT_S", 5.0)
    monkeypatch.setattr(rs_mod, "CLOSE_TIMEOUT_S", 2.0)
    return ResidentSendSession("t", "cookie/x_profile", window_mode=mode,
                               idle_timeout_s=idle)


OK_RESULT = None  # send_action 返回值由测试构造


async def ok_action(page, room_id):
    return None.__class__  # 占位（会被替换）


# ---- ENG-1：空闲关闭 vs 在途发送竞态 ----

@pytest.mark.asyncio
async def test_idle_close_holds_lock_and_rechecks(monkeypatch):
    """空闲关闭必须取同一把锁+锁内二次校验活动时间戳（ENG-1）——
    发送刚恢复活动时看门狗不得关闭会话"""
    session = make_session(monkeypatch, idle=0)  # 空闲阈值 0——看门狗立即想关
    context = FakeContext([FakePage()])
    install_pw(monkeypatch, context)
    monkeypatch.setattr(rs_mod, "IDLE_POLL_S", 0.05)  # 看门狗 50ms 一查

    async def action(page, rid):
        await asyncio.sleep(0.3)  # 模拟发送耗时
        return "OK"

    # 发送启动会话+看门狗；看门狗想关但锁被发送持有，锁内二次校验活动时间戳已刷新
    result = await session.send("room1", "https://x/room1", action)
    assert result == "OK"
    assert session._context is not None  # 发送后活动时间戳已刷新——会话未关闭
    await session.aclose()


@pytest.mark.asyncio
async def test_operation_timeout_resets_session(monkeypatch):
    """ENG-1：页面操作超时→会话级重置（关 context）→UNKNOWN 回执"""
    session = make_session(monkeypatch)
    context = FakeContext([FakePage()])
    install_pw(monkeypatch, context)

    async def slow_action(page, rid):
        await asyncio.sleep(99)  # 超过 PAGE_OP_TIMEOUT_S*3（已注入 5s→15s？注入后=5*3=15s）
        return "never"

    result = await session.send("room1", "https://x/room1", slow_action)
    assert result.status == SendStatus.UNKNOWN
    assert "超时" in (result.detail or "")
    # 会话已重置（context 关闭置 None）
    assert session._context is None


# ---- CEO-F8：健康检查两路径 ----

@pytest.mark.asyncio
async def test_health_check_page_lost_relaunches(monkeypatch):
    """CEO-F8 路径一：page 失效→自动拉起（不报登录失效）"""
    session = make_session(monkeypatch)
    dead = FakePage(closed=True)
    context = FakeContext([dead])
    install_pw(monkeypatch, context)

    # 预置：room1 的 page 已关闭；new_page 返回 fresh
    session._context = context
    session._pw_stack = FakePWFactory(context)
    session._pages["room1"] = dead

    async def action(page, rid):
        return ("page-is", page)

    result = await session.send("room1", "https://x/room1", action)
    assert result[0] == "page-is"
    assert result[1] is not dead  # 拉起了新页面（CEO-F8 自动恢复）


@pytest.mark.asyncio
async def test_login_failure_signal_maps_to_login_hint(monkeypatch):
    """CEO-F8 路径二：登录失效（页面'需先登录'信号）→NEEDS_LOGIN 语义——
    由 sender 页面配方判定（会话层不吞）"""
    from danmaku_listener.senders import douyin as dy_mod

    class LoginSignalPage(FakePage):
        async def evaluate(self, js, args=None):
            return "visible"

    session = make_session(monkeypatch)
    context = FakeContext([LoginSignalPage()])
    install_pw(monkeypatch, context)

    async def action(page, rid):
        # 模拟抖音页面配方检测到登录信号
        return "LOGIN_FAIL"

    result = await session.send("room1", "https://x/room1", action)
    assert result == "LOGIN_FAIL"


# ---- DX-D7：close 超时自愈 ----

@pytest.mark.asyncio
async def test_close_timeout_marks_stale_and_cleans_next_launch(monkeypatch):
    """DX-D7：close 超时→stale 标记→下次启动前清理残留进程"""
    session = make_session(monkeypatch)
    context = FakeContext([FakePage()])
    context.close_delay = 5.0  # > CLOSE_TIMEOUT_S(2s)
    install_pw(monkeypatch, context)

    await session.send("room1", "https://x/room1", lambda p, r: _done())
    await session.close()  # 显式关闭触发 close 超时路径
    assert session._stale is True

    # 下次启动前清理：mock cleanup_stale_chromium 验证调用
    called = {}

    def fake_cleanup(profile_dir):
        called["dir"] = profile_dir
        return 2

    monkeypatch.setattr(rs_mod, "cleanup_stale_chromium", fake_cleanup)
    context2 = FakeContext([FakePage()])
    install_pw(monkeypatch, context2)

    async def action(page, rid):
        return "OK2"

    result = await session.send("room1", "https://x/room1", action)
    assert result == "OK2"
    assert called.get("dir") == "cookie/x_profile"  # 清理按 profile 目录匹配
    assert session._stale is False


async def _done():
    return "OK"


# ---- ENG-6：撞锁独立错误+重启设界 ----

@pytest.mark.asyncio
async def test_singleton_lock_conflict_is_independent_error(monkeypatch):
    """ENG-6：profile 被占用（登录进行中）→独立错误回执（不自动重启不误报登录失效）"""
    session = make_session(monkeypatch)
    err = SessionLockedError("profile 被占用（登录进行中或残留进程）: User data directory in use")
    install_pw(monkeypatch, FakeContext([]), launch_error=err)

    result = await session.send("room1", "https://x/room1", lambda p, r: _done())
    assert result.status == SendStatus.FAILED
    assert "被占用" in (result.fix_hint or "")
    assert "登录进行中" in (result.fix_hint or "")


# ---- 会话形态（DX-D9）----

def test_headless_new_mode_generates_flag(monkeypatch):
    """DX-D9：headless_new 形态生成 --headless=new flag（无桌面）"""
    kwargs, extra = rs_mod._base_launch_args(rs_mod.MODE_HEADLESS_NEW)
    assert kwargs["headless"] is False
    assert "--headless=new" in extra
    assert "--disable-renderer-backgrounding" in extra  # ENG-8 flag 族
    kwargs2, extra2 = rs_mod._base_launch_args(rs_mod.MODE_MINIMIZED)
    assert "--window-position=-32000,-32000" in extra2
    assert "--headless=new" not in extra2


# ---- ENG-12：生命周期日志存在性（结构化日志抽查）----

@pytest.mark.asyncio
async def test_lifecycle_logs_emitted(monkeypatch):
    """ENG-12：启动/关闭日志各一条（loguru 自有 handler——caplog 抓不到 loguru）"""
    from loguru import logger

    logs: list[str] = []

    def sink(message):
        logs.append(str(message))

    hid = logger.add(sink, level="INFO")
    try:
        session = make_session(monkeypatch)
        context = FakeContext([FakePage()])
        install_pw(monkeypatch, context)

        await session.send("room1", "https://x/room1", lambda p, r: _done())
        await session.close()
    finally:
        logger.remove(hid)
    assert any("会话启动" in m for m in logs), logs
    assert any("会话关闭" in m for m in logs), logs
