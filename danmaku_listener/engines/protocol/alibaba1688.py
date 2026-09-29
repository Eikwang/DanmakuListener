"""1688 直播弹幕引擎（阿里系 powermsg 协议——与淘宝同构，2026-09-29 实测确认）

协议证据（live.1688.com/zb/play.html 实测抓取）：
- 网关：h5api.m.1688.com（1688 域名，同 appKey 12574478）
- 接口：mtop.taobao.powermsg.h5.msg.pullnativemsg + .subscribe（API 名与淘宝相同）
- 消息结构：与淘宝同构（viewCountFormat/totalCount/onlineCount 统计、
  subType/nick/content 聊天等——JSON 对象流）

直播间参数：feedId（场次）+ userId（主播）——room_spec 兼容 feedId、完整链接。
"""

import re
from typing import Optional

from danmaku_listener.engines.protocol.taobao import TaobaoWebProtocolEngine

PROTOCOL_VERSION = "alibaba1688-1"

LIVE_URL_TEMPLATE = "https://live.1688.com/zb/play.html?feedId={live_id}"


class Alibaba1688Engine(TaobaoWebProtocolEngine):
    """1688 直播弹幕引擎（淘宝 mtop powermsg 协议同构复用）"""

    platform = "alibaba1688"
    PROTOCOL_VERSION = PROTOCOL_VERSION  # alibaba1688-1

    MTOP_DOMAIN = "1688.com"
    LIVE_URL_TEMPLATE = LIVE_URL_TEMPLATE
    #: 1688 页面：powermsg（pull/subscribe）请求携带 topic
    TOPIC_ANCHORS = ("powermsg",)
    #: 1688 页面实测轮询参数（2026-09-29 抓取）
    POWERMSG_SDK_VERSION = "h5_3.3.3"
    POWERMSG_PAGESIZE = 20
    POWERMSG_INIT_OFFSET_ZERO = True
    PAGE_ORIGIN = "https://live.1688.com"

    @staticmethod
    def _extract_live_id(room_spec: str) -> str:
        """feedId 归一：数字 / 完整链接（feedId= 或 userId=）"""
        if "1688.com" in room_spec:
            m = re.search(r"feedId=(\d+)", room_spec)
            if m:
                return m.group(1)
        m = re.match(r"^(\d{8,25})$", room_spec.strip())
        if m:
            return m.group(1)
        raise ValueError(f"无法解析 1688 直播间 feedId: {room_spec!r}")

    @property
    def engine_id(self) -> str:
        return "webws:alibaba1688"

    def validate_room_id(self, room_id: str) -> None:
        """add_room 预校验：1688 引擎无法解析淘宝链接（提示用对前缀）"""
        try:
            self._extract_live_id(room_id)
        except ValueError as e:
            raise ValueError(
                f"{e}——若为淘宝直播间请使用 taobao: 前缀添加") from e
