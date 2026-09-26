"""心跳循环、loop lag 与录制器测试"""

import asyncio
import json

import pytest

from danmaku_listener.bus.heartbeat_loop import HeartbeatLoop
from danmaku_listener.bus.system_status import SystemStatusFactory
from danmaku_listener.contract import Category
from danmaku_listener.fixtures.recorder import FixtureRecorder
from danmaku_listener.fixtures.replayer import validate_events


def _factory():
    return SystemStatusFactory(platform="bilibili", engine="protocol:bilibili")


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_and_lags():
    sent = []
    rooms = ["r1", "r2"]

    async def send(wire):
        sent.append(wire)

    loop = HeartbeatLoop(_factory(), send, interval_seconds=0.05, rooms_provider=lambda: rooms)
    loop.start()
    await asyncio.sleep(0.25)
    await loop.stop()

    assert len(sent) >= 2  # 至少一个完整周期覆盖两个房间
    for wire in sent:
        assert wire["category"] == "system"
        assert wire["type"] == "HEARTBEAT"
    # 每周期两房间各一条；全部房间覆盖
    last_cycle = sent[-2:]
    assert {w["room_id"] for w in last_cycle} == {"r1", "r2"}


def test_recorder_writes_replayable_jsonl(tmp_path):
    path = tmp_path / "rec.jsonl"
    rec = FixtureRecorder(str(path), platform="bilibili")
    rec.record({
        "contract_version": "1.0.0", "category": "business", "type": "DANMU",
        "platform": "bilibili", "room_id": "1", "seq": 1, "timestamp": 1700000000,
        "engine": "test", "payload": {"type": "DANMU", "user_name": "a", "content": "hi"},
    })
    rec.record({
        "contract_version": "1.0.0", "category": "business", "type": "GIFT",
        "platform": "bilibili", "room_id": "1", "seq": 2, "timestamp": 1700000001,
        "engine": "test", "payload": {"type": "GIFT", "user_name": "a", "gift_name": "辣条", "gift_count": 1},
    })
    n = rec.close()
    assert n == 2

    stats = validate_events(str(path))
    assert stats["total"] == 2
    assert stats["by_type"] == {"DANMU": 1, "GIFT": 1}


def test_recorder_delay_ms_monotonic(tmp_path):
    path = tmp_path / "rec.jsonl"
    rec = FixtureRecorder(str(path))
    rec.record({"seq": 1})
    rec.record({"seq": 2})
    rec.close()
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    assert lines[0]["delay_ms"] == 0
    assert lines[1]["delay_ms"] >= 0
