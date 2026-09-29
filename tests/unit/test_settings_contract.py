"""配置面测试：TOML 覆盖加载、四层优先级、有界参数校验（契约 v1 DX-B）"""

import textwrap

import pytest
from pydantic import ValidationError

from danmaku_listener.config.settings import Settings, load_toml_overrides


def test_defaults_present():
    s = Settings()
    # 有界参数默认值与配置键（DX-B）
    assert s.bus_ring_capacity == 10000
    assert s.bus_dedup_window_seconds == 120
    assert s.engine_heartbeat_seconds == 10
    assert s.engine_lost_periods == 3
    assert s.platform_silence_timeout == 30
    assert s.fast_retry_max == 3
    assert s.slow_retry_cap_seconds == 900
    assert s.session_lifetime_seconds == 14400  # 4h
    assert s.ws_bind == "127.0.0.1"  # Eng S-2：默认仅本机
    assert s.bus_drop_order_list == ["LIKE", "ENTER_ROOM", "DANMU"]


def test_invalid_bounds_rejected():
    with pytest.raises(ValidationError):
        Settings(bus_ring_capacity=0)
    with pytest.raises(ValidationError):
        Settings(bus_dedup_window_seconds=-5)
    with pytest.raises(ValidationError):
        Settings(ws_bind="0.0.0.1")


def test_toml_nested_and_flat(tmp_path):
    toml = tmp_path / "cfg.toml"
    toml.write_text(
        textwrap.dedent(
            """
            log_level = "DEBUG"

            [ws]
            port = 9999
            """
        ),
        encoding="utf-8",
    )
    overrides = load_toml_overrides(str(toml))
    assert overrides["ws_port"] == 9999
    assert overrides["log_level"] == "DEBUG"
    s = Settings(**overrides)
    assert s.ws_port == 9999
    assert s.log_level == "DEBUG"


def test_toml_unknown_keys_ignored(tmp_path):
    toml = tmp_path / "cfg.toml"
    toml.write_text(
        textwrap.dedent(
            """
            [unknown_section]
            foo = 1
            """
        ),
        encoding="utf-8",
    )
    overrides = load_toml_overrides(str(toml))
    assert overrides == {}
