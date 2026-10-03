"""1688 独立引擎测试——DOM 弹幕解析/信封/生命周期"""

import asyncio

import pytest

from danmaku_listener.engines.protocol.live1688 import (
    Live1688Engine,
    extract_feed_id,
    parse_base64_mixed_message,
)


def test_extract_feed_id():
    assert extract_feed_id("3020478667606364") == "3020478667606364"
    assert extract_feed_id(
        "https://live.1688.com/zb/play.html?userId=4184469525&feedId=3020478667606364"
    ) == "3020478667606364"
    with pytest.raises(Exception):
        extract_feed_id("not-a-feed")


def test_parse_base64_mixed():
    import base64
    payload = b'\x00\x7b"nick": "u", "content": "hi"\x7d'
    objs = parse_base64_mixed_message(base64.b64encode(payload).decode())
    assert objs == [{"nick": "u", "content": "hi"}]


def test_map_chat_by_subtype():
    obj = {"subType": 10001, "nick": "用户A", "userid": "7", "content": "主播好"}
    mapped = Live1688Engine._map_message("123", obj, 1, 1700000000)
    assert mapped["type"] == "DANMU"
    assert mapped["payload"]["content"] == "主播好"


def test_map_stats_and_gift():
    stats = Live1688Engine._map_message(
        "123", {"viewCountFormat": "634 观看", "totalCount": 634, "onlineCount": 88},
        1, 1700000000)
    assert stats["type"] == "ROOM_STATS"
    # onlineCount 有值时观看人数取在线数
    assert stats["payload"]["viewer_count"] == 88
    assert stats["payload"]["total_view_count"] == 634

    # 2026-10-03 语义校准（用户实测"观看 0"根因）：onlineCount 恒 0/缺失 →
    # 观看人数回退 totalCount（UV），累计浏览 pageViewCount（PV）
    stats2 = Live1688Engine._map_message(
        "123", {"onlineCount": 0, "viewCountFormat": "1974 观看",
                "pageViewCount": 1974, "totalCount": 1193}, 2, 1700000000)
    assert stats2["payload"]["viewer_count"] == 1193
    assert stats2["payload"]["total_view_count"] == 1974

    # 精简形态（仅 totalCount）
    stats3 = Live1688Engine._map_message("123", {"totalCount": 8}, 3, 1700000000)
    assert stats3["payload"]["viewer_count"] == 8
    assert stats3["payload"]["total_view_count"] == 8

    gift = Live1688Engine._map_message(
        "123", {"subType": 10002, "nick": "土豪", "giftName": "小心心", "count": 3},
        2, 1700000000)
    assert gift["type"] == "GIFT"
    assert gift["payload"]["gift_count"] == 3


def test_map_member_and_like():
    member = Live1688Engine._map_message(
        "123", {"nick": "新人", "userid": "9", "flowSourceText": "分享"}, 1, 1700000000)
    assert member["type"] == "ENTER_ROOM"

    like = Live1688Engine._map_message("123", {"value": {"dig": 2}}, 2, 1700000000)
    assert like["type"] == "LIKE"


def test_envelope_platform_is_1688():
    """platform 必须如实标注 1688（用户实测教训：静态硬编码曾致 1688 消息标成 taobao）"""
    eng = Live1688Engine()
    env = eng._envelope(
        "123", {"category": "business", "type": "DANMU", "seq": 1,
                "timestamp": 0, "payload": {"type": "DANMU"}})
    assert env["platform"] == "1688"
    assert env["engine"] == "page:1688"
    assert env["protocol_version"] == "1688-1"


@pytest.mark.asyncio
async def test_dom_poll_emits_danmu():
    """DOM 弹幕轮询：mock page.evaluate 返回 {nick,text} 条目 → emit DANMU

    页面 JS 渲染源码实证：昵称在 .from（观众脱敏形态带尾冒号）、
    内容在 .msg-text，evaluate 内已分节点提取。
    """
    eng = Live1688Engine()
    got_list = []

    async def on_msg(m):
        got_list.append(m)

    eng.on_message(on_msg)

    class FakePage:
        calls = 0

        async def evaluate(self, *_a, **_k):
            FakePage.calls += 1
            if FakePage.calls == 1:
                return [
                    {"nick": "诗***婆", "text": "测试弹幕内容"},   # 脱敏昵称（尾冒号已在 JS 剥离）
                    {"nick": "", "text": "无昵称条目"},            # .from 空 → 昵称置空，不得复用内容
                ]
            return []

    task = asyncio.create_task(eng._poll_dom_danmu("123", FakePage()))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    danmus = [m for m in got_list if m["type"] == "DANMU"]
    assert len(danmus) == 2
    assert danmus[0]["payload"]["user_name"] == "诗***婆"
    assert danmus[0]["payload"]["content"] == "测试弹幕内容"
    assert danmus[1]["payload"]["user_name"] == ""
    assert danmus[1]["payload"]["content"] == "无昵称条目"
    for m in danmus:
        for k in ("contract_version", "category", "platform", "room_id",
                  "seq", "timestamp", "engine", "protocol_version", "payload"):
            assert k in m
    assert danmus[0]["platform"] == "1688"


@pytest.mark.asyncio
async def test_dom_poll_nick_fallback_split():
    """防御路径：.from 缺失时从文本拆 `昵称:内容`（两段均非空才拆）"""
    eng = Live1688Engine()
    got_list = []

    async def on_msg(m):
        got_list.append(m)

    eng.on_message(on_msg)

    class FakePage:
        async def evaluate(self, *_a, **_k):
            return [{"nick": "", "text": "回显用户:回显内容"}]

    task = asyncio.create_task(eng._poll_dom_danmu("123", FakePage()))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    danmus = [m for m in got_list if m["type"] == "DANMU"]
    assert len(danmus) == 1
    assert danmus[0]["payload"]["user_name"] == "回显用户"
    assert danmus[0]["payload"]["content"] == "回显内容"


@pytest.mark.asyncio
async def test_dom_poll_no_nick_reuse():
    """用户实测教训回归：昵称缺失时绝不让 user_name==content"""
    eng = Live1688Engine()
    got_list = []

    async def on_msg(m):
        got_list.append(m)

    eng.on_message(on_msg)

    class FakePage:
        async def evaluate(self, *_a, **_k):
            return [{"nick": "", "text": "这是碳架吗"}]

    task = asyncio.create_task(eng._poll_dom_danmu("123", FakePage()))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    danmus = [m for m in got_list if m["type"] == "DANMU"]
    assert len(danmus) == 1
    m = danmus[0]["payload"]
    assert m["content"] == "这是碳架吗"
    assert m["user_name"] != m["content"]  # 核心回归断言


@pytest.mark.asyncio
async def test_dom_poll_dedup():
    """同一弹幕（昵称+内容）不重复 emit（滚动历史区去重）"""
    eng = Live1688Engine()
    got_list = []

    async def on_msg(m):
        got_list.append(m)

    eng.on_message(on_msg)

    class FakePage:
        async def evaluate(self, *_a, **_k):
            return [{"nick": "", "text": "同一弹幕"}]

    task = asyncio.create_task(eng._poll_dom_danmu("123", FakePage()))
    await asyncio.sleep(0.6)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(got_list) == 1


def test_protocol_version():
    assert Live1688Engine().engine_id == "page:1688"
