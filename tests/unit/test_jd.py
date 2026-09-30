"""京东引擎测试——参数归一/帧解析/消息映射/信封/端到端"""

import asyncio
import json

import pytest

from danmaku_listener.engines.protocol.jd import (
    JDParseError,
    JDProtocolEngine,
    extract_room_id,
    map_jd_message,
    parse_jd_frame,
)


def test_extract_room_id():
    assert extract_room_id("12345678") == "12345678"
    assert extract_room_id(
        "https://live.jd.com/pop/980123.html?popId=980123") == "980123"
    # 链接无数字特征：截断作标识（页面直达用原链接）
    assert extract_room_id("https://live.jd.com/pop/abc.html") == "https://live.jd.com/pop/abc.html"
    with pytest.raises(JDParseError):
        extract_room_id("not-a-room")


def test_parse_jd_frame_shapes():
    """调研数据点形态：顶层 type=chat_group_message 弹幕帧"""
    frame = json.dumps({
        "aid": "dongdong", "type": "chat_group_message",
        "body": {"groupid": "980123", "nickName": "观众甲",
                 "content": "主播好", "ext": {"appid": "jd.mall"}},
    })
    out = parse_jd_frame(frame)
    assert len(out) >= 1
    assert any(o.get("nickName") == "观众甲" for o in out)

    # msgs 数组帧
    arr = json.dumps({"msgs": [
        {"type": "chat_group_message", "nickName": "乙", "content": "ok"}]})
    out2 = parse_jd_frame(arr)
    assert out2 and out2[0]["content"] == "ok"

    # 噪声过滤：非 JSON / 其他 WS 帧 / 无 type 特征
    assert parse_jd_frame("not json") == []
    assert parse_jd_frame(json.dumps({"t": 4, "b": {}})) == []
    assert parse_jd_frame(b"\x00\x01") == []


def test_map_jd_message():
    ts, seq = 1700000000, 1
    danmu = map_jd_message({"type": "chat_group_message",
                            "nickName": "观众甲", "content": "主播好"}, seq, ts)
    assert (danmu["type"], danmu["payload"]["content"],
            danmu["payload"]["user_name"]) == ("DANMU", "主播好", "观众甲")

    # 字段多候选兼容
    alt = map_jd_message({"type": "chat_group_message",
                          "nickname": "乙", "msg": "hello"}, seq, ts)
    assert alt["payload"]["user_name"] == "乙"
    assert alt["payload"]["content"] == "hello"

    enter = map_jd_message({"type": "join_live_broadcast",
                            "nickName": "路人"}, seq, ts)
    assert enter["type"] == "ENTER_ROOM"

    # 无昵称/无内容 → 不 emit
    assert map_jd_message({"type": "chat_group_message", "content": "x"}, seq, ts) is None
    assert map_jd_message({"type": "other", "nickName": "x", "content": "y"}, seq, ts) is None


def test_envelope_platform_is_jd():
    eng = JDProtocolEngine()
    env = eng._envelope(
        "123", {"category": "business", "type": "DANMU", "seq": 1,
                "timestamp": 0, "payload": {"type": "DANMU"}})
    assert env["platform"] == "jd"
    assert env["engine"] == "page:jd"
    assert env["protocol_version"] == "jd-1"
    for k in ("contract_version", "category", "platform", "room_id",
              "seq", "timestamp", "engine", "protocol_version", "payload"):
        assert k in env


@pytest.mark.asyncio
async def test_on_ws_frame_emits():
    """framereceived dict payload → emit DANMU + 刷新静默计时"""
    eng = JDProtocolEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    frame = json.dumps({"aid": "dongdong", "type": "chat_group_message",
                        "body": {"nickName": "观众甲", "content": "测试弹幕"}})
    before = eng._last_frame_box.setdefault("r1", {"t": 0.0})["t"]
    await asyncio.sleep(0.01)
    await eng._on_ws_frame("r1", {"payload": frame})
    danmus = [m for m in got if m["type"] == "DANMU"]
    assert len(danmus) == 1
    assert danmus[0]["payload"]["user_name"] == "观众甲"
    assert danmus[0]["platform"] == "jd"
    assert eng._last_frame_box["r1"]["t"] > before


def test_engine_id():
    assert JDProtocolEngine().engine_id == "page:jd"
