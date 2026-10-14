"""虎牙发送侧一次登录两态齐单测（2026-10-13 用户验收裁定——一次登录门配套）

覆盖 senders/huya.py 存档导出与 takeover 包装：
- export_huya_archive：huya 域过滤+原子落盘 / 无登录 cookie→False / context 异常→False
- takeover_login_and_archive：login_takeover 异常包装→False（不外抛）
全离线（fake context；cookie_dir 指向 tmp_path——不改真实 cookie/）。
"""

import json

import pytest

from danmaku_listener.senders.huya import export_huya_archive, takeover_login_and_archive
from danmaku_listener.senders.resident_session import LoginTakeoverError


class FakeCookieContext:
    """cookies() 形态 context（export_huya_archive 只消费这一个接口）"""

    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies


class BoomContext:
    async def cookies(self):
        raise RuntimeError("context crashed")


def _patch_cookie_dir(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import danmaku_listener.config.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings",
                        lambda: SimpleNamespace(cookie_dir=str(tmp_path)))


# ---- export_huya_archive ----

@pytest.mark.asyncio
async def test_export_huya_archive_filters_huya_domain_and_atomic_write(monkeypatch, tmp_path):
    """huya 域过滤：留 huya 域有值 cookie（含非登录名）；剔非 huya 域/空值；
    tmp+os.replace 原子落盘（无 .tmp 残留）"""
    _patch_cookie_dir(monkeypatch, tmp_path)
    cookies = [
        {"name": "yyuid", "value": "u1", "domain": ".huya.com"},
        {"name": "traceid", "value": "t1", "domain": "www.huya.com"},  # huya 域非登录名——保留
        {"name": "yyuid", "value": "dup", "domain": ".douyu.com"},     # 非 huya 域——剔除
        {"name": "hicl_imid", "value": "", "domain": ".huya.com"},     # 空值——剔除
    ]
    ok = await export_huya_archive(FakeCookieContext(cookies))
    assert ok is True
    saved = json.loads((tmp_path / "huya_login_cookies.json").read_text(encoding="utf-8"))
    assert set(saved.keys()) == {"cookies"}
    assert saved["cookies"] == [cookies[0], cookies[1]]
    assert not (tmp_path / "huya_login_cookies.json.tmp").exists()  # 原子替换无残留


@pytest.mark.asyncio
@pytest.mark.parametrize("cookies", [
    [],  # 空 cookie 列表
    [{"name": "guest", "value": "v", "domain": ".huya.com"}],  # huya 域但无登录名
])
async def test_export_huya_archive_no_login_cookie_returns_false(monkeypatch, tmp_path, cookies):
    """无登录 cookie（与 yyuid/hicl_imid/huya_uid 交集为空）→ False 且不落盘"""
    _patch_cookie_dir(monkeypatch, tmp_path)
    ok = await export_huya_archive(FakeCookieContext(cookies))
    assert ok is False
    assert not (tmp_path / "huya_login_cookies.json").exists()


@pytest.mark.asyncio
async def test_export_huya_archive_context_error_returns_false(tmp_path):
    """context.cookies() 异常 → False 不外抛、不落盘"""
    ok = await export_huya_archive(BoomContext())
    assert ok is False
    assert not (tmp_path / "huya_login_cookies.json").exists()


# ---- takeover_login_and_archive ----

@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    LoginTakeoverError("登录未完成（超时/关窗）"),
    RuntimeError("session crashed"),  # 会话层意外异常同样隔离
])
async def test_takeover_login_and_archive_wraps_errors(monkeypatch, exc):
    """login_takeover 异常（LoginTakeoverError/会话层异常）→ 包装为 False 不外抛"""
    from types import SimpleNamespace

    import danmaku_listener.config.settings as settings_mod
    import danmaku_listener.senders.huya as huya_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: SimpleNamespace())

    class FailSession:
        async def login_takeover(self, *args, **kwargs):
            raise exc

    monkeypatch.setattr(huya_mod, "_get_session", lambda idle, mode: FailSession())
    ok = await takeover_login_and_archive("12345")
    assert ok is False


@pytest.mark.asyncio
async def test_takeover_login_and_archive_cleans_up_on_cancel(monkeypatch):
    """ship 对抗F2 守护：stop_room 取消路径→可见窗会话 close 后重抛（防 SingletonLock 连锁失败）"""
    import asyncio
    from types import SimpleNamespace

    import danmaku_listener.config.settings as settings_mod
    import danmaku_listener.senders.huya as huya_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: SimpleNamespace())

    closes: list = []

    class CancelSession:
        async def login_takeover(self, *args, **kwargs):
            raise asyncio.CancelledError

        async def close(self):
            closes.append(True)

    monkeypatch.setattr(huya_mod, "_get_session", lambda idle, mode: CancelSession())
    with pytest.raises(asyncio.CancelledError):
        await takeover_login_and_archive("12345")
    assert closes == [True]
