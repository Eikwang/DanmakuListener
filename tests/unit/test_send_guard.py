"""SendGuard 六件套单元测试（AutoDanmu T4 验证义务）

覆盖：开关默认关/熔断 N 边界/限速/去重/长度/关键词/控制符清洗（DX-F1 拒绝不排队语义）。
"""

import pytest

from danmaku_listener.config.settings import Settings
from danmaku_listener.contract.models import SendRejectReason
from danmaku_listener.senders.guard import SendGuard


def make_guard(**overrides) -> SendGuard:
    base = dict(
        send_enabled_platforms="bilibili",
        send_dry_run=False,
        send_min_interval_seconds=30.0,
        send_jitter_seconds=0.0,
        send_circuit_threshold=3,
        send_dedup_window_seconds=300,
        send_max_length=100,
        send_rate_key="platform",
    )
    base.update(overrides)
    return SendGuard(Settings(**base), blocked_keywords=["违禁词"])


def test_default_all_disabled():
    g = SendGuard(Settings())
    ok, reason, _ = g.check("bilibili", "1", "hello")
    assert not ok and reason == SendRejectReason.SENDER_DISABLED.value


def test_enabled_platform_passes_basic():
    g = make_guard()
    ok, reason, sanitized = g.check("bilibili", "1", "hello world")
    assert ok and reason is None and sanitized == "hello world"


def test_rate_limit_rejects_second_immediate_send():
    g = make_guard()
    assert g.check("bilibili", "1", "first")[0]
    g.record_attempt("bilibili", "1", "first")
    ok, reason, _ = g.check("bilibili", "1", "second")
    assert not ok and reason == SendRejectReason.RATE_LIMITED.value


def test_rate_key_platform_room_isolates_rooms():
    g = make_guard(send_rate_key="platform_room")
    g.record_attempt("bilibili", "1", "x")
    ok, _, _ = g.check("bilibili", "2", "y")  # 不同房间不受同平台窗口挤兑（F4）
    assert ok


def test_dedup_window_blocks_same_content():
    g = make_guard(send_dedup_window_seconds=300)
    g.record_attempt("bilibili", "1", "same")
    ok, reason, _ = g.check("bilibili", "1", "same")
    assert not ok and reason == SendRejectReason.DUPLICATE.value


def test_too_long_rejected():
    g = make_guard(send_max_length=10)
    ok, reason, _ = g.check("bilibili", "1", "x" * 11)
    assert not ok and reason == SendRejectReason.TOO_LONG.value


def test_keyword_blocked():
    g = make_guard()
    ok, reason, _ = g.check("bilibili", "1", "包含违禁词的内容")
    assert not ok and reason == SendRejectReason.KEYWORD_BLOCKED.value


def test_control_chars_sanitized():
    g = make_guard()
    ok, _, sanitized = g.check("bilibili", "1", "hello\u0007world\n")
    assert ok and sanitized == "helloworld"


def test_circuit_opens_after_n_failures_and_stays_until_manual_reset():
    g = make_guard(send_circuit_threshold=3)
    for _ in range(2):
        g.record_result("bilibili", "failed")
    assert not g.is_tripped("bilibili")
    g.record_result("bilibili", "failed")  # 第 N=3 次 → 熔断（F3）
    ok, reason, _ = g.check("bilibili", "1", "hello")
    assert g.is_tripped("bilibili")
    assert not ok and reason == SendRejectReason.CIRCUIT_OPEN.value
    g.record_result("bilibili", "failed")  # 继续失败不解熔断
    assert g.is_tripped("bilibili")
    g.enable("bilibili")  # 人工重开（R10：不自动恢复）
    ok, _, _ = g.check("bilibili", "1", "hello")
    assert ok


def test_unknown_does_not_count_toward_circuit():
    g = make_guard(send_circuit_threshold=2)
    g.record_result("bilibili", "unknown")
    g.record_result("bilibili", "unknown")
    assert not g.is_tripped("bilibili")  # R36：unknown 不计熔断


def test_success_resets_fail_streak():
    g = make_guard(send_circuit_threshold=3)
    g.record_result("bilibili", "failed")
    g.record_result("bilibili", "failed")
    g.record_result("bilibili", "sent")
    g.record_result("bilibili", "failed")
    assert not g.is_tripped("bilibili")


def test_snapshot_shape():
    g = make_guard(send_dry_run=True)
    snap = g.snapshot()
    assert snap["dry_run"] is True
    assert snap["platforms"]["bilibili"]["enabled"] is True
    assert snap["platforms"]["bilibili"]["circuit_open"] is False
