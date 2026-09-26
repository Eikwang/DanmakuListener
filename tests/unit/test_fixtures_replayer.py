"""fixtures 回放器测试（契约 v1 测试基建 T4）"""

import json

import pytest

from danmaku_listener.fixtures.replayer import load_jsonl, replay, validate_events


@pytest.fixture()
def sample_file(tmp_path):
    events = [
        {"delay_ms": 0, "wire": {"contract_version": "1.0.0", "category": "business", "type": "DANMU",
                                  "platform": "bilibili", "room_id": "1", "seq": 1, "timestamp": 1700000000,
                                  "engine": "replay", "payload": {"type": "DANMU", "user_name": "a", "content": "hi"}}},
        {"delay_ms": 100, "wire": {"contract_version": "1.0.0", "category": "business", "type": "GIFT",
                                    "platform": "bilibili", "room_id": "1", "seq": 2, "timestamp": 1700000001,
                                    "engine": "replay", "payload": {"type": "GIFT", "user_name": "a", "gift_name": "辣条", "gift_count": 1}}},
    ]
    f = tmp_path / "sample.jsonl"
    f.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    return str(f)


def test_load_jsonl(sample_file):
    events = load_jsonl(sample_file)
    assert len(events) == 2
    assert events[1]["delay_ms"] == 100


def test_validate_events(sample_file):
    stats = validate_events(sample_file)
    assert stats["total"] == 2
    assert stats["invalid"] == 0
    assert stats["by_type"] == {"DANMU": 1, "GIFT": 1}


@pytest.mark.asyncio
async def test_replay_yields_in_order(sample_file):
    got = []

    async def sink(wire):
        got.append(wire["seq"])

    async for _ in replay(sample_file, sink, speed=100):
        pass
    assert got == [1, 2]


def test_invalid_jsonl_rejected(tmp_path):
    f = tmp_path / "bad.jsonl"
    f.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(str(f))
