"""Task-04: 进程过滤器 测试

验证 ProcessFilter 类：白名单匹配、缓存、异常处理。
"""

import pytest
import time
from unittest.mock import patch, MagicMock


class TestProcessFilterInit:
    """ProcessFilter 初始化测试"""

    def test_default_allowed(self):
        """默认白名单包含 7 个浏览器"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert "chrome" in f.allowed
        assert "msedge" in f.allowed
        assert len(f.allowed) == 7

    def test_custom_allowed(self):
        """自定义白名单"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter(allowed_processes=["chrome", "msedge"])
        assert f.allowed == {"chrome", "msedge"}


class TestProcessFilterAllowed:
    """is_allowed_pid 测试"""

    def test_chrome_allowed(self):
        """chrome 在白名单内"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert f.is_allowed_pid(pid=1234, process_name="chrome") is True

    def test_python_not_allowed(self):
        """python 不在白名单内"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert f.is_allowed_pid(pid=1234, process_name="python") is False

    def test_case_insensitive(self):
        """大小写不敏感"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert f.is_allowed_pid(pid=1234, process_name="Chrome") is True

    def test_custom_whitelist(self):
        """自定义白名单"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter(allowed_processes=["chrome"])
        assert f.is_allowed_pid(pid=1234, process_name="msedge") is False

    def test_empty_process_name(self):
        """空进程名不在白名单"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert f.is_allowed_pid(pid=1234, process_name="") is False


class TestProcessFilterCache:
    """进程名缓存测试"""

    def test_cache_stores_result(self):
        """缓存存储查询结果"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        f._cache[1234] = ("chrome", time.time())
        assert f.is_allowed_pid(pid=1234, process_name=None) is True

    def test_cache_ttl_default(self):
        """默认 TTL 为 30 秒"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        assert f._cache_ttl == 30.0

    def test_get_process_name_uses_cache(self):
        """_get_process_name 命中缓存时不调 psutil"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        f._cache[1234] = ("chrome", time.time())
        with patch('danmaku_listener.engines.process_filter.psutil.Process') as mock_process:
            result = f._get_process_name(1234)
            assert result == "chrome"
            mock_process.assert_not_called()


class TestProcessFilterExceptions:
    """异常处理测试"""

    def test_access_denied_returns_empty(self):
        """psutil.AccessDenied 时 _get_process_name 返回空字符串"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        import psutil
        f = ProcessFilter()
        with patch('danmaku_listener.engines.process_filter.psutil.Process', side_effect=psutil.AccessDenied(1234)):
            result = f._get_process_name(1234)
            assert result == ""

    def test_no_such_process_returns_empty(self):
        """psutil.NoSuchProcess 时 _get_process_name 返回空字符串"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        import psutil
        f = ProcessFilter()
        with patch('danmaku_listener.engines.process_filter.psutil.Process', side_effect=psutil.NoSuchProcess(9999)):
            result = f._get_process_name(9999)
            assert result == ""


class TestProcessFilterByPort:
    """基于端口的进程过滤测试"""

    def test_find_pid_by_port_found(self):
        """能找到端口对应的 PID"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        mock_conn = MagicMock()
        mock_conn.laddr.port = 12345
        mock_conn.status = 'ESTABLISHED'
        mock_conn.pid = 999

        with patch('danmaku_listener.engines.process_filter.psutil.net_connections', return_value=[mock_conn]):
            pid = f._find_pid_by_port(12345)
            assert pid == 999

    def test_find_pid_by_port_not_found(self):
        """找不到端口时返回 None"""
        from danmaku_listener.engines.process_filter import ProcessFilter
        f = ProcessFilter()
        with patch('danmaku_listener.engines.process_filter.psutil.net_connections', return_value=[]):
            pid = f._find_pid_by_port(54321)
            assert pid is None
