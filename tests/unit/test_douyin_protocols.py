"""抖音平台协议定义测试

验证抖音 Protobuf 消息类型的正确解析。
"""

import pytest
from datetime import datetime

from danmaku_listener.adapters.protocols.message_types import (
    DouyinMessageType,
    parse_message_type,
)


class TestDouyinMessageTypes:
    """抖音消息类型测试"""

    def test_chat_message_type(self):
        """测试普通弹幕消息类型识别"""
        result = parse_message_type("WebcastChatMessage")
        assert result == DouyinMessageType.CHAT

    def test_gift_message_type(self):
        """测试礼物消息类型识别"""
        result = parse_message_type("WebcastGiftMessage")
        assert result == DouyinMessageType.GIFT

    def test_like_message_type(self):
        """测试点赞消息类型识别"""
        result = parse_message_type("WebcastLikeMessage")
        assert result == DouyinMessageType.LIKE

    def test_member_message_type(self):
        """测试进房消息类型识别"""
        result = parse_message_type("WebcastMemberMessage")
        assert result == DouyinMessageType.MEMBER

    def test_social_message_type(self):
        """测试关注消息类型识别"""
        result = parse_message_type("WebcastSocialMessage")
        assert result == DouyinMessageType.SOCIAL

    def test_room_user_seq_message_type(self):
        """测试统计消息类型识别"""
        result = parse_message_type("WebcastRoomUserSeqMessage")
        assert result == DouyinMessageType.ROOM_STATS

    def test_control_message_type(self):
        """测试控制消息类型识别"""
        result = parse_message_type("WebcastControlMessage")
        assert result == DouyinMessageType.CONTROL

    def test_fansclub_message_type(self):
        """测试粉丝团消息类型识别"""
        result = parse_message_type("WebcastFansclubMessage")
        assert result == DouyinMessageType.FANSCLUB

    def test_unknown_message_type(self):
        """测试未知消息类型返回 NONE"""
        result = parse_message_type("UnknownMessage")
        assert result == DouyinMessageType.UNKNOWN

    def test_empty_message_type(self):
        """测试空消息类型返回 NONE"""
        result = parse_message_type("")
        assert result == DouyinMessageType.UNKNOWN

    def test_none_message_type(self):
        """测试 None 消息类型返回 NONE"""
        result = parse_message_type(None)
        assert result == DouyinMessageType.UNKNOWN

    def test_all_message_types_covered(self):
        """测试所有预期的消息类型都被覆盖"""
        expected_types = [
            "WebcastChatMessage",
            "WebcastGiftMessage",
            "WebcastLikeMessage",
            "WebcastMemberMessage",
            "WebcastSocialMessage",
            "WebcastRoomUserSeqMessage",
            "WebcastControlMessage",
            "WebcastFansclubMessage",
        ]

        for msg_type in expected_types:
            result = parse_message_type(msg_type)
            assert result != DouyinMessageType.UNKNOWN, f"{msg_type} should be recognized"