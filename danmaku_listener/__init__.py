"""DanmakuListener - 高性能跨平台弹幕监听解决方案

提供代理模式和浏览器模式的混合架构，支持抖音、斗鱼、B站等多平台弹幕监听。
"""

from danmaku_listener.listener import DanmakuListener
from danmaku_listener.bus.message import DanmakuMessage, GiftInfo
from danmaku_listener.core import MetricsCollector

__version__ = "0.2.0"
__all__ = ["DanmakuListener", "DanmakuMessage", "GiftInfo", "MetricsCollector"]