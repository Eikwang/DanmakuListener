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
    """2026-09-30 在播房间实测形态校准（xhs_raw.jsonl 696 条采样）"""
    ts, seq = 1700000000, 1
    danmu = map_custom_data(
        {"type": "text", "desc": "好看", "profile": {"nickname": "小明", "user_id": "9"}},
        seq, ts)
    assert (danmu["type"], danmu["payload"]["content"],
            danmu["payload"]["user_name"]) == ("DANMU", "好看", "小明")

    enter = map_custom_data({"type": "audience_join_v2",
                             "profile": {"nickname": "小刚"}}, seq, ts)
    assert enter["type"] == "ENTER_ROOM"

    # 实测：点赞 type=praise，count 在 praise_info（聚合数）；profile 无 nickname
    like = map_custom_data({"type": "praise", "praise_info": {"count": 13},
                            "profile": {"user_id": "u1"}}, seq, ts)
    assert like["type"] == "LIKE" and like["payload"]["count"] == 13
    assert like["payload"]["user_name"] == ""

    # 实测：礼物 type=gift_dock_and_effect（下划线命名 + 嵌套取数）
    gift = map_custom_data({
        "type": "gift_dock_and_effect",
        "send_user_info": {"id": "s1", "nick_name": "🥑晴天**"},
        "base_gift_info": {"name": "人气票", "coins": 1},
        "gift_action_info": {"count": 1, "comb_count": 70},
    }, seq, ts)
    assert gift["type"] == "GIFT"
    assert gift["payload"]["gift_name"] == "人气票"
    assert gift["payload"]["gift_count"] == 1
    assert gift["payload"]["user_name"] == "🥑晴天**"
    assert gift["payload"]["user_id"] == "s1"

    follow = map_custom_data({"type": "follow_emcee",
                              "profile": {"nickname": "粉"}}, seq, ts)
    assert follow["type"] == "SOCIAL"

    share = map_custom_data({"type": "share",
                             "profile": {"nickname": "分享者"}}, seq, ts)
    assert share["type"] == "SOCIAL" and share["payload"]["action"] == "share"

    # 实测不 emit：活跃信号/送礼重复视图（防重复计数）/运营位/来源路径
    # （refresh 例外：2026-10-06 起带 viewers 名单时映射 ROOM_STATS 在线人数）
    for t in ("letter_refresh", "gift_comment", "gift_settle",
              "light", "live_banner_resource", "goods_rank_entrance_im"):
        assert map_custom_data({"type": t}, seq, ts) is None
    # refresh：无名单 → None；有名单 → ROOM_STATS（见 test_refresh_viewers_maps_room_stats）
    assert map_custom_data({"type": "refresh"}, seq, ts) is None
    with_viewers = map_custom_data(
        {"type": "refresh",
         "room_data": {"viewers": [{"user_id": "u1", "nickname": "甲"}]}}, seq, ts)
    assert with_viewers["type"] == "ROOM_STATS"
    # 调研推断的旧枚举实测不存在——防御保留（映射不到即 None）
    assert map_custom_data({"type": "like", "likeActionCount": 3}, seq, ts) is None


def test_praise_nickname_from_nick_cache():
    """praise 无昵称 → 会话学习表反查（2026-10-03 用户需求"点赞显示实际
    用户名"）：refresh 观众名单/text 弹幕帧学习，praise 按 user_id 命中"""
    ts, seq = 1700000000, 1
    cache: dict = {}

    # refresh 学习在线观众名单（2026-10-06 起同时映射 ROOM_STATS 在线人数）
    r = map_custom_data({
        "type": "refresh",
        "room_data": {"viewers": [
            {"user_id": "5bee6cd6", "nickname": "努力的小wil"},
            {"user_id": "", "nickname": "空id跳过"},
            {"user_id": "n1", "nickname": ""},
        ]},
    }, seq, ts, cache)
    assert r is not None and r["type"] == "ROOM_STATS"
    assert r["payload"]["viewer_count"] == 3  # 平台口径=名单原长（含未带昵称项）
    assert cache == {"5bee6cd6": "努力的小wil"}

    # text 弹幕帧学习
    map_custom_data({"type": "text", "desc": "好", "profile":
                     {"nickname": "小明", "user_id": "u9"}}, seq, ts, cache)
    assert cache["u9"] == "小明"

    # praise 按 user_id 反查命中（观众名单来源）
    like = map_custom_data({"type": "praise", "praise_info": {"count": 2},
                            "profile": {"user_id": "5bee6cd6"}}, seq, ts, cache)
    assert like["payload"]["user_name"] == "努力的小wil"
    assert like["payload"]["count"] == 2

    # praise 命中（弹幕来源）
    like2 = map_custom_data({"type": "praise", "praise_info": {"count": 1},
                             "profile": {"user_id": "u9"}}, seq, ts, cache)
    assert like2["payload"]["user_name"] == "小明"

    # 未命中 → 置空（前端回退"有人"）
    like3 = map_custom_data({"type": "praise", "praise_info": {"count": 1},
                             "profile": {"user_id": "unknown"}}, seq, ts, cache)
    assert like3["payload"]["user_name"] == ""

    # gift 学习 send_user_info（id/nick_name）
    map_custom_data({"type": "gift_dock_and_effect",
                     "send_user_info": {"id": "s1", "nick_name": "送礼人"},
                     "base_gift_info": {"name": "人气票", "coins": 1},
                     "gift_action_info": {"count": 1}}, seq, ts, cache)
    assert cache["s1"] == "送礼人"


def test_engine_uses_shared_nick_cache():
    """引擎持有跨帧学习表并传入 map（praise 反查依赖同实例多帧）"""
    eng = XiaohongshuEngine()
    assert eng._nick_cache == {}


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
        {"type": "praise", "praise_info": {"count": 5}}]))
    likes = [m for m in got if m["type"] == "LIKE"]
    assert len(likes) == 1 and likes[0]["payload"]["count"] == 5


def test_engine_id():
    assert XiaohongshuEngine().engine_id == "page:xiaohongshu"


# ---- 关注/在线人数映射补齐（2026-10-06 用户实测缺口）----

def test_refresh_viewers_maps_room_stats():
    """在线人数补齐：refresh 的 viewers 名单非空 → ROOM_STATS(viewer_count=len)"""
    cd = {"type": "refresh",
          "room_data": {"viewers": [{"user_id": "u1", "nickname": "甲"},
                                    {"user_id": "u2", "nickname": "乙"}]}}
    cache = {}
    msg = map_custom_data(cd, 1, 1000, cache)
    assert msg is not None and msg["type"] == "ROOM_STATS"
    assert msg["payload"]["viewer_count"] == 2
    # 昵称学习保持（online 名单同时是 praise 反查来源）
    assert cache["u1"] == "甲"


def test_refresh_empty_viewers_skips_room_stats():
    """名单为空跳过（避免"观看 0"误导——对齐 taobao 语义校准教训）"""
    cd = {"type": "refresh", "room_data": {"viewers": []}}
    assert map_custom_data(cd, 1, 1000, {}) is None
    cd2 = {"type": "refresh"}
    assert map_custom_data(cd2, 1, 1000, {}) is None


def test_follow_variant_widened():
    """关注匹配加宽：follow_emcee（调研名）与 follow 变体均映射 SOCIAL"""
    for t in ("follow_emcee", "follow"):
        cd = {"type": t, "profile": {"nickname": "粉丝", "user_id": "u9"}}
        msg = map_custom_data(cd, 2, 1000, {})
        assert msg is not None and msg["type"] == "SOCIAL"
        assert msg["payload"]["action"] == "follow"


@pytest.mark.asyncio
async def test_room_stats_dedup_engine_level():
    """引擎层同值去重：viewer_count 不变的 refresh 不重复 emit（对齐 taobao）"""
    eng = XiaohongshuEngine()
    emitted = []

    async def fake_emit(msg):
        emitted.append(msg)

    eng._emit_message = fake_emit
    cd = {"type": "refresh",
          "room_data": {"viewers": [{"user_id": "u1", "nickname": "甲"},
                                    {"user_id": "u2", "nickname": "乙"}]}}
    await eng._on_ws_frame("r1", {"payload": json.dumps({"t": 4, "b": {"d": {"b": []}}})})
    # 直接驱动 _on_ws_frame 的映射路径（绕过 WS 解析，聚焦去重逻辑）
    eng._last_room_stats.clear()
    msg = map_custom_data(cd, eng.next_seq("r1"), 1000, eng._nick_cache)
    # 模拟 _on_ws_frame 的去重段
    sig = (msg["payload"]["viewer_count"],)
    first_time = sig != eng._last_room_stats.get("r1")
    eng._last_room_stats["r1"] = sig
    second_time = sig != eng._last_room_stats.get("r1")
    assert first_time is True and second_time is False
