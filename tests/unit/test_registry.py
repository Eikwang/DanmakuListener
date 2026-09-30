"""引擎注册表测试（阶段 6 收口）"""

import pytest

from danmaku_listener.engines.registry import PLATFORM_ENGINES, build_engine


def test_all_platforms_registered():
    assert set(PLATFORM_ENGINES.keys()) == {
        "bilibili", "douyu", "huya", "kuaishou", "wechat_channels", "douyin", "taobao", "1688", "meituan", "xiaohongshu", "jd"
    }


def test_build_engine_returns_correct_type():
    from danmaku_listener.engines.protocol.bilibili import BilibiliProtocolEngine
    engine = build_engine("bilibili")
    assert isinstance(engine, BilibiliProtocolEngine)
    assert engine.engine_id == "protocol:bilibili"


def test_unknown_platform_clear_error():
    with pytest.raises(KeyError, match="pinduoduo"):
        build_engine("pinduoduo")
