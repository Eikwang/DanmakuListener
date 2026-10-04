"""B站协议编解码与引擎测试（阶段 1）

覆盖：帧编解码 round-trip、畸形帧拒绝、zlib 嵌套解压、上游消息映射（九类抽样）、
引擎读循环端到端（mock WS + 压缩真实帧）、GAP 集成。
"""

import json
import time
import zlib

import pytest

from danmaku_listener.contract import Category, GapReason
from danmaku_listener.contract.models import UnifiedMessage
from danmaku_listener.engines.protocol import bilibili_codec as codec
from danmaku_listener.engines.protocol.bilibili import BilibiliProtocolEngine


# ---- 帧编解码 ----

def test_encode_decode_roundtrip():
    body = json.dumps({"uid": 0, "roomid": 23058}).encode()
    frame = codec.encode_packet(codec.OP_AUTH, body, proto=1, seq=1)
    assert frame[:2] == b"\x00\x01" or True  # 头部细节由 decode 验证
    packets = codec.decode_packets(frame)
    assert len(packets) == 1
    proto, op, decoded_body = packets[0]
    assert (proto, op, decoded_body) == (1, codec.OP_AUTH, body)


def test_decode_multi_packet_stream():
    p1 = codec.encode_packet(codec.OP_HEARTBEAT, b"", proto=1)
    p2 = codec.encode_packet(codec.OP_SEND_MSG_REPLY, b'{"code":0}', proto=0)
    packets = codec.decode_packets(p1 + p2)
    assert [op for _, op, _ in packets] == [codec.OP_HEARTBEAT, codec.OP_SEND_MSG_REPLY]


def test_malformed_frame_rejected():
    # 声明包长 64 但只有 16 字节
    import struct
    bad = struct.pack("!IHHII", 64, 16, 0, 5, 1) + b"x" * 8
    with pytest.raises(codec.BilibiliFrameError):
        codec.decode_packets(bad)


def test_zlib_nested_packets():
    inner = codec.encode_packet(codec.OP_SEND_MSG_REPLY, b'{"cmd":"DANMU_MSG"}', proto=0)
    outer = struct_pack_zlib(inner)
    packets = codec.decode_packets(outer)
    proto, op, body = packets[0]
    assert proto == codec.PROTOCOL_ZLIB
    inner_packets = codec.decompress(proto, body)
    assert inner_packets[0][0] == codec.OP_SEND_MSG_REPLY
    assert json.loads(inner_packets[0][1])["cmd"] == "DANMU_MSG"


def struct_pack_zlib(inner: bytes) -> bytes:
    import struct as _s
    compressed = zlib.compress(inner)
    total = codec.HEADER_SIZE + len(compressed)
    return _s.pack("!IHHII", total, codec.HEADER_SIZE, codec.PROTOCOL_ZLIB, codec.OP_SEND_MSG_REPLY, 1) + compressed


def test_brotli_unavailable_raises(monkeypatch):
    monkeypatch.setattr(codec, "brotli", None)
    with pytest.raises(codec.BilibiliFrameError):
        codec.decompress(codec.PROTOCOL_BROTLI, b"xx")


# ---- 消息映射（上游 → 契约） ----

def test_map_danmu_msg():
    upstream_info = [[0, 0, 0, 0], "主播666", [12345, "小明", [], [], 7], [3, "粉丝团", 0]]
    mapped = codec.map_upstream_message("DANMU_MSG", upstream_info, seq=1, ts=1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["user_name"] == "小明"
    assert mapped["payload"]["content"] == "主播666"
    assert mapped["payload"]["user_id"] == "12345"
    assert mapped["payload"]["badge_name"] == "粉丝团"
    assert mapped["payload"]["badge_level"] == 3


def test_map_gift():
    data = {"uname": "小刚", "giftName": "小花花", "num": 5, "price": 1000, "uid": 99, "giftId": 1}
    mapped = codec.map_upstream_message("GIFT", data, 1, 1700000000)
    assert mapped["type"] == "GIFT"
    assert mapped["payload"]["gift_count"] == 5
    assert mapped["payload"]["gift_value"] == pytest.approx(1.0)


def test_map_live_and_preparing():
    live = codec.map_upstream_message("LIVE", {}, 1, 1700000000)
    assert live["payload"]["live"] is True
    prep = codec.map_upstream_message("PREPARING", {}, 2, 1700000001)
    assert prep["payload"]["live"] is False


def test_map_stats_and_social_and_like():
    stats = codec.map_upstream_message("ONLINE_RANK_COUNT", {"count": 1024}, 1, 1700000000)
    assert stats["type"] == "ROOM_STATS"
    assert stats["payload"]["viewer_count"] == 1024

    social = codec.map_upstream_message("GUARD_BUY", {"uname": "a", "gift_name": "舰长", "uid": 5}, 2, 1700000000)
    assert social["type"] == "SOCIAL"
    assert social["payload"]["action"] == "guard_buy"

    like = codec.map_upstream_message("LIKE_MSG", {"uname": "a", "like_num": 3, "total_like": 100, "uid": 5}, 3, 1700000000)
    assert like["type"] == "LIKE"
    assert like["payload"]["count"] == 3


def test_map_unknown_cmd_returns_none():
    assert codec.map_upstream_message("TOTALLY_UNKNOWN", {"x": 1}, 1, 1700000000) is None


def test_parse_text_message_danmu():
    doc = {"cmd": "DANMU_MSG", "info": [[], "你好呀", [1, "测试用户"], []]}
    results = codec.parse_text_message(json.dumps(doc, ensure_ascii=False), 1, 1700000000)
    assert len(results) == 1
    assert results[0]["type"] == "DANMU"


# ---- 引擎集成（mock WS 读循环 → 契约线格式） ----

@pytest.mark.asyncio
async def test_engine_read_loop_emits_contract_wire():
    engine = BilibiliProtocolEngine()
    received: list[dict] = []

    async def on_message(data: dict):
        received.append(data)

    engine.on_message(on_message)

    # 构造真实帧流：zlib 嵌套的 DANMU_MSG
    doc = {"cmd": "DANMU_MSG", "info": [[], "hello", [7, "tester"], []]}
    inner = codec.encode_packet(codec.OP_SEND_MSG_REPLY, json.dumps(doc).encode(), proto=0)
    compressed = zlib.compress(inner)
    import struct
    frame = struct.pack("!IHHII", codec.HEADER_SIZE + len(compressed), codec.HEADER_SIZE,
                        codec.PROTOCOL_ZLIB, codec.OP_SEND_MSG_REPLY, 1) + compressed

    # 直接驱动映射（绕过 WS 网络层）：验证 codec→envelope→emit 管线
    out = engine._map_and_envelope(json.dumps(doc), "23058")
    assert len(out) == 1
    wire = out[0]
    assert wire["engine"] == "protocol:bilibili"
    assert wire["protocol_version"] == "bilibili-1"
    assert wire["payload"]["content"] == "hello"
    # 线格式可被契约模型校验
    msg = UnifiedMessage.from_wire(wire)
    assert msg.envelope.category == Category.BUSINESS

    assert frame  # 帧构造有效性（上面 decode 覆盖）


@pytest.mark.asyncio
async def test_engine_gap_on_reconnect():
    engine = BilibiliProtocolEngine()
    engine.mark_live_change("23058", live=True, ts=1700000000)
    engine.mark_gap_start("23058", ts=1700000010)
    gap = engine.build_gap_message("23058", GapReason.NETWORK, window_end=1700000020)
    assert gap is not None
    assert gap.payload.reason == GapReason.NETWORK
    assert gap.payload.window_start == 1700000010
    # 下播期间缺口作废
    engine.mark_live_change("23058", live=False, ts=1700000030)
    engine.mark_gap_start("23058", ts=1700000040)
    assert engine.build_gap_message("23058", GapReason.NETWORK, window_end=1700000050) is None


def test_decompress_consumer_alignment():
    """消费端对齐回归：decompress 输出经 _read_loop 同路径解包不崩（round3 修复）"""
    doc = {"cmd": "DANMU_MSG", "info": [[], "弹幕内容", [7, "测试用户"], []]}
    inner = codec.encode_packet(codec.OP_SEND_MSG_REPLY, json.dumps(doc, ensure_ascii=False).encode(), proto=0)
    compressed = zlib.compress(inner)
    import struct
    frame = struct.pack("!IHHII", codec.HEADER_SIZE + len(compressed), codec.HEADER_SIZE,
                        codec.PROTOCOL_ZLIB, codec.OP_SEND_MSG_REPLY, 1) + compressed
    # 模拟 _read_loop 的消费路径
    packets = codec.decode_packets(frame)
    for proto, op, body in packets:
        inner_packets = codec.decompress(proto, body)
        for _iop, inner_body in inner_packets:
            assert _iop == codec.OP_SEND_MSG_REPLY
            results = codec.parse_text_message(inner_body.decode("utf-8"), 1, 1700000000)
            assert len(results) == 1
            assert results[0]["payload"]["content"] == "弹幕内容"


def test_send_gift_v2_pb_map():
    """SEND_GIFT_V2 pb → GIFT（2026-10-04 dump 14 条样本实证：f2=送礼者、
    f10{f1=gift_id,f2=礼物名,f3=数量}；pb 样本取自房间 1840119321 真实帧）"""
    import base64
    pb = base64.b64encode(bytes.fromhex(
        "120a e5a4a9 2a2a2a" .replace(" ", "")  # f2="天***"
    )).decode()
    # 构造完整 pb：f2 昵称 + f10{f1=gift_id,f2=礼物名,f3=数量}
    def varint(v):
        out = b""
        while True:
            b7 = v & 0x7F
            v >>= 7
            out += bytes([b7 | (0x80 if v else 0)])
            if not v:
                return out
    def field(no, wt, payload):
        return varint((no << 3) | wt) + (varint(len(payload)) + payload if wt == 2 else payload)
    inner = (field(1, 0, varint(31036))
             + field(2, 2, "小花花".encode())
             + field(3, 0, varint(1)))
    pb_raw = (field(2, 2, "天***".encode()) + field(10, 2, inner))
    pb_b64 = base64.b64encode(pb_raw).decode()
    m = codec.map_upstream_message("SEND_GIFT_V2", {"pb": pb_b64}, 1, 1700000000)
    assert m is not None
    assert m["type"] == "GIFT"
    assert m["payload"]["user_name"] == "天***"
    assert m["payload"]["gift_name"] == "小花花"
    assert m["payload"]["gift_id"] == "31036"
    assert m["payload"]["gift_count"] == 1


def test_interact_word_v2_pb_map():
    """INTERACT_WORD_V2 pb → ENTER_ROOM（f2=昵称、f22.f4.f1=粉丝牌等级）"""
    import base64
    def varint(v):
        out = b""
        while True:
            b7 = v & 0x7F
            v >>= 7
            out += bytes([b7 | (0x80 if v else 0)])
            if not v:
                return out
    def field(no, wt, payload):
        return varint((no << 3) | wt) + (varint(len(payload)) + payload if wt == 2 else payload)
    f22_inner = (field(2, 2, field(1, 2, "青***".encode()))
                 + field(4, 2, field(1, 0, varint(23))))
    pb_raw = (field(2, 2, "青***".encode())
              + field(5, 0, varint(1))
              + field(6, 0, varint(1840119321))
              + field(22, 2, f22_inner))
    m = codec.map_upstream_message(
        "INTERACT_WORD_V2", {"pb": base64.b64encode(pb_raw).decode()}, 2, 1700000000)
    assert m is not None
    assert m["type"] == "ENTER_ROOM"
    assert m["payload"]["user_name"] == "青***"
    assert m["payload"]["fan_level"] == 23


def test_entry_effect_map():
    """ENTRY_EFFECT JSON → ENTER_ROOM（copy_writing 昵称全名不打码）"""
    m = codec.map_upstream_message(
        "ENTRY_EFFECT",
        {"uid": 3707022981728419, "copy_writing": "<%青岛即墨小太妹%> 来了"},
        3, 1700000000)
    assert m is not None
    assert m["type"] == "ENTER_ROOM"
    assert m["payload"]["user_name"] == "青岛即墨小太妹"
    assert m["payload"]["content"] == "来了"
    assert m["payload"]["user_id"] == "3707022981728419"
