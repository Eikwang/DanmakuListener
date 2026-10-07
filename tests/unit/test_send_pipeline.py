"""发送管线+审计单元测试（AutoDanmu T5 验证义务）

覆盖：幂等（R18/F9 重启重建）/审计 fail-closed（R25）/dry-run 回执语义（DX-F1）/
守卫拒绝回执/room 判定（F2）/F6 鉴权拒绝/回执线格式（尽力推送广播断言）。
持久化模块 → chdir 隔离 fixture（学习 persisted-runtime-data-pollutes-tests）。
"""

import json

import pytest

from danmaku_listener.config.settings import Settings
from danmaku_listener.contract.models import SendRejectReason, SendStatus
from danmaku_listener.senders.audit import SendAuditLog
from danmaku_listener.senders.base import SendResult, BaseSender
from danmaku_listener.senders.pipeline import DanmuCommandPipeline
from danmaku_listener.senders.registry import SenderRegistry


@pytest.fixture()
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def make_settings(**overrides) -> Settings:
    base = dict(
        send_enabled_platforms="bilibili",
        send_dry_run=False,
        send_min_interval_seconds=0.0,
        send_jitter_seconds=0.0,
        send_circuit_threshold=5,
        send_dedup_window_seconds=300,
        send_max_length=100,
        send_rate_key="platform",
        send_audit_file="./persistence_data/send_audit.jsonl",
        send_idempotency_index="./persistence_data/send_idempotency.json",
    )
    base.update(overrides)
    return Settings(**base)


class FakeSender(BaseSender):
    platform = "bilibili"

    def __init__(self, result: SendResult):
        self._result = result
        self.calls: list[tuple[str, str]] = []

    async def send(self, room_id: str, content: str) -> SendResult:
        self.calls.append((room_id, content))
        return self._result


class RoomRegistry(SenderRegistry):
    """F2 快照注册表（可控房间集合）"""

    def __init__(self, rooms: set):
        super().__init__(room_checker=lambda p, r: (p, r) in rooms)
        self.rooms = rooms


def make_pipeline(tmp_path, *, rooms=("bilibili", "1"), enabled="bilibili",
                  dry_run=False, sender=None, auth=True, settings=None):
    s = settings or make_settings(send_enabled_platforms=enabled, send_dry_run=dry_run)
    reg = RoomRegistry({rooms} if isinstance(rooms, tuple) else rooms)
    reg.register(sender or FakeSender(SendResult(SendStatus.SENT, sent_at=1700000000)))
    audit = SendAuditLog(str(tmp_path / "audit.jsonl"), str(tmp_path / "idem.json"))
    broadcasts: list[dict] = []

    async def broadcast(wire: dict) -> None:
        broadcasts.append(wire)

    pipe = DanmuCommandPipeline(registry=reg, guard=None, audit=audit,
                                broadcaster=broadcast, auth_configured=auth)
    # guard 在管线后构造注入（避免 settings 泄漏到 registry）
    from danmaku_listener.senders.guard import SendGuard
    pipe._guard = SendGuard(s, blocked_keywords=[])
    pipe._audit = audit
    return pipe, reg, audit, broadcasts


@pytest.mark.asyncio
async def test_happy_path_sent_receipt(in_tmp):
    pipe, _, audit, broadcasts = make_pipeline(in_tmp)
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    p = wire["payload"]
    assert wire["category"] == "command" and wire["type"] == "DANMU_SEND_RESULT"
    assert p["status"] == "sent" and p["sent_at"] == 1700000000
    assert len(broadcasts) == 1  # 尽力推送（R11）
    assert audit.lookup("r1")["status"] == "sent"


@pytest.mark.asyncio
async def test_dry_run_is_not_success_semantics(in_tmp):
    pipe, reg, audit, _ = make_pipeline(in_tmp, dry_run=True)
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    p = wire["payload"]
    assert p["status"] == "dry_run"  # DX-F1/R11：非成功语义
    assert reg._senders["bilibili"].calls == []  # 未实发


@pytest.mark.asyncio
async def test_idempotent_replay_returns_last_result(in_tmp):
    pipe, _, _, _ = make_pipeline(in_tmp)
    await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    p = wire["payload"]
    assert p["status"] == "sent"  # 回执上次结果（R18）
    assert p["reason_code"] in (None, SendRejectReason.IDEMPOTENT_REPLAY.value)


@pytest.mark.asyncio
async def test_idempotency_index_survives_restart(in_tmp):
    pipe, _, audit, _ = make_pipeline(in_tmp)
    await pipe.handle_request("bilibili", "1", "r9", "hello", source="rest")
    # 模拟重启：新管线实例从磁盘索引恢复（F9）
    audit2 = SendAuditLog(str(in_tmp / "audit.jsonl"), str(in_tmp / "idem.json"))
    assert audit2.lookup("r9")["status"] == "sent"


@pytest.mark.asyncio
async def test_room_not_listened(in_tmp):
    pipe, _, _, _ = make_pipeline(in_tmp, rooms=set())
    wire = await pipe.handle_request("bilibili", "999", "r1", "hello", source="rest")
    assert wire["payload"]["reason_code"] == SendRejectReason.ROOM_NOT_LISTENED.value


@pytest.mark.asyncio
async def test_sender_disabled(in_tmp):
    pipe, _, _, _ = make_pipeline(in_tmp, enabled="")
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    assert wire["payload"]["reason_code"] == SendRejectReason.SENDER_DISABLED.value


@pytest.mark.asyncio
async def test_auth_unconfigured_refuses_service(in_tmp):
    pipe, _, _, _ = make_pipeline(in_tmp, auth=False)
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    assert wire["payload"]["reason_code"] == SendRejectReason.AUTH_UNCONFIGURED.value  # F6


@pytest.mark.asyncio
async def test_audit_fail_closed_blocks_real_send(in_tmp, monkeypatch):
    pipe, reg, audit, _ = make_pipeline(in_tmp)
    monkeypatch.setattr(audit, "append", lambda row: False)  # 审计写入失败（R25）
    wire = await pipe.handle_request("bilibili", "1", "r1", "hello", source="rest")
    assert wire["payload"]["reason_code"] == SendRejectReason.AUDIT_UNAVAILABLE.value
    assert reg._senders["bilibili"].calls == []  # 未实发（fail-closed）


@pytest.mark.asyncio
async def test_circuit_open_blocks_before_sender(in_tmp):
    sender = FakeSender(SendResult(SendStatus.SENT, sent_at=1))
    pipe, _, _, _ = make_pipeline(in_tmp, sender=sender)
    for i in range(5):  # 阈值 5（默认 N）
        await pipe.handle_request("bilibili", "1", f"f{i}", f"msg-{i}", source="rest")
    sender._result = SendResult(SendStatus.FAILED, SendRejectReason.PLATFORM_REJECTED.value)
    pipe._registry._senders["bilibili"] = sender
    for i in range(5):
        await pipe.handle_request("bilibili", "1", f"g{i}", f"other-{i}", source="rest")
    assert pipe._guard.is_tripped("bilibili")
    wire = await pipe.handle_request("bilibili", "1", "blocked", "hello", source="rest")
    assert wire["payload"]["reason_code"] == SendRejectReason.CIRCUIT_OPEN.value  # F3 独立码


@pytest.mark.asyncio
async def test_malformed_wire_rejected_without_crash(in_tmp):
    pipe, _, _, _ = make_pipeline(in_tmp)
    wire = await pipe.handle_wire({"bad": "data"}, source="ws")
    assert wire["payload"]["status"] == "failed"  # E3：畸形命令拒绝不炸
