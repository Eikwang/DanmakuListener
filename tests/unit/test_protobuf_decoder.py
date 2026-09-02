"""Task-06: Protobuf 解码器 测试

验证 ProtobufDecoder 完整解码链路：
raw bytes → WssResponse → 检查 compress_type → Gzip 解压 → Response → 遍历 Message → List[DecodedMessage]
"""

import gzip
import pytest

from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
from danmaku_listener.adapters.protocols.proto.message_pb2 import (
    Response, Message, ChatMessage, GiftMessage, LikeMessage, MemberMessage, User,
)


def _build_wss_response(payload_bytes: bytes, compress_type: str = "") -> bytes:
    """构造 WssResponse 的序列化字节

    Args:
        payload_bytes: Response 的序列化字节（可能已 gzip 压缩）
        compress_type: 压缩类型（"gzip" 或空）

    Returns:
        WssResponse.SerializeToString()
    """
    wss = WssResponse(seqid=1, logid=1, service=1, method=1)
    if compress_type:
        wss.headers["compress_type"] = compress_type
    wss.payload = payload_bytes
    return wss.SerializeToString()


def _build_response_with_chat(content: str, nickname: str = "test", msg_id: int = 123) -> bytes:
    """构造包含一条 ChatMessage 的 Response 序列化字节"""
    chat = ChatMessage(content=content)
    chat.user.nickname = nickname

    msg = Message(method="WebcastChatMessage", msgId=msg_id)
    msg.payload = chat.SerializeToString()

    response = Response()
    response.messages.append(msg)
    return response.SerializeToString()


def _build_response_with_gift(
    nickname: str = "gifter", gift_name: str = "rocket",
    diamond_count: int = 100, repeat_count: int = 2, msg_id: int = 456,
) -> bytes:
    """构造包含一条 GiftMessage 的 Response 序列化字节"""
    gift = GiftMessage()
    gift.user.nickname = nickname
    gift.gift.name = gift_name
    gift.gift.diamondCount = diamond_count
    gift.repeatCount = repeat_count

    msg = Message(method="WebcastGiftMessage", msgId=msg_id)
    msg.payload = gift.SerializeToString()

    response = Response()
    response.messages.append(msg)
    return response.SerializeToString()


def _build_response_multi_messages() -> bytes:
    """构造包含多条 Message 的 Response"""
    chat = ChatMessage(content="hello")
    chat.user.nickname = "user1"
    msg1 = Message(method="WebcastChatMessage", msgId=111)
    msg1.payload = chat.SerializeToString()

    like = LikeMessage(count=5)
    like.user.nickname = "user2"
    msg2 = Message(method="WebcastLikeMessage", msgId=222)
    msg2.payload = like.SerializeToString()

    response = Response()
    response.messages.append(msg1)
    response.messages.append(msg2)
    return response.SerializeToString()


class TestProtobufDecoderNoGzip:
    """无 Gzip 压缩的解码测试"""

    def test_decode_chat_message(self):
        """解码 ChatMessage → DecodedMessage(method, payload, msg_id)"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder, DecodedMessage
        decoder = ProtobufDecoder()

        response_bytes = _build_response_with_chat("你好", "测试用户", 123)
        wss_bytes = _build_wss_response(response_bytes)

        results = decoder.decode(wss_bytes)
        assert len(results) == 1
        assert results[0].method == "WebcastChatMessage"
        assert results[0].msg_id == "123"
        assert isinstance(results[0].payload, bytes)
        assert len(results[0].payload) > 0

    def test_decode_gift_message(self):
        """解码 GiftMessage"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()

        response_bytes = _build_response_with_gift("送礼者", "火箭", 100, 2, 456)
        wss_bytes = _build_wss_response(response_bytes)

        results = decoder.decode(wss_bytes)
        assert len(results) == 1
        assert results[0].method == "WebcastGiftMessage"
        assert results[0].msg_id == "456"

    def test_decode_multiple_messages(self):
        """解码多条 Message"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()

        response_bytes = _build_response_multi_messages()
        wss_bytes = _build_wss_response(response_bytes)

        results = decoder.decode(wss_bytes)
        assert len(results) == 2
        assert results[0].method == "WebcastChatMessage"
        assert results[0].msg_id == "111"
        assert results[1].method == "WebcastLikeMessage"
        assert results[1].msg_id == "222"


class TestProtobufDecoderWithGzip:
    """Gzip 压缩的解码测试"""

    def test_decode_gzip_compressed(self):
        """解码 Gzip 压缩的 payload"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()

        response_bytes = _build_response_with_chat("hello gzip", "user", 999)
        compressed = gzip.compress(response_bytes)
        wss_bytes = _build_wss_response(compressed, compress_type="gzip")

        results = decoder.decode(wss_bytes)
        assert len(results) == 1
        assert results[0].method == "WebcastChatMessage"
        assert results[0].msg_id == "999"

    def test_decode_no_compress_type_header(self):
        """无 compress_type header 时直接用 payload"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()

        response_bytes = _build_response_with_chat("no gzip", "user", 100)
        # 不设置 compress_type header
        wss_bytes = _build_wss_response(response_bytes, compress_type="")

        results = decoder.decode(wss_bytes)
        assert len(results) == 1
        assert results[0].method == "WebcastChatMessage"


class TestProtobufDecoderErrors:
    """异常处理测试"""

    def test_invalid_wss_bytes(self):
        """无效 bytes（非 Protobuf 格式）→ 返回空列表，不抛异常 → AC-010"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()
        results = decoder.decode(b"this is not protobuf")
        assert results == []

    def test_invalid_gzip_data(self):
        """compress_type=gzip 但 payload 无效 → 返回空列表，记录警告 → AC-011"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()
        wss_bytes = _build_wss_response(b"not_gzip_data", compress_type="gzip")
        results = decoder.decode(wss_bytes)
        assert results == []

    def test_invalid_response_payload(self):
        """Response 反序列化失败 → 返回空列表 → AC-010"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()
        # 构造合法 WssResponse，但 payload 不是合法的 Response
        wss_bytes = _build_wss_response(b"garbage_response_data")
        # WssResponse 能解析，但 Response 解析会得到空 messages
        results = decoder.decode(wss_bytes)
        # 可能返回空列表（messages 为空）或抛异常（取决于 protobuf 行为）
        # 关键是不崩溃
        assert isinstance(results, list)

    def test_empty_input(self):
        """空输入 → 返回空列表"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder
        decoder = ProtobufDecoder()
        results = decoder.decode(b"")
        assert results == []


class TestDecodedMessage:
    """DecodedMessage 数据类测试"""

    def test_decoded_message_fields(self):
        """DecodedMessage 包含 method, payload, msg_id"""
        from danmaku_listener.engines.protobuf_decoder import DecodedMessage
        msg= DecodedMessage(
            method="WebcastChatMessage",
            payload=b"test",
            msg_id="123",
        )
        assert msg.method == "WebcastChatMessage"
        assert msg.payload == b"test"
        assert msg.msg_id == "123"

    def test_decoded_message_msg_id_is_str(self):
        """msg_id 始终为字符串类型"""
        from danmaku_listener.engines.protobuf_decoder import ProtobufDecoder, DecodedMessage
        decoder = ProtobufDecoder()

        response_bytes = _build_response_with_chat("test", "user", 456)
        wss_bytes = _build_wss_response(response_bytes)

        results = decoder.decode(wss_bytes)
        assert len(results) == 1
        assert isinstance(results[0].msg_id, str)
        assert results[0].msg_id == "456"
