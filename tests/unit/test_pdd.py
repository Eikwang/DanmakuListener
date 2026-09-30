"""拼多多引擎测试——解码链/映射/信封/端到端（mini pb 编码器构造真实帧）"""

import asyncio
import gzip
import json
import struct

import pytest

from danmaku_listener.engines.protocol.pdd import (
    PDDParseError,
    PDDProtocolEngine,
    decode_pdd_frame,
    extract_room_id,
    map_pdd_message,
)


# ---- 测试辅助：mini protobuf 编码器（构造真实下行帧形态） ----

def _pb_varint(value: int) -> bytes:
    out = b""
    while True:
        b = value & 0x7F
        value >>= 7
        out += bytes([b | (0x80 if value else 0)])
        if not value:
            return out


def _pb_field(field_no: int, wire: int, data: bytes) -> bytes:
    return _pb_varint((field_no << 3) | wire) + (
        _pb_varint(len(data)) + data if wire == 2 else data)


def _build_frame(biz_obj, compress: int = 0) -> bytes:
    """构造 16 字节包头 + TitanPayload(field1=command,field10=body,field14=compress)
    + MulticastLite(field1=bizType,field4=payload) + JSON"""
    payload = json.dumps(biz_obj, ensure_ascii=False).encode("utf-8")
    multicast = _pb_field(1, 0, _pb_varint(40)) + _pb_field(4, 2, payload)
    body = gzip.compress(multicast) if compress == 1 else multicast
    titan = (_pb_field(1, 2, b"livestream.push")
             + _pb_field(10, 2, body)
             + _pb_field(14, 0, _pb_varint(compress)))
    header = struct.pack(">hhiii", 1, 100, 0, 0, len(titan))
    return header + titan


def test_extract_room_id():
    assert extract_room_id("1234567890") == "1234567890"
    assert extract_room_id("https://mobile.yangkeduo.com/live.html?xxx=1").startswith("https://")
    with pytest.raises(PDDParseError):
        extract_room_id("not-a-room")


def test_decode_pdd_frame_plain():
    """无压缩帧：四层解码 → 业务对象"""
    biz = {"message_type": "live_chat",
           "message_data": {"live_chat_list": [
               {"uid": "u1", "nickname": "甲", "chat_message": "主播好"}]}}
    out = decode_pdd_frame(_build_frame(biz))
    assert len(out) == 1
    assert out[0]["message_data"]["live_chat_list"][0]["nickname"] == "甲"


def test_decode_pdd_frame_gzip():
    """compress=1：TitanPayload.body 先 gunzip 再解 MulticastLite"""
    biz = {"message_type": "live_chat",
           "message_data": {"live_chat_list": [
               {"uid": "u2", "nickname": "乙", "chat_message": "收到"}]}}
    out = decode_pdd_frame(_build_frame(biz, compress=1))
    assert out and out[0]["message_data"]["live_chat_list"][0]["uid"] == "u2"


def test_decode_pdd_frame_noise():
    """短帧/非 protobuf/JSON 失败/字符串帧 → 空列表（页内其他 WS 自然过滤）"""
    assert decode_pdd_frame(b"\x00\x01") == []
    assert decode_pdd_frame(b"\x00" * 32) == []
    assert decode_pdd_frame("plain text") == []
    assert decode_pdd_frame(None) == []


def test_map_pdd_message_live_chat_list():
    """调研兼容形态：live_chat_list[]（弹幕文本，实测样本未现——通道待诊断）"""
    ts, seq = 1700000000, 1
    msgs = map_pdd_message({
        "message_type": "live_chat",
        "message_data": {"live_chat_list": [
            {"uid": "u1", "nickname": "甲", "chat_message": "第一条"},
            {"uid": "u2", "nickname": "乙", "chat_message": "第二条"},
            {"uid": "u3", "chat_message": ""},  # 空内容跳过
        ]},
    }, seq, ts)
    assert len(msgs) == 2
    assert msgs[0]["type"] == "DANMU"
    assert msgs[0]["payload"]["user_name"] == "甲"
    assert msgs[1]["payload"]["content"] == "第二条"
    # 无 live_chat_list → 空
    assert map_pdd_message({"message_type": "other"}, seq, ts) == []


def test_map_pdd_message_sampled_types():
    """2026-09-30 实测形态 + 用户裁定范围（业务消息仅入场/弹幕/点赞三种）"""
    ts, seq = 1700000000, 1
    # 观看数 → ROOM_STATS
    stats = map_pdd_message({
        "message_type": "live_audience_num",
        "message_data": {"live_audience_num": 7736,
                         "live_audience_num_desc": "7736观看"}}, seq, ts)
    assert stats[0]["type"] == "ROOM_STATS"
    assert stats[0]["payload"]["viewer_count"] == 7736

    # 点赞总数 → ROOM_STATS 附加
    likes = map_pdd_message({
        "message_type": "show_thumb_up_count",
        "message_data": {"total_count": 83}}, seq, ts)
    assert likes[0]["payload"]["like_count"] == 83

    # 进场 notice
    enter = map_pdd_message({
        "message_type": "live_chat_notice",
        "message_data": {"live_chat_notice_list": [
            {"live_chat_notice_type": "enter",
             "live_chat_notice_data": {"user_list": [
                 {"uid": 4012262747511, "nickname": "宋***"}]}}]}}, seq, ts)
    assert enter[0]["type"] == "ENTER_ROOM"
    assert enter[0]["payload"]["user_name"] == "宋***"
    assert enter[0]["payload"]["user_id"] == "4012262747511"

    # 关注/开团 → 用户裁定不监听（SOCIAL 不映射）
    fav = map_pdd_message({
        "message_type": "live_chat_notice",
        "message_data": {"live_chat_notice_list": [
            {"live_chat_notice_type": "favorite",
             "live_chat_notice_data": {"user_list": [{"nickname": "欢***"}]}}]}},
        seq, ts)
    assert fav == []
    go = map_pdd_message({
        "message_type": "live_chat_notice",
        "message_data": {"live_chat_notice_list": [
            {"live_chat_notice_type": "group_open",
             "live_chat_notice_data": {}}]}}, seq, ts)
    assert go == []

    # ext 点赞保留；关注 116/购买 120 → 用户裁定不监听
    ext = map_pdd_message({
        "message_type": "live_chat_ext_v2",
        "message_data": {"live_chat_ext_list": [
            {"sub_type": 121, "body": {"title": "最***", "content": "点了赞"}},
            {"sub_type": 116, "body": {"title": "欢***", "content": "关注了主播"}},
            {"sub_type": 120, "body": {"title": "王***",
                                       "content": " 已购买2号商品"}},
        ]}}, seq, ts)
    assert len(ext) == 1
    assert ext[0]["type"] == "LIKE"
    assert ext[0]["payload"]["user_name"] == "最***"


def test_envelope_platform_is_pdd():
    eng = PDDProtocolEngine()
    env = eng._envelope(
        "123", {"category": "business", "type": "DANMU", "seq": 1,
                "timestamp": 0, "payload": {"type": "DANMU"}})
    assert env["platform"] == "pdd"
    assert env["engine"] == "page:pdd"
    assert env["protocol_version"] == "pdd-1"
    for k in ("contract_version", "category", "platform", "room_id",
              "seq", "timestamp", "engine", "protocol_version", "payload"):
        assert k in env


@pytest.mark.asyncio
async def test_on_ws_frame_emits():
    """framereceived 二进制帧 → 解码 emit DANMU + 刷新静默计时"""
    eng = PDDProtocolEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    frame = _build_frame({"message_type": "live_chat",
                          "message_data": {"live_chat_list": [
                              {"uid": "u9", "nickname": "观众甲",
                               "chat_message": "测试弹幕"}]}})
    before = eng._last_frame_box.setdefault("r1", {"t": 0.0})["t"]
    await asyncio.sleep(0.01)
    await eng._on_ws_frame("r1", {"payload": frame})
    danmus = [m for m in got if m["type"] == "DANMU"]
    assert len(danmus) == 1
    assert danmus[0]["payload"]["user_name"] == "观众甲"
    assert danmus[0]["payload"]["content"] == "测试弹幕"
    assert danmus[0]["platform"] == "pdd"
    assert eng._last_frame_box["r1"]["t"] > before


def test_engine_id():
    assert PDDProtocolEngine().engine_id == "page:pdd"
