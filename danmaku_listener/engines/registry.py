"""引擎注册表（阶段 6 全局收口）

serve 与 AUTOlive 集成的统一入口：按平台构造契约 v1 引擎。
阶段 1-5 引擎在此集中注册（三级覆盖：全局→平台→房间 由配置面承接，
本表只做引擎构造与默认路由）。

兜底触发语义（配置人工开关，默认全部关闭）：
① 长尾平台（不在六平台范围的临时需求）② 主路线失效期间 ③ 调试对照
"""

from typing import Dict, Optional

from danmaku_listener.engines.base import BaseEngine
from danmaku_listener.engines.protocol.bilibili import BilibiliProtocolEngine
from danmaku_listener.engines.protocol.douyu import DouyuProtocolEngine
from danmaku_listener.engines.protocol.huya import HuyaProtocolEngine
from danmaku_listener.engines.protocol.kuaishou import KuaishouProtocolEngine
from danmaku_listener.engines.wechat_channels import WechatChannelsEngine
from danmaku_listener.persistence.room_state_store import RoomStateStore

PLATFORM_ENGINES = {
    "bilibili": BilibiliProtocolEngine,
    "douyu": DouyuProtocolEngine,
    "huya": HuyaProtocolEngine,
    "kuaishou": KuaishouProtocolEngine,
    "wechat_channels": WechatChannelsEngine,
}


def build_engine(platform: str, state_store: Optional[RoomStateStore] = None, **kwargs) -> BaseEngine:
    """按平台构造引擎实例

    Raises:
        KeyError: 平台未注册（长尾平台走兜底注入引擎，见 NOT in scope 与兜底开关）
    """
    if platform not in PLATFORM_ENGINES:
        raise KeyError(
            f"平台 {platform!r} 未注册（已注册：{sorted(PLATFORM_ENGINES)}）；"
            "长尾平台使用兜底注入引擎（配置人工开关，默认关闭）"
        )
    return PLATFORM_ENGINES[platform](state_store=state_store, **kwargs)
