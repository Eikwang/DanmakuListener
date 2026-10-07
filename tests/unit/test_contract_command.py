"""契约 command 扩展单元测试（AutoDanmu T3——additive-only 验证）"""

import time

import pytest
from pydantic import ValidationError

from danmaku_listener.contract.models import (Category, DanmuSendRequestPayload,
                                              DanmuSendResultPayload, SendStatus,
                                              UnifiedMessage)


def _envelope(t, platform="bilibili", room_id="23058"):
    return dict(category="command", type=t, platform=platform, room_id=room_id,
                seq=1, timestamp=int(time.time()), engine="autolive")


def test_send_request_roundtrip():
    m = UnifiedMessage(envelope=_envelope("DANMU_SEND_REQUEST"),
                       payload={"type": "DANMU_SEND_REQUEST", "request_id": "r1", "content": "hi"})
    w = m.to_wire()
    assert w["category"] == "command"
    m2 = UnifiedMessage.from_wire(w)
    assert m2.payload.request_id == "r1" and m2.payload.content == "hi"


def test_blank_content_rejected():
    with pytest.raises(ValidationError):
        DanmuSendRequestPayload(request_id="r1", content="   ")


def test_failed_requires_reason_code():
    with pytest.raises(ValidationError):
        DanmuSendResultPayload(request_id="r1", status=SendStatus.FAILED)
    ok = DanmuSendResultPayload(request_id="r1", status=SendStatus.FAILED,
                                reason_code="SENDER_DISABLED")
    assert ok.reason_code == "SENDER_DISABLED"


def test_sent_requires_sent_at():
    with pytest.raises(ValidationError):
        DanmuSendResultPayload(request_id="r1", status=SendStatus.SENT)
    ok = DanmuSendResultPayload(request_id="r1", status=SendStatus.SENT, sent_at=1700000000)
    assert ok.sent_at == 1700000000


def test_dry_run_is_valid_status_without_sent_at():
    ok = DanmuSendResultPayload(request_id="r1", status=SendStatus.DRY_RUN)
    assert ok.status == SendStatus.DRY_RUN  # 非成功语义（DX-F1）


def test_category_mismatch_rejected():
    with pytest.raises(ValidationError):
        UnifiedMessage(envelope={**_envelope("DANMU_SEND_REQUEST"), "category": "business"},
                       payload={"type": "DANMU_SEND_REQUEST", "request_id": "r1", "content": "x"})


def test_additive_only_business_system_unchanged():
    # 既有九类不受 command 扩展影响（回归守护）
    m = UnifiedMessage(envelope={**_envelope("DANMU"), "category": "business", "type": "DANMU"},
                       payload={"type": "DANMU", "user_name": "u", "content": "c"})
    assert m.is_business and m.envelope.category == Category.BUSINESS
