"""平台标识解析工具

提供直播间规格字符串的解析功能，格式为 "platform:room_id"。
"""

from dataclasses import dataclass
from typing import Optional, Tuple

# 支持的平台类型
PlatformType = str  # 使用字符串字面量联合类型更灵活

# 已知平台列表
SUPPORTED_PLATFORMS = ["douyin", "douyu", "bilibili", "kuaishou", "taobao", "weixin"]


@dataclass(frozen=True)
class RoomSpec:
    """直播间规格

    Attributes:
        platform: 平台标识
        room_id: 房间 ID
    """

    platform: str
    room_id: str


def parse_room_spec(spec: str) -> RoomSpec:
    """解析直播间规格字符串

    Args:
        spec: 格式为 "platform:room_id" 的字符串

    Returns:
        RoomSpec 实例

    Raises:
        ValueError: 如果格式不正确或平台不支持
    """
    if not spec or ":" not in spec:
        raise ValueError(f"Invalid room spec format: {spec}. Expected 'platform:room_id'")

    parts = spec.split(":", 1)
    platform = parts[0].strip().lower()
    room_id = parts[1].strip()

    if not platform:
        raise ValueError("Platform cannot be empty")

    if not room_id:
        raise ValueError("Room ID cannot be empty")

    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}. Supported: {SUPPORTED_PLATFORMS}")

    return RoomSpec(platform=platform, room_id=room_id)


def validate_platform(platform: str) -> bool:
    """验证平台是否受支持

    Args:
        platform: 平台标识

    Returns:
        True 如果平台受支持
    """
    return platform.lower() in SUPPORTED_PLATFORMS


def get_default_engine(platform: str) -> str:
    """获取平台的默认引擎类型

    Args:
        platform: 平台标识

    Returns:
        "proxy" 或 "browser"
    """
    # 抖音优先使用代理模式
    if platform == "douyin":
        return "proxy"
    # 其他平台暂时使用浏览器模式（后续可扩展代理模式）
    return "browser"