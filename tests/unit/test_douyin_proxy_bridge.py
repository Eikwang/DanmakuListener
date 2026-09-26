"""抖音代理桥接测试（阶段 2）——旧 DanmakuMessage → 契约统一消息"""

import pytest

from danmaku_listener.bus.message import DanmakuMessage
from danmaku_listener.engines.douyin_proxy import DouyinProxyEngine


@pytest.mark.asyncio
async def test_ingest_legacy_to_contract():
    engine = DouyinProxyEngine()
    received: list[dict] = []

    async def on_message(data: dict):
        received.append(data)

    engine.on_message(on_message)

    old = DanmakuMessage(
        platform="douyin", room_id="123", user_name="小明",
        content="来了来了", timestamp=1700000000, message_type="normal",
    )
    unified = await engine.ingest_legacy(old)

    assert unified.envelope.type == "DANMU"
    assert unified.envelope.engine == "proxy:douyin"
    assert unified.envelope.seq == 1
    assert len(received) == 1
    assert received[0]["payload"]["content"] == "来了来了"


@pytest.mark.asyncio
async def test_route_failed_three_part():
    engine = DouyinProxyEngine()
    received: list[dict] = []

    async def on_message(data: dict):
        received.append(data)

    engine.on_message(on_message)
    await engine.route_failed(
        "123",
        reason_code="douyin.companion.version_mismatch",
        fix_hint="还原 index.js 并锁定直播伴侣版本",
        docs_anchor="docs/platforms/douyin/runbook.md#version-lock",
    )
    from danmaku_listener.contract.models import UnifiedMessage
    msg = UnifiedMessage.from_wire(received[0])
    assert msg.envelope.type == "ROUTE_FAILED"
    assert msg.payload.failure.reason_code == "douyin.companion.version_mismatch"
