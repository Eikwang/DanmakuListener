"""视频号 GIFT 路径单测（2026-10-03 NameError 回归——GIFT 分支无覆盖曾致
WXSP_GIFT_PRICE 未导入逃过单测、运行时礼物全丢）"""
import base64
import json

import pytest

from danmaku_listener.engines.wechat_channels import WechatChannelsEngine


def _feed_response(app_items, msg_items=None):
    """构造 live/msg 响应（asyncio mock response 对象）"""
    body = {"errCode": 0, "data": {"appMsgList": app_items,
                                   "msgList": msg_items or []}}

    class FakeResponse:
        url = "https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/live/msg?x=1"

        async def json(self):
            return body

    return FakeResponse()


def _app(msg_type, payload_obj=None, raw_payload=""):
    return {"msgType": msg_type, "payload": raw_payload,
            "fromUserContact": {"contact": {"nickname": "测试用户",
                                            "username": "u1"}}}


def _b64(obj):
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode()).decode()


@pytest.mark.asyncio
async def test_gift_20122_20078_paths_no_nameerror():
    """GIFT/新点赞(20122)/新关注(20078) 三条路径运行时不抛 NameError
    （WXSP_GIFT_PRICE 未导入回归——2026-10-03 用户实测礼物全丢）"""
    eng = WechatChannelsEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)

    gift_payload = {"content": "测试用户送了主播1个玫瑰",
                    "reward_product_id": "findercoin_5_x",
                    "reward_product_count": 2,
                    "reward_amount_in_wecoin": 0}
    app_items = [
        _app(20009, raw_payload=_b64(gift_payload)),          # 礼物
        _app(20122, raw_payload=_b64({"type": 1, "wording": "赞了直播"})),  # 点赞
        _app(20078, raw_payload=_b64({"follow_time": 1, "wording": "关注了主播"})),  # 关注
    ]
    await eng._on_response("r1", _feed_response(app_items))

    types = [m["type"] for m in got]
    assert "GIFT" in types and "LIKE" in types and "SOCIAL" in types

    gift = next(m for m in got if m["type"] == "GIFT")
    # 玫瑰在价格表 → gift_name 反查命中；gift_value = 单价×数量
    assert gift["payload"]["gift_name"] == "玫瑰"
    assert gift["payload"]["gift_value"] == 1 * 2
    assert gift["payload"]["gift_count"] == 2
    assert gift["platform"] == "wechat_channels"

    like = next(m for m in got if m["type"] == "LIKE")
    assert like["payload"]["user_name"] == "测试用户"
    follow = next(m for m in got if m["type"] == "SOCIAL")
    assert follow["payload"]["action"] == "follow"


@pytest.mark.asyncio
async def test_gift_unknown_name_falls_back_to_content():
    """未知礼物名（不在价格表）→ gift_name 退回 content 描述"""
    eng = WechatChannelsEngine()
    got = []

    async def on_msg(m):
        got.append(m)

    eng.on_message(on_msg)
    gift_payload = {"content": "测试用户送了主播1个神秘彩蛋",
                    "reward_product_id": "findercoin_5_y",
                    "reward_product_count": 1}
    await eng._on_response("r1", _feed_response([_app(20009, raw_payload=_b64(gift_payload))]))
    gift = next(m for m in got if m["type"] == "GIFT")
    assert "神秘彩蛋" in gift["payload"]["gift_name"]
