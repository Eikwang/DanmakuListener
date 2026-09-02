"""Task-02: Protobuf 代码生成 测试

验证 protoc 生成的 Python 类可正常导入、实例化、序列化/反序列化。
"""

import pytest


class TestProtobufImports:
    """Protobuf 类导入测试"""

    def test_import_wss_response(self):
        """WssResponse 可导入"""
        from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
        assert WssResponse is not None

    def test_import_message_classes(self):
        """所有消息类可导入"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import (
            Response, Message, ChatMessage, GiftMessage, LikeMessage,
            MemberMessage, SocialMessage, ControlMessage,
            RoomUserSeqMessage, FansclubMessage,
        )
        assert Response is not None
        assert ChatMessage is not None
        assert GiftMessage is not None

    def test_import_from_package_init(self):
        """从包 __init__.py 导入"""
        from danmaku_listener.adapters.protocols.proto import (
            WssResponse, Response, ChatMessage, GiftMessage, User, GiftStruct,
        )
        assert WssResponse is not None
        assert ChatMessage is not None


class TestWssResponseSerialization:
    """WssResponse 序列化/反序列化测试"""

    def test_wss_response_instantiate(self):
        """WssResponse 可实例化"""
        from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
        wss = WssResponse()
        assert wss is not None

    def test_wss_response_set_fields(self):
        """WssResponse 可设置字段"""
        from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
        wss = WssResponse(seqid=1, payload=b"test")
        assert wss.seqid == 1
        assert wss.payload == b"test"

    def test_wss_response_serialize(self):
        """WssResponse 序列化返回非空 bytes"""
        from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
        wss = WssResponse(seqid=1, payload=b"test")
        serialized = wss.SerializeToString()
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0

    def test_wss_response_headers_map(self):
        """WssResponse headers 是 map 字段"""
        from danmaku_listener.adapters.protocols.proto.wss_pb2 import WssResponse
        wss = WssResponse()
        wss.headers["compress_type"] = "gzip"
        assert wss.headers["compress_type"] == "gzip"


class TestChatMessageSerialization:
    """ChatMessage 序列化/反序列化测试"""

    def test_chat_message_instantiate(self):
        """ChatMessage 可实例化"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import ChatMessage
        msg = ChatMessage()
        assert msg is not None

    def test_chat_message_set_content(self):
        """ChatMessage 可设置 content"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import ChatMessage
        msg = ChatMessage(content="hello")
        assert msg.content == "hello"

    def test_chat_message_serialize_deserialize(self):
        """ChatMessage 序列化后反序列化数据一致"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import ChatMessage
        msg = ChatMessage(content="hello")
        serialized = msg.SerializeToString()

        msg2 = ChatMessage()
        msg2.ParseFromString(serialized)
        assert msg2.content == "hello"

    def test_chat_message_with_user(self):
        """ChatMessage 可嵌套 User"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import ChatMessage, User
        msg = ChatMessage(content="你好")
        msg.user.nickname = "测试用户"
        serialized = msg.SerializeToString()

        msg2 = ChatMessage()
        msg2.ParseFromString(serialized)
        assert msg2.content == "你好"
        assert msg2.user.nickname == "测试用户"


class TestGiftMessageSerialization:
    """GiftMessage 序列化/反序列化测试"""

    def test_gift_message_with_gift_struct(self):
        """GiftMessage 可嵌套 GiftStruct"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import GiftMessage, User, GiftStruct
        msg = GiftMessage()
        msg.user.nickname = "送礼者"
        msg.gift.name = "火箭"
        msg.gift.diamondCount = 100
        msg.repeatCount = 2
        serialized = msg.SerializeToString()

        msg2 = GiftMessage()
        msg2.ParseFromString(serialized)
        assert msg2.user.nickname == "送礼者"
        assert msg2.gift.name == "火箭"
        assert msg2.gift.diamondCount == 100
        assert msg2.repeatCount == 2


class TestResponseWithMessages:
    """Response 包含 Message 列表的测试"""

    def test_response_with_chat_message(self):
        """Response 可包含 ChatMessage 类型的 Message"""
        from danmaku_listener.adapters.protocols.proto.message_pb2 import Response, Message, ChatMessage
        # 构造 ChatMessage payload
        chat = ChatMessage(content="hello")
        chat.user.nickname = "test"

        # 构造 Message
        msg = Message(method="WebcastChatMessage", msgId=123)
        msg.payload = chat.SerializeToString()

        # 构造 Response
        response = Response()
        response.messages.append(msg)

        serialized = response.SerializeToString()

        # 反序列化
        response2 = Response()
        response2.ParseFromString(serialized)
        assert len(response2.messages) == 1
        assert response2.messages[0].method == "WebcastChatMessage"
        assert response2.messages[0].msgId == 123

        # 反序列化内层 ChatMessage
        chat2 = ChatMessage()
        chat2.ParseFromString(response2.messages[0].payload)
        assert chat2.content == "hello"
        assert chat2.user.nickname == "test"
