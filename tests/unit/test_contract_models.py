"""契约 v1 模型单测

覆盖：信封校验、category/type 一致性、判别载荷路由、失败三段式非空、
GAP 窗口校验、线格式往返、旧模型兼容适配。
"""

import pytest
from pydantic import ValidationError

from danmaku_listener.bus.message import DanmakuMessage, GiftInfo
from danmaku_listener.contract.legacy import legacy_to_unified, unified_to_legacy
from danmaku_listener.contract.models import (
    Category,
    Envelope,
    FailureInfo,
    GapPayload,
    GapReason,
    InteractiveLogin,
    NeedsLoginPayload,
    RouteFailedPayload,
    UnifiedMessage,
)


def _danmu(seq: int = 0, **over) -> UnifiedMessage:
    return UnifiedMessage(
        envelope=Envelope(
            category=Category.BUSINESS,
            type="DANMU",
            platform="bilibili",
            room_id="23058",
            seq=seq,
            timestamp=1700000000,
            engine="protocol:bilibili",
        ),
        payload={"type": "DANMU", "user_name": "alice", "content": "你好"} | over,
    )


def test_danmu_roundtrip_wire():
    msg = _danmu()
    wire = msg.to_wire()
    assert wire["category"] == "business"
    assert wire["type"] == "DANMU"
    restored = UnifiedMessage.from_wire(wire)
    assert restored.envelope == msg.envelope
    assert restored.payload == msg.payload


def test_category_type_consistency():
    with pytest.raises(ValidationError):
        UnifiedMessage(
            envelope=Envelope(
                category=Category.BUSINESS,
                type="HEARTBEAT",  # 业务大类不允许系统类型
                platform="bilibili",
                room_id="1",
                seq=0,
                timestamp=1,
                engine="e",
            ),
            payload={"type": "HEARTBEAT"},
        )


def test_payload_type_mismatch_rejected():
    with pytest.raises(ValidationError):
        UnifiedMessage(
            envelope=Envelope(
                category=Category.BUSINESS,
                type="GIFT",
                platform="bilibili",
                room_id="1",
                seq=0,
                timestamp=1,
                engine="e",
            ),
            payload={"type": "DANMU", "user_name": "a", "content": "b"},
        )


def test_failure_info_nonempty():
    with pytest.raises(ValidationError):
        RouteFailedPayload(failure=FailureInfo(reason_code="", fix_hint="x", docs_anchor="y"))
    with pytest.raises(ValidationError):
        RouteFailedPayload(failure=FailureInfo(reason_code="x", fix_hint=" ", docs_anchor="y"))


def test_gap_window_order():
    with pytest.raises(ValidationError):
        GapPayload(window_start=100, window_end=50, reason=GapReason.NETWORK)


def test_gap_backpressure_reason():
    g = GapPayload(window_start=1, window_end=2, reason=GapReason.BACKPRESSURE, dropped_estimate=5)
    assert g.reason == GapReason.BACKPRESSURE


def test_needs_login_interactive_payload():
    p = NeedsLoginPayload(
        failure=FailureInfo(reason_code="wechat_channels.login_expired", fix_hint="重新扫码", docs_anchor="docs/platforms/wechat_channels/runbook.md"),
        interactive_login=InteractiveLogin(login_url="https://channels.weixin.qq.com/..."),
    )
    assert p.interactive_login.login_url.startswith("https://")
    with pytest.raises(ValidationError):
        NeedsLoginPayload(
            failure=FailureInfo(reason_code="a", fix_hint="b", docs_anchor="c"),
            interactive_login=InteractiveLogin(),
        )


def test_negative_seq_rejected():
    with pytest.raises(ValidationError):
        _danmu(seq=-1)


def test_legacy_roundtrip_danmu():
    old = DanmakuMessage(
        platform="douyin",
        room_id="123",
        user_name="bob",
        content="hi",
        timestamp=1700000001,
        message_type="normal",
    )
    uni = legacy_to_unified(old, seq=1, engine="proxy:douyin")
    assert uni.envelope.type == "DANMU"
    back = unified_to_legacy(uni)
    assert back == old


def test_legacy_roundtrip_gift():
    old = DanmakuMessage(
        platform="douyin",
        room_id="123",
        user_name="bob",
        content="玫瑰",
        timestamp=1700000002,
        message_type="gift",
        gift_info=GiftInfo(user_name="bob", gift_name="玫瑰", gift_count=2, gift_value=10),
    )
    uni = legacy_to_unified(old, seq=2, engine="proxy:douyin")
    assert uni.envelope.type == "GIFT"
    back = unified_to_legacy(uni)
    assert back is not None
    assert back.gift_info.gift_count == 2


def test_legacy_system_maps_to_gap():
    old = DanmakuMessage(
        platform="douyin",
        room_id="123",
        user_name="",
        content="reconnected",
        timestamp=1700000003,
        message_type="system",
    )
    uni = legacy_to_unified(old, seq=3, engine="proxy:douyin")
    assert uni.envelope.category == Category.SYSTEM
    assert uni.envelope.type == "GAP"
    assert uni.payload.approx is True


def test_unsupported_unified_to_legacy_returns_none():
    assert unified_to_legacy(_danmu()) is not None  # DANMU 支持
    uni = UnifiedMessage(
        envelope=Envelope(
            category=Category.SYSTEM,
            type="HEARTBEAT",
            platform="bilibili",
            room_id="1",
            seq=0,
            timestamp=1,
            engine="e",
        ),
        payload={"type": "HEARTBEAT"},
    )
    assert unified_to_legacy(uni) is None
