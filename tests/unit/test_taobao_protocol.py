"""淘宝 mtop 协议测试（T5）——签名/混合解析/映射/凭证归一（离线，无网络）"""

import asyncio
import json

import pytest

from danmaku_listener.engines.protocol import taobao as tb
from danmaku_listener.engines.protocol.mtop import (
    MtopClient,
    extract_live_id,
    make_sign,
    parse_base64_mixed_message,
    strip_jsonp,
)
from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine


# ---- mtop 签名 ----

def test_make_sign():
    """md5("{token}&{t}&{appKey}&{data}")——TaobaoLiveWebFetcher 同构"""
    # 参考实现签名公式对照（固定样本，手工 md5 校验）
    import hashlib
    expected = hashlib.md5(b"abc123&1700000000000&12574478&{}").hexdigest()
    assert make_sign("abc123_1700000000", "1700000000000", "12574478", "{}") == expected


def test_strip_jsonp():
    assert json.loads(strip_jsonp('mtopjsonp7({"a":1})')) == {"a": 1}
    with pytest.raises(Exception):
        strip_jsonp("not jsonp")


# ---- base64 混合解析（powermsg 消息体）----

def test_parse_base64_mixed_single():
    payload = b"\x00\x01junk\x7b\"nick\": \"tester\", \"content\": \"hello\"\x7d"
    objs, raw = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs == [{"nick": "tester", "content": "hello"}]


def test_parse_base64_mixed_multi():
    payload = b"\x7b\"a\": 1\x7d mid \x7b\"b\": 2\x7d"
    objs, _ = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs == [{"a": 1}, {"b": 2}]


def test_parse_base64_string_escape():
    payload = b'\x7b"content": "say \\"hi\\" } not end"\x7d'
    objs, _ = parse_base64_mixed_message(__import__("base64").b64encode(payload).decode())
    assert objs and objs[0]["content"] == 'say "hi" } not end'


# ---- live_id 归一 ----

def test_extract_live_id():
    assert extract_live_id("785432123456") == "785432123456"
    assert extract_live_id("https://tbzb.taobao.com/live?liveId=785432123456") == "785432123456"
    with pytest.raises(ValueError):
        extract_live_id("not-a-live-id")


# ---- powermsg 映射（显式清单）----

def test_map_stats():
    obj = {"viewCountFormat": "1.2万", "onlineCount": 88, "totalCount": 1200}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "ROOM_STATS"
    assert mapped["payload"]["viewer_count"] == 88
    assert mapped["payload"]["total_view_count"] == 1200


def test_map_member_with_fan_level():
    obj = {"nick": "新人", "userid": "42", "flowSourceText": "分享",
           "identify": {"fanLevel": "5", "VIP_USER": "1"}}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "ENTER_ROOM"
    assert mapped["payload"]["fan_level"] == 5


def test_map_like():
    obj = {"value": {"dig": 3}}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["type"] == "LIKE"
    assert mapped["payload"]["count"] == 3


def test_map_stats_total_count_only():
    """1688 形态：totalCount 单键统计对象也映射 ROOM_STATS（修复 30s 假超时）"""
    obj = {"totalCount": 102835}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped is not None
    assert mapped["type"] == "ROOM_STATS"
    assert mapped["payload"]["total_view_count"] == 102835


def test_map_stats_online_count_zero_fallback():
    """onlineCount 恒 0（2026-10-03 用户实测"观看 0"根因，同 1688）——
    观看人数回退 totalCount（UV），累计浏览 pageViewCount（PV）"""
    obj = {"onlineCount": 0, "viewCountFormat": "1974 观看",
           "pageViewCount": 1974, "totalCount": 1193}
    mapped = TaobaoWebProtocolEngine._map_powermsg("123", obj, 1, 1700000000)
    assert mapped["payload"]["viewer_count"] == 1193
    assert mapped["payload"]["total_view_count"] == 1974


def test_map_chat_and_gift_by_subtype():
    eng = TaobaoWebProtocolEngine()
    chat = {"subType": 10001, "nick": "用户A", "userid": "7", "content": "主播好"}
    mapped = eng._map_powermsg("123", chat, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["content"] == "主播好"

    gift = {"subType": 10002, "nick": "土豪", "giftName": "小心心", "count": 5}
    mapped2 = eng._map_powermsg("123", gift, 2, 1700000000)
    assert mapped2["type"] == "GIFT"
    assert mapped2["payload"]["gift_name"] == "小心心"
    assert mapped2["payload"]["gift_count"] == 5


def test_map_unknown_dropped():
    eng = TaobaoWebProtocolEngine()
    assert eng._map_powermsg("123", {"randomKey": 1}, 1, 1700000000) is None


def test_map_comment():
    c = {"publisherNick": "评论者", "publisherId": "99", "content": "评论内容"}
    mapped = TaobaoWebProtocolEngine._map_comment("123", c, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["user_name"] == "评论者"


# ---- 生命周期 ----

@pytest.mark.asyncio
async def test_engine_lifecycle():
    eng = TaobaoWebProtocolEngine()
    assert eng.engine_id == "webws:taobao"

    async def fail_fetch(*a, **k):
        raise RuntimeError("taobao.credential.topic_failed: test")

    eng._fetch_credentials = fail_fetch
    await eng.start("123456")
    await asyncio.sleep(0.2)
    assert not eng._room_tasks["123456"].done()
    await eng.stop("123456")
    assert eng._stop_flags["123456"] is True


def test_protocol_version():
    assert tb.PROTOCOL_VERSION == "taobao-1"
