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
    """2026-09-30 zhibo.jd.com 实测分发形态（58 帧采样）"""
    ts, seq = 1700000000, 1
    # 统计帧 → ROOM_STATS
    stats = map_jd_message({
        "type": "get_statistics_result",
        "body": {"current_viewer": 1234, "thumbs_up_num": 56, "pv": 100,
                 "groupid": "48293857"}}, seq, ts)
    assert stats["type"] == "ROOM_STATS"
    assert stats["payload"]["viewer_count"] == 1234

    # 进场（聚合形态）
    enter = map_jd_message({
        "type": "chat_group_message",
        "body": {"type": "join_live_broadcast_summary",
                 "nickName": "123时间的玫瑰", "joinUserNum": 16,
                 "content": "123时间的玫瑰等16人来了", "groupid": "48293857"}},
        seq, ts)
    assert enter["type"] == "ENTER_ROOM"
    assert enter["payload"]["user_name"] == "123时间的玫瑰"

    # 点赞
    like = map_jd_message({
        "type": "chat_group_message",
        "body": {"type": "thumbs_up", "thumbs_up_num": 3}}, seq, ts)
    assert like["type"] == "LIKE" and like["payload"]["count"] == 3

    # 弹幕（实测形态）：body.type=viewer_send_message + nickName/content
    danmu = map_jd_message({
        "type": "chat_group_message",
        "from": {"app": "jd.live", "pinmd5": "b750e5b8"},
        "body": {"type": "viewer_send_message", "nickName": "无聊的小土豆来了",
                 "content": "上点那个喷雾喷苍蝇的", "groupid": "48077657",
                 "loveLevel": 5, "userMemberLevel": 4}}, seq, ts)
    assert danmu["type"] == "DANMU"
    assert danmu["payload"]["user_name"] == "无聊的小土豆来了"
    assert danmu["payload"]["content"] == "上点那个喷雾喷苍蝇的"

    # 宽容兼容路径保留（无 body.type）
    alt = map_jd_message({
        "type": "chat_group_message",
        "body": {"nickName": "观众甲", "content": "主播好",
                 "groupid": "48293857"}}, seq, ts)
    assert alt["type"] == "DANMU"
    assert alt["payload"]["user_name"] == "观众甲"
    assert alt["payload"]["content"] == "主播好"

    # 下单通知等高频运营形态 → 不映射
    assert map_jd_message({
        "type": "chat_group_message",
        "body": {"type": "user_places_order", "nickName": "x"}}, seq, ts) is None

    # 购买/购物车等运营形态 → 不映射
    assert map_jd_message({
        "type": "chat_group_message",
        "body": {"type": "viewer_buy_product_summary", "nickName": "Xuxug",
                 "content": "Xuxug正在购买510号商品"}}, seq, ts) is None
    assert map_jd_message({
        "type": "chat_group_message",
        "body": {"type": "new_anchor_cart_number", "number": "2"}}, seq, ts) is None
    # 非 chat_group_message 顶层
    assert map_jd_message({"type": "other", "body": {"nickName": "x",
                                                     "content": "y"}}, seq, ts) is None


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
