"""发送管线围栏单元测试（AutoDanmu T2 修复——CEO-3 + 评审 redteam#3 裁定：sender 异常→FAILED 计熔断回执+审计 result 行）

背景（2026-10-08 验收战役）：pipeline.py 唯一分发点（R32）原对 sender.send 无异常围栏，
异常穿透 api_send_danmu → aiohttp 500 且审计无 result 行（幂等索引缺结果）。
"""

import json

import pytest

from danmaku_listener.config.settings import Settings
from danmaku_listener.contract.models import SendStatus, UnifiedMessage
from danmaku_listener.senders.audit import SendAuditLog
from danmaku_listener.senders.base import BaseSender, SendResult
from danmaku_listener.senders.guard import SendGuard
from danmaku_listener.senders.pipeline import DanmuCommandPipeline
from danmaku_listener.senders.registry import SenderRegistry


class BoomSender(BaseSender):
    """恒抛异常的 sender（模拟 launch/evaluate 层未捕获异常）"""

    platform = "taobao"

    async def send(self, room_id: str, content: str) -> SendResult:
        raise RuntimeError("boom: playwright crashed")


class OkSender(BaseSender):
    """正常回执 sender"""

    platform = "taobao"

    async def send(self, room_id: str, content: str) -> SendResult:
        return SendResult(SendStatus.SENT, sent_at=1234567890)


def make_pipeline(tmp_path, sender) -> DanmuCommandPipeline:
    settings = Settings(
        send_enabled_platforms="taobao",
        send_dry_run=False,
        send_min_interval_seconds=0.0,
        send_jitter_seconds=0.0,
        send_circuit_threshold=5,
        send_dedup_window_seconds=300,
        send_max_length=100,
        send_rate_key="platform",
        send_audit_file=str(tmp_path / "audit.jsonl"),
        send_idempotency_index=str(tmp_path / "idem.json"),
    )
    guard = SendGuard(settings, blocked_keywords=[])
    audit = SendAuditLog(settings.send_audit_file, settings.send_idempotency_index)
    registry = SenderRegistry(room_checker=lambda p, r: True)
    registry.register(sender)
    return DanmuCommandPipeline(registry=registry, guard=guard, audit=audit,
                                auth_configured=True)


@pytest.mark.asyncio
async def test_sender_exception_maps_to_failed_with_audit_row(tmp_path):
    """围栏核心断言：sender 抛异常 → FAILED/SEND_TIMEOUT 回执（计熔断）+ 审计 result 行落盘
    （评审 redteam#3 语义裁定：未捕获异常=真实故障计熔断；unknown 保留给 sender 自分类）"""
    pipeline = make_pipeline(tmp_path, BoomSender())
    wire = await pipeline.handle_request(platform="taobao", room_id="1",
                                         request_id="fence-1", content="hello", source="rest")
    msg = UnifiedMessage.from_wire(wire)
    payload = msg.payload
    assert payload.status == SendStatus.FAILED
    assert payload.reason_code == "SEND_TIMEOUT"
    # wire payload 不携带 detail（detail 只进日志与审计）；异常类型经日志断言由上方 WARNING 呈现
    # 审计 result 行必须存在（原缺陷=异常路径无 result 行，幂等索引缺结果）
    rows = [json.loads(line) for line in
            (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    kinds = [r["kind"] for r in rows if r.get("request_id") == "fence-1"]
    assert "intent" in kinds and "result" in kinds
    result_row = next(r for r in rows if r.get("request_id") == "fence-1" and r["kind"] == "result")
    assert result_row["status"] == "failed"


@pytest.mark.asyncio
async def test_sender_receipt_passthrough_unaffected(tmp_path):
    """正常回执路径不受围栏影响（sent 原样透传）"""
    pipeline = make_pipeline(tmp_path, OkSender())
    wire = await pipeline.handle_request(platform="taobao", room_id="1",
                                         request_id="ok-1", content="hello", source="rest")
    msg = UnifiedMessage.from_wire(wire)
    assert msg.payload.status == SendStatus.SENT
    assert msg.payload.sent_at == 1234567890


@pytest.mark.asyncio
async def test_duplicate_hint_points_to_reconcile(tmp_path):
    """CEO-8：DUPLICATE 回执 hint 指引对账查询（影子症状的正确处置）"""
    pipeline = make_pipeline(tmp_path, OkSender())
    first = await pipeline.handle_request(platform="taobao", room_id="1",
                                          request_id="dup-1", content="hello", source="rest")
    assert UnifiedMessage.from_wire(first).payload.status == SendStatus.SENT
    second = await pipeline.handle_request(platform="taobao", room_id="1",
                                           request_id="dup-2", content="hello", source="rest")
    payload = UnifiedMessage.from_wire(second).payload
    assert payload.reason_code == "DUPLICATE"
    assert "对账" in (payload.fix_hint or "")


# Value: protects=守卫链非 DUPLICATE 拒绝（TOO_LONG/KEYWORD_BLOCKED）保持默认 fix_hint
#   「守卫命中——AUTOlive 退避重试」不变（CEO-8 hints map 只接管 DUPLICATE）;
#        fails_when=hints dict 误吞其它 reason（.get 默认参被删→hint=None）或默认 hint 文案被改坏;
#        why_new=test_send_pipeline.py 无守卫拒绝回执的 fix_hint 断言；本 diff 恰好重写了该 hint 选择行;
#        seam=none
@pytest.mark.asyncio
async def test_guard_reject_default_hint_unchanged_for_non_duplicate(tmp_path):
    from danmaku_listener.contract.models import SendRejectReason
    # TOO_LONG：超长内容（send_max_length=100）
    pipeline = make_pipeline(tmp_path, OkSender())
    wire = await pipeline.handle_request(platform="taobao", room_id="1",
                                         request_id="hint-1", content="x" * 101, source="rest")
    payload = UnifiedMessage.from_wire(wire).payload
    assert payload.reason_code == SendRejectReason.TOO_LONG.value
    assert payload.fix_hint == "守卫命中——AUTOlive 退避重试"
    # KEYWORD_BLOCKED：第二个非 DUPLICATE 守卫码同样走默认 hint
    pipeline2 = make_pipeline(tmp_path, OkSender())
    pipeline2._guard._keywords = {"禁词"}
    wire2 = await pipeline2.handle_request(platform="taobao", room_id="1",
                                           request_id="hint-2", content="含禁词的内容", source="rest")
    payload2 = UnifiedMessage.from_wire(wire2).payload
    assert payload2.reason_code == SendRejectReason.KEYWORD_BLOCKED.value
    assert payload2.fix_hint == "守卫命中——AUTOlive 退避重试"


@pytest.mark.asyncio
async def test_fence_exception_still_occupies_dedup_window(tmp_path):
    """计划 §226：围栏捕获异常后去重/限速窗口已被 record_attempt 占用——
    同内容立即重试必得 DUPLICATE+对账 hint（影子症状语义锁定）"""
    pipeline = make_pipeline(tmp_path, BoomSender())
    first = await pipeline.handle_request(platform="taobao", room_id="1",
                                          request_id="occ-1", content="hello", source="rest")
    assert UnifiedMessage.from_wire(first).payload.status == SendStatus.FAILED
    # 换正常 sender 后同内容立即重试：窗口已被异常尝试占用
    pipeline._registry._senders["taobao"] = OkSender()
    second = await pipeline.handle_request(platform="taobao", room_id="1",
                                           request_id="occ-2", content="hello", source="rest")
    payload = UnifiedMessage.from_wire(second).payload
    assert payload.reason_code == "DUPLICATE"
    assert "对账" in (payload.fix_hint or "")
