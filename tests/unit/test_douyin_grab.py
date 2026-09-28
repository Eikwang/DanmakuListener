"""抖音 BarrageGrab 桥接引擎测试——九类消息映射 + 分发逻辑"""

import asyncio
import json

import pytest

from danmaku_listener.engines.douyin_grab import DouyinBarrageGrabEngine


def _wrap(msg_type: int, data: dict) -> str:
    return json.dumps({"Type": msg_type, "Data": json.dumps(data)}, ensure_ascii=False)


def _danmu_data(**over):
    d = {
        "MsgId": 7301, "Content": "主播讲得真好", "RoomId": "112233",
        "WebRoomId": "445566", "User": {"Id": 9527, "Nickname": "测试用户"},
    }
    d.update(over)
    return d


@pytest.mark.asyncio
async def test_danmu_dispatch():
    eng = DouyinBarrageGrabEngine()
    msgs = []
    eng.on_message(lambda m: asyncio.ensure_future(_collect(msgs, m)))
    eng._active_rooms.add("445566")
    await eng._dispatch(_wrap(1, _danmu_data()))
    assert len(msgs) == 1
    m = msgs[0]
    assert m["type"] == "DANMU" and m["platform"] == "douyin"
    assert m["payload"]["content"] == "主播讲得真好"
    assert m["payload"]["user_name"] == "测试用户"
    assert m["payload"]["user_id"] == "9527"
    assert m["msg_id"] == 7301


async def _collect(store, m):
    store.append(m)


@pytest.mark.asyncio
async def test_gift_like_enter_follow_stats_fansclub_share():
    eng = DouyinBarrageGrabEngine()
    msgs = []
    eng.on_message(lambda m: asyncio.ensure_future(_collect(msgs, m)))
    eng._active_rooms.add("445566")

    cases = [
        (2, {"Count": 3, "Total": 99, "User": {"Id": 1, "Nickname": "u"}, "WebRoomId": "445566"}, "LIKE"),
        (3, {"User": {"Id": 2, "Nickname": "u2"}, "CurrentCount": 12, "WebRoomId": "445566"}, "ENTER_ROOM"),
        (4, {"User": {"Id": 3, "Nickname": "u3"}, "WebRoomId": "445566"}, "SOCIAL"),
        (5, {"GiftName": "玫瑰", "GiftCount": 5, "DiamondCount": 10,
             "User": {"Id": 4, "Nickname": "u4"}, "WebRoomId": "445566"}, "GIFT"),
        (6, {"OnlineUserCount": 88, "TotalUserCount": 1200, "WebRoomId": "445566"}, "ROOM_STATS"),
        (7, {"Type": 1, "FansClubName": "粉丝团", "Level": 5,
             "User": {"Id": 5, "Nickname": "u5"}, "WebRoomId": "445566"}, "SOCIAL"),
        (8, {"User": {"Id": 6, "Nickname": "u6"}, "WebRoomId": "445566"}, "SOCIAL"),
    ]
    for msg_type, data, expect_type in cases:
        await eng._dispatch(_wrap(msg_type, data))
    types = [m["type"] for m in msgs]
    assert types == ["LIKE", "ENTER_ROOM", "SOCIAL", "GIFT", "ROOM_STATS", "SOCIAL", "SOCIAL"]
    gift = next(m for m in msgs if m["type"] == "GIFT")
    assert gift["payload"]["gift_name"] == "玫瑰"
    assert gift["payload"]["gift_count"] == 5
    assert gift["payload"]["gift_value"] == 10
    follow = msgs[2]
    assert follow["payload"]["action"] == "follow"


@pytest.mark.asyncio
async def test_live_exit_dispatch():
    eng = DouyinBarrageGrabEngine()
    msgs = []
    eng.on_message(lambda m: asyncio.ensure_future(_collect(msgs, m)))
    eng._active_rooms.add("445566")
    await eng._dispatch(json.dumps({"Type": 9, "Data": json.dumps({"WebRoomId": "445566"})}))
    assert len(msgs) == 1
    assert msgs[0]["type"] == "LIVE_STATUS_CHANGE"
    assert msgs[0]["payload"]["live"] is False


@pytest.mark.asyncio
async def test_unregistered_room_dropped():
    eng = DouyinBarrageGrabEngine()
    msgs = []
    eng.on_message(lambda m: asyncio.ensure_future(_collect(msgs, m)))
    eng._active_rooms.add("445566")
    await eng._dispatch(_wrap(1, _danmu_data(WebRoomId="999999")))
    assert msgs == []


@pytest.mark.asyncio
async def test_invalid_json_ignored():
    eng = DouyinBarrageGrabEngine()
    msgs = []
    eng.on_message(lambda m: asyncio.ensure_future(_collect(msgs, m)))
    eng._active_rooms.add("445566")
    await eng._dispatch("not-json")
    await eng._dispatch(json.dumps({"Type": 1}))  # 缺 Data
    assert msgs == []


@pytest.mark.asyncio
async def test_engine_lifecycle():
    eng = DouyinBarrageGrabEngine()
    assert eng.engine_id == "grab:douyin"
    # 连接失败（8888 未开）应进入重试循环不崩溃
    await eng.start("12345")
    await asyncio.sleep(0.3)
    assert eng._conn_task is not None
    await eng.stop("12345")
