"""视频号受控后台引擎测试（阶段 5）——有界会话语义 + NEEDS_LOGIN 闭环 + 契约合规"""

import asyncio
import json

import pytest

from danmaku_listener.contract import Category, SystemType
from danmaku_listener.contract.models import UnifiedMessage
from danmaku_listener.engines.wechat_channels import (
    SESSION_LIFETIME_SECONDS,
    BACKEND_URL,
    WechatChannelsEngine,
)


@pytest.mark.asyncio
async def test_session_event_is_contract_compliant():
    engine = WechatChannelsEngine()
    received: list[dict] = []

    async def on_message(data: dict):
        received.append(data)

    engine.on_message(on_message)
    await engine._emit_session_event("room1", detail="session rebuilt after 100s")
    await asyncio.sleep(0)

    assert len(received) == 1
    msg = UnifiedMessage.from_wire(received[0])  # 契约可解析
    assert msg.envelope.category == Category.SYSTEM
    assert msg.envelope.type == SystemType.ENGINE_STATUS.value
    assert msg.payload.engine == "controlled:wechat_channels"
    assert "rebuilt" in msg.payload.detail


def test_needs_login_payload_schema_requires_interactive_or_none():
    # interactive_login 必须二选一（qr/url）否则 ValidationError —— 契约 E 项
    from danmaku_listener.contract.models import FailureInfo, NeedsLoginPayload
    with pytest.raises(Exception):
        NeedsLoginPayload(
            failure=FailureInfo(reason_code="a", fix_hint="b", docs_anchor="c"),
            interactive_login={"qr_image_b64": None, "login_url": None},
        )


def test_session_lifetime_is_4h():
    assert SESSION_LIFETIME_SECONDS == 14400


def test_backend_url_constant():
    assert "channels.weixin.qq.com" in BACKEND_URL
