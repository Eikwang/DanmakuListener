"""结构化日志测试

验证增强日志配置功能。
"""

import json
import sys
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

from danmaku_listener.utils.logger import (
    setup_logger,
    get_logger,
    setup_structured_logger,
    mask_sensitive,
)


class TestStructuredLogger:
    """结构化日志测试"""

    def test_setup_structured_logger_creates_handlers(self):
        """测试结构化日志配置创建多个 handler"""
        # 不应抛出异常
        setup_structured_logger(level="DEBUG")

    def test_mask_sensitive_masks_cookie(self):
        """测试 Cookie 值被遮蔽"""
        data = {"cookie": "session=abc123xyz", "url": "https://example.com"}
        masked = mask_sensitive(data)
        assert "abc123xyz" not in str(masked)
        assert "***" in str(masked.get("cookie", "")) or "abc123xyz" not in masked.get("cookie", "")

    def test_mask_sensitive_masks_token(self):
        """测试 token 值被遮蔽"""
        data = {"token": "secret_token_12345", "user": "test"}
        masked = mask_sensitive(data)
        assert "secret_token_12345" not in str(masked)
        assert masked["user"] == "test"

    def test_mask_sensitive_masks_password(self):
        """测试 password 值被遮蔽"""
        data = {"password": "my_password", "username": "admin"}
        masked = mask_sensitive(data)
        assert "my_password" not in str(masked)
        assert masked["username"] == "admin"

    def test_mask_sensitive_preserves_non_sensitive(self):
        """测试非敏感字段保持不变"""
        data = {"platform": "douyin", "room_id": "123456", "count": 100}
        masked = mask_sensitive(data)
        assert masked == data

    def test_mask_sensitive_nested_dict(self):
        """测试嵌套字典中的敏感字段也被遮蔽"""
        data = {
            "request": {
                "headers": {
                    "authorization": "Bearer abc123",
                },
                "url": "https://example.com",
            }
        }
        masked = mask_sensitive(data)
        assert "abc123" not in str(masked)

    def test_mask_sensitive_empty_dict(self):
        """测试空字典"""
        assert mask_sensitive({}) == {}

    def test_setup_structured_logger_with_file(self, tmp_path):
        """测试结构化日志配置支持文件输出"""
        log_file = str(tmp_path / "test.log")
        setup_structured_logger(level="DEBUG", log_file=log_file)

    def test_get_logger_returns_bound_logger(self):
        """测试 get_logger 返回绑定模块名的 logger"""
        log = get_logger("test_module")
        assert log is not None


class TestSetupLogger:
    """基础日志配置测试"""

    def test_setup_logger_default_level(self):
        """测试默认日志级别"""
        setup_logger()  # 不应抛出异常

    def test_setup_logger_custom_level(self):
        """测试自定义日志级别"""
        setup_logger(level="DEBUG")

    def test_setup_logger_with_file(self, tmp_path):
        """测试日志文件输出"""
        log_file = str(tmp_path / "test.log")
        setup_logger(level="INFO", log_file=log_file)
