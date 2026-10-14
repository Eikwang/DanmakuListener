"""引擎注册表测试（阶段 6 收口）"""

import pytest

from danmaku_listener.engines.registry import PLATFORM_ENGINES, build_engine


def test_all_platforms_registered():
    assert set(PLATFORM_ENGINES.keys()) == {
        "bilibili", "douyu", "huya", "kuaishou", "wechat_channels", "douyin", "taobao", "1688", "meituan", "xiaohongshu", "pdd", "jd"
    }


def test_build_engine_returns_correct_type():
    from danmaku_listener.engines.protocol.bilibili import BilibiliProtocolEngine
    engine = build_engine("bilibili")
    assert isinstance(engine, BilibiliProtocolEngine)
    assert engine.engine_id == "protocol:bilibili"


def test_unknown_platform_clear_error():
    with pytest.raises(KeyError, match="pinduoduo"):
        build_engine("pinduoduo")


# ---- bilibili cookie 兜底（S5，2026-10-13：默认 txt 缺失→兜底登录闭环产物）----

class _RecordingEngine:
    """捕获构造 kwargs 的假引擎（替代真 BilibiliProtocolEngine 构造）"""

    def __init__(self, state_store=None, **kwargs):
        self.kwargs = kwargs
        self.state_store = state_store


def _patch_bilibili_settings(monkeypatch, bilibili_cookie_file):
    from types import SimpleNamespace

    import danmaku_listener.config.settings as settings_mod
    import danmaku_listener.engines.registry as registry_mod

    monkeypatch.setattr(settings_mod, "get_settings",
                        lambda: SimpleNamespace(bilibili_cookie_file=bilibili_cookie_file))
    monkeypatch.setitem(registry_mod.PLATFORM_ENGINES, "bilibili", _RecordingEngine)


def test_bilibili_cookie_fallback_reads_storage_state(monkeypatch, tmp_path):
    """默认 txt 不存在→兜底读登录闭环产物 bilibili_storage_state.json（同目录）"""
    default_txt = tmp_path / "bilibili_cookies.txt"  # 不存在
    fallback = tmp_path / "bilibili_storage_state.json"
    fallback.write_text("{}", encoding="utf-8")
    _patch_bilibili_settings(monkeypatch, str(default_txt))
    engine = build_engine("bilibili")
    assert engine.kwargs["cookie_file"] == str(fallback)


def test_bilibili_cookie_fallback_miss_keeps_default(monkeypatch, tmp_path):
    """兜底也未命中→保持原路径（回退默认 txt，行为不变）"""
    default_txt = tmp_path / "bilibili_cookies.txt"  # 两文件都不存在
    _patch_bilibili_settings(monkeypatch, str(default_txt))
    engine = build_engine("bilibili")
    assert engine.kwargs["cookie_file"] == str(default_txt)
