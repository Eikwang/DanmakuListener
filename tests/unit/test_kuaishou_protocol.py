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
    frame = codec.build_heartbeat()
    payload_type, compression, payload = codec.decode_socket_message(frame)
    assert payload_type == ks_pb2.PayloadType.CS_HEARTBEAT


def test_enter_room_frame():
    frame = codec.build_enter_room("test-token", "23058")
    payload_type, compression, payload = codec.decode_socket_message(frame)
    assert payload_type == ks_pb2.PayloadType.CS_ENTER_ROOM
    enter = ks_pb2.CSWebEnterRoom()
    enter.ParseFromString(payload)
    assert enter.payload.token == "test-token"
    # liveStreamId 来自 livedetail 接口（非房间号）；pageId 随机生成（非固定值）
    assert enter.payload.liveStreamId == "23058"
    assert enter.payload.pageId and enter.payload.pageId != "1"


def test_aes_unsupported_flagged():
    with pytest.raises(ValueError):
        codec.decompress_payload(3, b"xx")
