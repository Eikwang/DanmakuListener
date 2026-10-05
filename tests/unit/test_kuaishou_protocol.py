"""快手协议编解码与引擎测试（阶段 4）——pb2 构造真实 protobuf 做 round-trip"""

import gzip

import pytest

from danmaku_listener.engines.protocol import ks_pb2, kuaishou_codec as codec


def _make_feed_push() -> bytes:
    """用 pb2 构造真实 SCWebFeedPush（压缩 GZIP）"""
    push = ks_pb2.SCWebFeedPush()
    comment = push.commentFeeds.add()
    comment.id = "c1"
    comment.user.principalId = "u-1"
    comment.user.userName = "小明"
    comment.content = "666"

    like = push.likeFeeds.add()
    like.id = "l1"
    like.user.userName = "小刚"

    gift = push.giftFeeds.add()
    gift.id = "g1"
    gift.user.userName = "小刚"
    gift.giftId = 1001
    gift.batchSize = 2
    gift.comboCount = 3

    push.displayWatchingCount = "1.2万"
    push.displayLikeCount = "3400"

    inner = push.SerializeToString()
    compressed = gzip.compress(inner)
    sm = ks_pb2.SocketMessage()
    sm.payloadType = ks_pb2.PayloadType.SC_FEED_PUSH
    sm.compressionType = ks_pb2.CompressionType.GZIP
    sm.payload = compressed
    return sm.SerializeToString()


def test_decode_socket_message_roundtrip():
    frame = _make_feed_push()
    payload_type, compression, payload = codec.decode_socket_message(frame)
    assert payload_type == ks_pb2.PayloadType.SC_FEED_PUSH
    assert compression == ks_pb2.CompressionType.GZIP
    assert payload[:2] == b"\x1f\x8b"  # gzip magic


def test_map_feed_push_to_contract():
    frame = _make_feed_push()
    results = codec.map_socket_message(frame, seq_start=0, ts=1700000000)
    types = [r["type"] for r in results]
    assert types.count("DANMU") == 1
    assert types.count("LIKE") == 1
    assert types.count("GIFT") == 1
    assert types.count("ROOM_STATS") == 1

    danmu = next(r for r in results if r["type"] == "DANMU")
    assert danmu["payload"]["user_name"] == "小明"
    assert danmu["msg_id"] == "c1"  # 跨路线去重键

    stats = next(r for r in results if r["type"] == "ROOM_STATS")
    assert stats["payload"]["viewer_count"] == 12000  # 1.2万解析
    assert stats["payload"]["total_likes"] == 3400

    gift = next(r for r in results if r["type"] == "GIFT")
    assert gift["payload"]["gift_count"] == 6  # batchSize 2 × combo 3


def test_seq_monotonic_in_batch():
    frame = _make_feed_push()
    results = codec.map_socket_message(frame, seq_start=10, ts=1700000000)
    seqs = [r["seq"] for r in results]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_heartbeat_frame():
    frame = codec.build_heartbeat(1700000000000)
    payload_type, compression, payload = codec.decode_socket_message(frame)
    assert payload_type == ks_pb2.PayloadType.CS_HEARTBEAT
    # 2026-09 扁平结构：payload = field1 varint 时间戳
    assert payload == b"\x08" + codec._pb_varint(1700000000000)


def test_enter_room_frame():
    frame = codec.build_enter_room("test-token", "23058", page_id="abc123")
    payload_type, compression, payload = codec.decode_socket_message(frame)
    assert payload_type == ks_pb2.PayloadType.CS_ENTER_ROOM
    # 2026-09 扁平结构：field1=token, field2=liveStreamId, field7=pageId
    assert codec._pb_field_str(1, "test-token") in payload
    assert codec._pb_field_str(2, "23058") in payload
    assert codec._pb_field_str(7, "abc123") in payload
    # token 必须是 payload 首字段（页面真实帧对照——嵌套形式被 SC_ERROR code=60 拒绝）
    assert payload.startswith(b"\x0a")


def test_aes_unsupported_flagged():
    with pytest.raises(ValueError):
        codec.decompress_payload(3, b"xx")


def test_parse_display_dirty_formats():
    """展示计数解析增强（2026-10-05 快手空统计行修复）"""
    parse = codec._parse_display
    assert parse("1.2万") == 12000
    assert parse("1.3万人") == 13000        # 脏后缀
    assert parse("13,000") == 13000         # 千分位
    assert parse("13000") == 13000
    assert parse("1.08亿") == 108000000
    assert parse("") is None
    assert parse("--") is None              # 完全无法解析
    assert parse("万") is None


def test_map_feed_push_all_unparsable_no_emit():
    """display 双解析失败 → 不 emit 空统计帧（前端空行根因）"""
    push = ks_pb2.SCWebFeedPush()
    push.displayWatchingCount = "--"
    push.displayLikeCount = "n/a"
    results = codec.map_feed_push(push.SerializeToString(), 0, 1700000000)
    assert not [r for r in results if r["type"] == "ROOM_STATS"]


def test_map_feed_push_partial_parsable_emits():
    """单边解析成功 → 正常 emit（None 侧不带垃圾占位）"""
    push = ks_pb2.SCWebFeedPush()
    push.displayWatchingCount = "1.3万人"
    push.displayLikeCount = ""
    results = codec.map_feed_push(push.SerializeToString(), 0, 1700000000)
    stats = [r for r in results if r["type"] == "ROOM_STATS"]
    assert len(stats) == 1
    assert stats[0]["payload"]["viewer_count"] == 13000
    assert stats[0]["payload"]["total_likes"] is None
