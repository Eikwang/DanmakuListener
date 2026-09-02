"""Task-01: 配置模型扩展 测试

验证 Settings 新增的代理相关配置项。
"""

import os
import pytest
from unittest.mock import patch


class TestProxySettings:
    """代理配置项测试"""

    def test_default_used_proxy(self):
        """默认 used_proxy=True"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.used_proxy is True

    def test_default_cert_dir(self):
        """默认 cert_dir='~/.mitmproxy'"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.cert_dir == "~/.mitmproxy"

    def test_default_process_filter(self):
        """默认 process_filter 包含 7 个浏览器"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert "chrome" in s.process_filter
        assert "msedge" in s.process_filter
        assert "QQBrowser" in s.process_filter
        assert "360se" in s.process_filter
        assert "firefox" in s.process_filter
        assert "2345Explorer" in s.process_filter
        assert "iexplore" in s.process_filter

    def test_default_force_polling(self):
        """默认 force_polling=False"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.force_polling is False

    def test_default_auto_pause(self):
        """默认 auto_pause=False"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.auto_pause is False

    def test_default_ssl_decrypt_hostnames(self):
        """默认 ssl_decrypt_hostnames 为空字符串"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.ssl_decrypt_hostnames == ""

    def test_process_filter_list_property(self):
        """process_filter_list 属性返回逗号分割后的列表"""
        from danmaku_listener.config.settings import Settings
        s = Settings(process_filter="chrome,msedge")
        assert s.process_filter_list == ["chrome", "msedge"]

    def test_process_filter_list_default(self):
        """process_filter_list 默认返回 7 个浏览器列表"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        result = s.process_filter_list
        assert len(result) == 7
        assert result[0] == "chrome"

    def test_ssl_decrypt_extra_hostnames_empty(self):
        """ssl_decrypt_extra_hostnames 空字符串返回空列表"""
        from danmaku_listener.config.settings import Settings
        s = Settings()
        assert s.ssl_decrypt_extra_hostnames == []

    def test_ssl_decrypt_extra_hostnames_with_values(self):
        """ssl_decrypt_extra_hostnames 返回逗号分割后的列表"""
        from danmaku_listener.config.settings import Settings
        s = Settings(ssl_decrypt_hostnames="custom.example.com,another.example.com")
        assert s.ssl_decrypt_extra_hostnames == ["custom.example.com", "another.example.com"]

    def test_env_used_proxy_false(self):
        """环境变量 USED_PROXY=false → used_proxy=False"""
        from danmaku_listener.config.settings import Settings
        with patch.dict(os.environ, {"USED_PROXY": "false"}):
            s = Settings()
            assert s.used_proxy is False

    def test_env_process_filter(self):
        """环境变量 PROCESS_FILTER 覆盖默认值"""
        from danmaku_listener.config.settings import Settings
        with patch.dict(os.environ, {"PROCESS_FILTER": "chrome,msedge"}):
            s = Settings()
            assert s.process_filter == "chrome,msedge"
            assert s.process_filter_list == ["chrome", "msedge"]
