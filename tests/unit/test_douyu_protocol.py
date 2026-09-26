"""斗鱼协议编解码与引擎测试（阶段 3a）"""

import struct

import pytest

from danmaku_listener.engines.protocol import douyu_codec as codec


# ---- 转义与消息体 ----

def test_escape_unescape_roundtrip():
    assert codec._escape("a/b@c") == "a@Sb@Ac"
    assert codec._unescape("a@Sb@Ac") == "a/b@c"


def test_encode_decode_body_roundtrip():
    body = codec.encode_body({"type": "chatmsg", "txt": "你好/世界", "nn": "用户@名"})
    fields = codec.decode_body(body)
    assert fields == {"type": "chatmsg", "txt": "你好/世界", "nn": "用户@名"}


def test_body_null_terminator():
    body = codec.encode_body({"type": "heartbeat"})
    assert body.endswith(b"\x00")
    assert b"type@=heartbeat/" in body


# ---- 帧 ----

def test_packet_roundtrip():
    body = codec.encode_body({"type": "heartbeat"})
    packet = codec.encode_packet(body)
    # 头部：小端 长度+重复
    msg_len, repeat, msg_type, crypt, reserved = codec.PACKET_HEADER.unpack_from(packet)
    assert msg_len == repeat == len(body) + 8
    assert msg_type == codec.CLIENT_TYPE
    assert crypt == reserved == 0
    packets = codec.decode_packets(packet)
    assert packets == [{"type": "heartbeat"}]


def test_decode_server_packets_only():
    server_body = codec.encode_body({"type": "chatmsg", "nn": "a", "txt": "b"})
    client_body = codec.encode_body({"type": "heartbeat"})
    server_pkt = codec.encode_packet(server_body, client=False)
    client_pkt = codec.encode_packet(client_body, client=True)
    packets = codec.decode_packets(server_pkt + client_pkt)
    assert len(packets) == 2
    assert packets[0]["type"] == "chatmsg"
    assert packets[0]["_packet_type"] == codec.SERVER_TYPE
    assert packets[1]["_packet_type"] == codec.CLIENT_TYPE


def test_malformed_frame_rejected():
    bad = struct.pack("<IIHBB", 64, 64, 690, 0, 0) + b"x" * 8
    with pytest.raises(codec.DouyuFrameError):
        codec.decode_packets(bad)


# ---- 握手 ----

def test_login_and_join():
    login = codec.build_login(23058)
    fields = codec.decode_body(login[8:])
    assert fields["type"] == "loginreq"
    assert fields["roomid"] == 23058
    join = codec.build_join_group(23058)
    fields = codec.decode_body(join[8:])
    assert fields == {"type": "joingroup", "rid": 23058, "gid": -9999}


# ---- 映射 ----

def test_map_chatmsg():
    mapped = codec.map_upstream({"type": "chatmsg", "nn": "小明", "txt": "666", "uid": "1",
                                 "bnn": "粉丝团", "bl": "12"}, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["badge_level"] == 12


def test_map_gift_enter_stats():
    gift = codec.map_upstream({"type": "dgb", "nn": "a", "gs": "火箭", "gn": "2", "uid": "1"}, 1, 1700000000)
    assert gift["type"] == "GIFT" and gift["payload"]["gift_count"] == 2

    enter = codec.map_upstream({"type": "uenter", "nn": "a", "uid": "1"}, 2, 1700000000)
    assert enter["type"] == "ENTER_ROOM"

    stats = codec.map_upstream({"type": "rss", "vc": "10240"}, 3, 1700000000)
    assert stats["type"] == "ROOM_STATS"
    assert stats["payload"]["viewer_count"] == 1024  # 除以 10 口径


def test_map_unknown_returns_none():
    assert codec.map_upstream({"type": "noble_num_info"}, 1, 1700000000) is None
