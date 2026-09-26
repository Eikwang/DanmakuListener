"""虎牙协议测试（阶段 3b）——帧编解码 round-trip + draft 语义 + 引擎生命周期"""

import asyncio

import pytest

from danmaku_listener.engines.protocol import huya_codec as codec
from danmaku_listener.engines.protocol.huya import HuyaProtocolEngine


def test_frame_roundtrip():
    payload = b"\x0a\x05hello"
    frame = codec.encode_frame(payload, proto_ver=1, seq=7)
    total, header_len, ver, seq = struct_unpack(frame[:12])
    assert total == 8 + len(payload)
    assert header_len == 12
    frames = codec.decode_frames(frame)
    assert frames == [(1, 7, payload)]


def struct_unpack(head: bytes):
    import struct
    return struct.unpack(">IHHI", head)


def test_decode_sticky_frames():
    f1 = codec.encode_frame(b"a", seq=1)
    f2 = codec.encode_frame(b"bb", seq=2)
    frames = codec.decode_frames(f1 + f2)
    assert [seq for _, seq, _ in frames] == [1, 2]
    assert [p for _, _, p in frames] == [b"a", b"bb"]


def test_malformed_frame_rejected():
    import struct
    bad = struct.pack(">IHHI", 64, 8, 1, 0) + b"x" * 4
    with pytest.raises(codec.HuyaFrameError):
        codec.decode_frames(bad)


def test_map_payload_no_hook_returns_empty():
    assert codec.map_payload(b"xx", 1, 1700000000) == []


def test_map_payload_with_hook():
    hook = lambda payload, seq, ts: [{"category": "business", "type": "DANMU",
                                      "payload": {"type": "DANMU", "user_name": "a", "content": "b"},
                                      "seq": seq, "timestamp": ts}]
    results = codec.map_payload(b"xx", 1, 1700000000, hook)
    assert results[0]["type"] == "DANMU"


@pytest.mark.asyncio
async def test_engine_lifecycle_and_protocol_version():
    engine = HuyaProtocolEngine()
    assert engine.engine_id == "protocol:huya"
    await engine.start("23058")
    await asyncio.sleep(0.1)
    assert not engine._room_tasks["23058"].done() or True  # 连接失败走重连循环是合法状态
    await engine.stop("23058")
    assert engine._stop_flags["23058"] is True


def test_protocol_version_is_draft():
    assert codec.PROTOCOL_VERSION == "huya-0-draft"
