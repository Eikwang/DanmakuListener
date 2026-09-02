"""工具函数模块测试

验证平台解析器和配置管理的核心功能。
"""

import pytest

from danmaku_listener.utils.platform_parser import (
    parse_room_spec,
    RoomSpec,
    SUPPORTED_PLATFORMS,
    validate_platform,
    get_default_engine,
)
from danmaku_listener.config.settings import Settings, get_settings


# ===== 平台解析器测试 =====


class TestPlatformParser:
    """平台解析器测试"""

    def test_parse_valid_spec(self):
        """测试解析有效的房间规格"""
        spec = parse_room_spec("douyin:123456")
        assert spec.platform == "douyin"
        assert spec.room_id == "123456"

    def test_parse_spec_strips_whitespace(self):
        """测试去除空格"""
        spec = parse_room_spec("  douyin : 123456  ")
        assert spec.platform == "douyin"
        assert spec.room_id == "123456"

    def test_parse_spec_case_insensitive(self):
        """测试平台标识不区分大小写"""
        spec = parse_room_spec("DouYin:123456")
        assert spec.platform == "douyin"

    def test_parse_empty_spec_raises(self):
        """测试空字符串抛出异常"""
        with pytest.raises(ValueError, match="Invalid room spec"):
            parse_room_spec("")

    def test_parse_no_colon_raises(self):
        """测试缺少冒号抛出异常"""
        with pytest.raises(ValueError, match="Invalid room spec"):
            parse_room_spec("douyin123456")

    def test_parse_empty_platform_raises(self):
        """测试空平台标识抛出异常"""
        with pytest.raises(ValueError, match="Platform cannot be empty"):
            parse_room_spec(":123456")

    def test_parse_empty_room_id_raises(self):
        """测试空房间 ID 抛出异常"""
        with pytest.raises(ValueError, match="Room ID cannot be empty"):
            parse_room_spec("douyin:")

    def test_parse_unsupported_platform_raises(self):
        """测试不支持的平台抛出异常"""
        with pytest.raises(ValueError, match="Unsupported platform"):
            parse_room_spec("unknown:123456")

    def test_room_spec_is_frozen(self):
        """测试 RoomSpec 是不可变的"""
        spec = RoomSpec(platform="douyin", room_id="123")
        with pytest.raises(AttributeError):
            spec.platform = "bilibili"

    def test_supported_platforms_list(self):
        """测试支持的平台列表"""
        assert "douyin" in SUPPORTED_PLATFORMS
        assert "douyu" in SUPPORTED_PLATFORMS
        assert "bilibili" in SUPPORTED_PLATFORMS

    def test_validate_platform_valid(self):
        """测试验证有效平台"""
        assert validate_platform("douyin") is True
        assert validate_platform("DOUYIN") is True

    def test_validate_platform_invalid(self):
        """测试验证无效平台"""
        assert validate_platform("unknown") is False

    def test_get_default_engine_douyin(self):
        """测试抖音默认使用代理引擎"""
        assert get_default_engine("douyin") == "proxy"

    def test_get_default_engine_other_platforms(self):
        """测试其他平台默认使用浏览器引擎"""
        assert get_default_engine("bilibili") == "browser"
        assert get_default_engine("douyu") == "browser"


# ===== 配置管理测试 =====


class TestSettings:
    """配置管理测试"""

    def test_default_values(self):
        """测试默认配置值"""
        settings = Settings()
        assert settings.log_level == "INFO"
        assert settings.proxy_port == 8827
        assert settings.max_rooms == 10
        assert settings.browser_headless is True
        assert settings.cookie_dir == "./cookie"
        assert settings.reconnect_max_retries == 3
        assert settings.reconnect_base_delay == 1.0
        assert settings.heartbeat_interval == 30
        assert settings.dedup_window_size == 300

    def test_proxy_host_default(self):
        """测试默认代理地址"""
        settings = Settings()
        assert settings.proxy_host == "127.0.0.1"

    def test_proxy_host_listen_any(self):
        """测试监听所有接口时的代理地址"""
        settings = Settings(listen_any=True)
        assert settings.proxy_host == "0.0.0.0"

    def test_proxy_address(self):
        """测试完整代理地址"""
        settings = Settings()
        assert settings.proxy_address == "127.0.0.1:8827"

    def test_get_settings_cached(self):
        """测试配置单例缓存"""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
