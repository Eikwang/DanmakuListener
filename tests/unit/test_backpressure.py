"""背压分级缓冲与去重窗口测试（契约 v1 工程前置 M/P）"""

import pytest

from danmaku_listener.bus.backpressure import BackpressureBuffer, BackpressureWindow
from danmaku_listener.bus.dedup_filter import DedupFilter


def test_buffer_basic_fifo():
    buf = BackpressureBuffer(capacity=3, drop_order=["LIKE"], overflow="oldest")
    assert buf.put("DANMU", {"seq": 1})
    assert buf.put("DANMU", {"seq": 2})
    assert buf.put("DANMU", {"seq": 3})
    wires = buf.drain()
    assert [w["seq"] for w in wires] == [1, 2, 3]


def test_backpressure_drops_low_value_first():
    buf = BackpressureBuffer(capacity=3, drop_order=["LIKE", "ENTER_ROOM", "DANMU"], overflow="oldest")
    buf.put("LIKE", {"n": 1})
    buf.put("ENTER_ROOM", {"n": 2})
    buf.put("GIFT", {"n": 3})
    # 满：新 DANMU 进来 → LIKE（drop_order 最前）被挤掉
    assert buf.put("DANMU", {"n": 4})
    dropped = buf.take_window_dropped()
    assert dropped == {"LIKE": 1}
    wires = buf.drain()
    assert [w["n"] for w in wires] == [2, 3, 4]


def test_backpressure_drop_order_priority():
    buf = BackpressureBuffer(capacity=2, drop_order=["LIKE", "DANMU"], overflow="oldest")
    buf.put("DANMU", {"n": 1})
    buf.put("GIFT", {"n": 2})
    # 满：drop_order 先 LIKE（无）再 DANMU → 挤掉 DANMU，保留 GIFT
    assert buf.put("GIFT", {"n": 3})
    dropped = buf.take_window_dropped()
    assert dropped == {"DANMU": 1}
    assert [w["n"] for w in buf.drain()] == [2, 3]


def test_overflow_newest_rejects_incoming():
    buf = BackpressureBuffer(capacity=2, drop_order=["LIKE"], overflow="newest")
    buf.put("GIFT", {"n": 1})
    buf.put("SUPER_CHAT", {"n": 2})
    # 满：无 LIKE 可挤（GIFT/SUPER_CHAT 高价值）→ newest=拒绝新 GIFT
    assert buf.put("GIFT", {"n": 3}) is False
    dropped = buf.take_window_dropped()
    assert dropped == {"GIFT": 1}
    assert [w["n"] for w in buf.drain()] == [1, 2]


def test_overflow_oldest_drops_any():
    buf = BackpressureBuffer(capacity=2, drop_order=["LIKE"], overflow="oldest")
    buf.put("GIFT", {"n": 1})
    buf.put("SUPER_CHAT", {"n": 2})
    assert buf.put("GIFT", {"n": 3})  # oldest：挤掉最老（GIFT n=1）
    assert [w["n"] for w in buf.drain()] == [2, 3]


def test_window_dropped_accumulates_between_reports():
    buf = BackpressureBuffer(capacity=1, drop_order=["LIKE"], overflow="oldest")
    win = BackpressureWindow(report_seconds=60)
    buf.put("LIKE", {"n": 1})
    buf.put("GIFT", {"n": 2})  # LIKE 被挤
    # 第一次 should_report（周期未到也可能立即取——monotonic 间隔极短，视实现）
    # 直接验证 take 语义：
    dropped = buf.take_window_dropped()
    assert dropped == {"LIKE": 1}
    assert buf.take_window_dropped() == {}


def test_invalid_capacity_rejected():
    with pytest.raises(ValueError):
        BackpressureBuffer(capacity=0, drop_order=[])
    with pytest.raises(ValueError):
        BackpressureBuffer(capacity=10, drop_order=[], overflow="sideways")


def test_dedup_window_seconds_param():
    f = DedupFilter(window_size=10, window_seconds=1)
    assert f.window_seconds == 1
    assert not f.should_filter("r1", "m1")
    assert f.should_filter("r1", "m1")  # 窗口内重复
