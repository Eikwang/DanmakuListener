"""小红书引擎测试——room_id 归一/WS 帧解析/消息映射/信封/端到端"""

import asyncio
import base64
import json

import pytest

from danmaku_listener.engines.protocol.xiaohongshu import (
    XiaohongshuEngine,
    XiaohongshuParseError,
    extract_room_id,
    map_custom_data,
    parse_ws_frame,
)


def _wrap_frame(cd_objs):
    """构造真实形态业务帧：t==4 → b.d.b[] → d=base64({"customData": json_str})"""
    items = [
        {"d": base64.b64encode(
            json.dumps({"customData": json.dumps(cd, ensure_ascii=False)},
                       ensure_ascii=False).encode()).decode()}
        for cd in cd_objs
    ]
    return json.dumps({"t": 4, "b": {"d": {"b": items}}})


def test_extract_room_id():
    assert extract_room_id("123456789012345") == "123456789012345"
    assert extract_room_id(
        "https://www.xiaohongshu.com/livestream/6789012345678?x=1") == "6789012345678"
    with pytest.raises(XiaohongshuParseError):
        extract_room_id("not-a-room")
    with pytest.raises(XiaohongshuParseError):
        extract_room_id("https://www.xiaohongshu.com/user/profile/abc")


def test_parse_ws_frame_real_shape():
    """完整业务帧解析出 customData 对象"""
    frame = _wrap_frame([
        {"type": "text", "desc": "主播好", "profile": {"nickname": "路人", "user_id": "u1"}},
        {"type": "like"},
    ])
    out = parse_ws_frame(frame)
    assert [o.get("type") for o in out] == ["text", "like"]
    assert out[0]["profile"]["nickname"] == "路人"


def test_parse_ws_frame_ignores_noise():
    """t!=4 帧 / 非 JSON / 二进制垃圾 / customData 缺失 → 空列表"""
    assert parse_ws_frame(json.dumps({"t": 3, "b": {}})) == []
    assert parse_ws_frame("not json at all") == []
    assert parse_ws_frame(b"\x00\x01\x02") == []
    assert parse_ws_frame(json.dumps({"t": 4, "b": {"d": {"b": [{"d": ""}]}}})) == []
    # customData 非法 JSON → 该项跳过不抛
    bad = json.dumps({"t": 4, "b": {"d": {"b": [
        {"d": base64.b64encode(json.dumps({"customData": "{broken"}).encode()).decode()}]}}})
    assert parse_ws_frame(bad) == []


def test_map_custom_data_types():
    ts, seq = 1700000000, 1
    danmu = map_custom_data(
        {"type": "text", "desc": "好看", "profile": {"nickname": "小明", "user_id": "9"}},
        seq, ts)
    assert (danmu["type"], danmu["payload"]["content"],
            danmu["payload"]["user_name"]) == ("DANMU", "好看", "小明")

    enter = map_custom_data({"type": "audience_join_v2",
                             "profile": {"nickname": "小刚"}}, seq, ts)
    assert enter["type"] == "ENTER_ROOM"

    like = map_custom_data({"type": "like", "likeActionCount": 3}, seq, ts)
    assert like["type"] == "LIKE" and like["payload"]["count"] == 3

    gift = map_custom_data({"type": "gift", "giftName": "小红心", "count": 2}, seq, ts)
    assert gift["type"] == "GIFT" and gift["payload"]["gift_count"] == 2

    follow = map_custom_data({"type": "follow_emcee",
                              "profile": {"nickname": "粉"}}, seq, ts)
    assert follow["type"] == "SOCIAL"

    # 活跃信号/未知类型 → 不 emit
    assert map_custom_data({"type": "refresh"}, seq, ts) is None
    assert map_custom_data({"type": "letter_refresh"}, seq, ts) is None
    assert map_custom_data({"type": "gift_dock_and_effect"}, seq, ts) is None


def test_envelope_platform_is_xiaohongshu():
    eng = XiaohongshuEngine()
    env = eng._envelope(
        "123", {"category": "business", "type": "DANMU", "seq": 1,
                "timestamp": 0, "payload": {"type": "DANMU"}})
    assert env["platform"] == "xiaohongshu"
    assert env["engine"] == "page:xiaohongshu"
    assert env["protocol_version"] == "xiaohongshu-1"
    for k in ("contract_version", "category", "platform", "room_id",
              "seq", "timestamp", "engine", "protocol_version", "payload"):
        assert k in env


@pytest.mark.asyncio
async def test_on_ws_frame_emits_and_touches_silence_timer():
    """framereceived dict payload（参考实现的传参 bug 已修正）→ emit + 刷新静默计时"""
    eng = XiaohongshuEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    payload = {"payload": _wrap_frame([
        {"type": "text", "desc": "测试弹幕", "profile": {"nickname": "路人甲", "user_id": "u9"}},
    ])}
    before = eng._last_frame_box.setdefault("r1", {"t": 0.0})["t"]
    await asyncio.sleep(0.01)
    await eng._on_ws_frame("r1", payload)
    danmus = [m for m in got if m["type"] == "DANMU"]
    assert len(danmus) == 1
    assert danmus[0]["payload"]["user_name"] == "路人甲"
    assert danmus[0]["payload"]["content"] == "测试弹幕"
    assert danmus[0]["platform"] == "xiaohongshu"
    assert eng._last_frame_box["r1"]["t"] > before
    # str payload 直传也支持
    await eng._on_ws_frame("r1", _wrap_frame([
        {"type": "like", "likeActionCount": 5}]))
    likes = [m for m in got if m["type"] == "LIKE"]
    assert len(likes) == 1 and likes[0]["payload"]["count"] == 5


def test_engine_id():
    assert XiaohongshuEngine().engine_id == "page:xiaohongshu"
