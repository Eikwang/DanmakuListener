"""Task-05: 系统代理管理器 测试

验证 SystemProxyManager：注册、关闭、可配置开关、异常处理。
"""

import pytest
from unittest.mock import patch, MagicMock


class TestSystemProxyManagerInit:
    """SystemProxyManager 初始化测试"""

    def test_enabled_by_default(self):
        """默认 enabled=True"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        spm = SystemProxyManager()
        assert spm.enabled is True

    def test_disabled(self):
        """enabled=False"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        spm = SystemProxyManager(enabled=False)
        assert spm.enabled is False


class TestSystemProxyManagerRegister:
    """register 测试"""

    def test_register_sets_proxy_enable_1(self):
        """注册时设置 ProxyEnable=1 和 ProxyServer"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0x80000001
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.REG_DWORD = 4
            mock_winreg.REG_SZ = 1
            mock_winreg.OpenKey.return_value = mock_key
            mock_winreg.QueryValueEx.side_effect = [(0, 4), ("", 1)]

            spm = SystemProxyManager()
            result = spm.register("127.0.0.1", 8827)

            assert result is True
            # 验证 ProxyEnable 被设为 1
            # SetValueEx(key, name, reserved, type, value) → args[4] is value
            calls = mock_winreg.SetValueEx.call_args_list
            proxy_enable_call = [c for c in calls if c[0][1] == "ProxyEnable"]
            assert len(proxy_enable_call) > 0
            assert proxy_enable_call[0][0][4] == 1

    def test_register_disabled_does_not_modify_registry(self):
        """enabled=False 时不修改注册表"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            spm = SystemProxyManager(enabled=False)
            result = spm.register("127.0.0.1", 8827)
            assert result is True
            mock_winreg.OpenKey.assert_not_called()

    def test_register_backs_up_original_values(self):
        """register 备份原始 ProxyEnable 和 ProxyServer 值"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0x80000001
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.REG_DWORD = 4
            mock_winreg.REG_SZ = 1
            mock_winreg.OpenKey.return_value = mock_key
            mock_winreg.QueryValueEx.side_effect = [(0, 4), ("proxy.old:8080", 1)]

            spm = SystemProxyManager()
            spm.register("127.0.0.1", 8827)

            assert spm._original_proxy_enable == 0
            assert spm._original_proxy_server == "proxy.old:8080"


class TestSystemProxyManagerClose:
    """close 测试"""

    def test_close_sets_proxy_enable_0(self):
        """关闭时设置 ProxyEnable=0"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0x80000001
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.REG_DWORD = 4
            mock_winreg.OpenKey.return_value = mock_key

            spm = SystemProxyManager()
            result = spm.close()
            assert result is True
            # 验证 ProxyEnable 被设为 0
            # SetValueEx(key, name, reserved, type, value) → args[4] is value
            calls = mock_winreg.SetValueEx.call_args_list
            proxy_enable_call = [c for c in calls if c[0][1] == "ProxyEnable"]
            assert len(proxy_enable_call) > 0
            assert proxy_enable_call[0][0][4] == 0

    def test_close_disabled_does_not_modify_registry(self):
        """enabled=False 时不修改注册表"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            spm = SystemProxyManager(enabled=False)
            result = spm.close()
            assert result is True
            mock_winreg.OpenKey.assert_not_called()

    def test_close_without_register_no_error(self):
        """close 在 register 未调用时不报错"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0x80000001
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.REG_DWORD = 4
            mock_winreg.OpenKey.return_value = mock_key

            spm = SystemProxyManager()
            result = spm.close()
            assert result is True


class TestSystemProxyManagerErrors:
    """异常处理测试"""

    def test_register_open_key_error_returns_false(self):
        """winreg.OpenKey 抛出 OSError 时 register 返回 False"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.OpenKey.side_effect = OSError("Access denied")

            spm = SystemProxyManager()
            result = spm.register("127.0.0.1", 8827)
            assert result is False

    def test_close_open_key_error_returns_false(self):
        """winreg.OpenKey 抛出 OSError 时 close 返回 False"""
        from danmaku_listener.managers.system_proxy_manager import SystemProxyManager
        with patch('danmaku_listener.managers.system_proxy_manager.winreg') as mock_winreg:
            mock_winreg.OpenKey.side_effect = OSError("Access denied")

            spm = SystemProxyManager()
            result = spm.close()
            assert result is False
