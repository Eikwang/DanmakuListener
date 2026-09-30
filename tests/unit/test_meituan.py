"""美团引擎测试——live_id 归一/快照映射/信封/去重/场次状态/ROOM_STATS"""

import asyncio

import pytest

from danmaku_listener.engines.protocol.meituan import (
    MeituanLiveEnded,
    MeituanParseError,
    MeituanPollEngine,
    extract_live_id,
)


def _danmu_msg(name="甲", uid=1, content="你好", cid="c1"):
    return {"msgType": 2,
            "imUserDTO": {"userName": name, "userId": uid},
            "imMsgDTO": {"content": content, "commentId": cid}}


def test_extract_live_id():
    assert extract_live_id("9496370") == "9496370"
    assert extract_live_id(
        "https://mlive.meituan.com/live/play.html?liveid=10038909&x=1") == "10038909"
    assert extract_live_id("http://dpurl.cn/voNM8RIz") == "http://dpurl.cn/voNM8RIz"
    with pytest.raises(MeituanParseError):
        extract_live_id("not-a-room")
    with pytest.raises(MeituanParseError):
        # 美团链接但无 liveid 参数
        extract_live_id("https://mlive.meituan.com/live/play.html?anchorId=7")


def test_validate_room_id():
    eng = MeituanPollEngine()
    eng.validate_room_id("9496370")
    with pytest.raises(ValueError):
        eng.validate_room_id("bogus:room")


def test_envelope_platform_is_meituan():
    eng = MeituanPollEngine()
    env = eng._envelope(
        "123", {"category": "business", "type": "DANMU", "seq": 1,
                "timestamp": 0, "payload": {"type": "DANMU"}})
    assert env["platform"] == "meituan"
    assert env["engine"] == "poll:meituan"
    assert env["protocol_version"] == "meituan-1"
    for k in ("contract_version", "category", "platform", "room_id",
              "seq", "timestamp", "engine", "protocol_version", "payload"):
        assert k in env


@pytest.mark.asyncio
async def test_snapshot_maps_danmu_in_order():
    """倒序快照数组 → 正序 emit；msgType=2 → DANMU"""
    eng = MeituanPollEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    snapshot = {
        "liveInfoVo": {"beginTime": 1700000000000},
        "messageVO": {"msgs": [
            _danmu_msg(name="乙", uid=2, content="第二条", cid="c2"),
            _danmu_msg(name="甲", uid=1, content="第一条", cid="c1"),
        ]},
    }
    await eng._handle_snapshot("r1", snapshot)
    danmus = [m for m in got if m["type"] == "DANMU"]
    assert [m["payload"]["content"] for m in danmus] == ["第一条", "第二条"]
    assert danmus[0]["payload"]["user_name"] == "甲"
    assert danmus[0]["payload"]["user_id"] == "1"
    assert danmus[0]["platform"] == "meituan"


@pytest.mark.asyncio
async def test_snapshot_dedup_and_msgtype_filter():
    """commentId 去重；msgType!=2 跳过；非 dict 条目跳过"""
    eng = MeituanPollEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    msg = _danmu_msg()
    await eng._handle_snapshot("r1", {"messageVO": {"msgs": [msg]}})
    # 同一 commentId 再次到达（全量快照轮询）→ 不重复
    await eng._handle_snapshot("r1", {"messageVO": {"msgs": [msg]}})
    # msgType=5（进入等未知类型）→ 跳过
    other = dict(_danmu_msg(cid="c9"), msgType=5)
    # 非 dict / 缺字段 → 跳过
    await eng._handle_snapshot("r1", {"messageVO": {"msgs": [
        "bogus", other, {"imUserDTO": {}, "imMsgDTO": {}}]}})
    danmus = [m for m in got if m["type"] == "DANMU"]
    assert len(danmus) == 1


@pytest.mark.asyncio
async def test_live_ended_on_endtime():
    """liveInfoVo.endTime 有值（场次已结束，历史场次实测）→ MeituanLiveEnded"""
    eng = MeituanPollEngine()
    with pytest.raises(MeituanLiveEnded):
        await eng._handle_snapshot(
            "r1", {"liveInfoVo": {"beginTime": 1735553979000,
                                  "endTime": 1735564179000},
                   "messageVO": {"msgs": []}})


@pytest.mark.asyncio
async def test_error_code_raises_live_ended():
    """网关错误体（code!=0）→ MeituanLiveEnded（触发三段式）"""
    eng = MeituanPollEngine()
    with pytest.raises(MeituanLiveEnded):
        await eng._handle_snapshot("r1", {"code": 404, "msg": "not found"})


@pytest.mark.asyncio
async def test_room_stats_emit_on_change():
    """liveLikeCount/liveHeat → ROOM_STATS；值不变不重复 emit"""
    eng = MeituanPollEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    live = {"liveLikeCount": 88, "liveHeat": "120"}
    await eng._handle_snapshot("r1", {"liveInfoVo": live, "messageVO": {"msgs": []}})
    await eng._handle_snapshot("r1", {"liveInfoVo": live, "messageVO": {"msgs": []}})
    like2 = dict(live, liveLikeCount=89)
    await eng._handle_snapshot("r1", {"liveInfoVo": like2, "messageVO": {"msgs": []}})
    stats = [m for m in got if m["type"] == "ROOM_STATS"]
    assert len(stats) == 2
    assert stats[0]["payload"]["like_count"] == 88
    assert stats[1]["payload"]["like_count"] == 89
    assert stats[0]["payload"]["heat"] == "120"


def test_engine_id():
    assert MeituanPollEngine().engine_id == "poll:meituan"
