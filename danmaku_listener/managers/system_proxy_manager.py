"""Windows 系统代理管理器

通过修改 Windows 注册表注册/关闭系统代理。
支持可配置开关，异常时确保恢复。
"""

import winreg
from typing import Optional

from loguru import logger


class SystemProxyManager:
    """Windows 系统代理管理器

    启动时注册系统代理（修改注册表），停止时恢复。
    可通过 enabled=False 关闭此功能（不触碰注册表）。
    """

    REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    def __init__(self, enabled: bool = True):
        """初始化系统代理管理器

        Args:
            enabled: 是否启用系统代理注册（False 时不修改注册表）
        """
        self.enabled = enabled
        self._original_proxy_enable: Optional[int] = None
        self._original_proxy_server: Optional[str] = None

    def register(self, host: str, port: int) -> bool:
        """注册系统代理

        修改注册表设置系统代理指向指定地址。
        备份原始值以便恢复。

        Args:
            host: 代理地址
            port: 代理端口

        Returns:
            True 如果成功，False 如果失败或未启用
        """
        if not self.enabled:
            logger.info("System proxy registration disabled by config")
            return True

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )

            # 备份原始值
            try:
                self._original_proxy_enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
                self._original_proxy_server = winreg.QueryValueEx(key, "ProxyServer")[0]
            except Exception:
                pass

            # 设置新值
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            winreg.CloseKey(key)

            logger.info(f"System proxy registered: {host}:{port}")
            return True

        except Exception as e:
            logger.warning(f"Failed to register system proxy: {e}")
            return False

    def close(self) -> bool:
        """关闭系统代理

        恢复 ProxyEnable=0。即使 mitmproxy 已异常退出也应调用此方法。

        Returns:
            True 如果成功，False 如果失败或未启用
        """
        if not self.enabled:
            return True

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                self.REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            logger.info("System proxy closed (ProxyEnable=0)")
            return True

        except Exception as e:
            logger.error(f"Failed to close system proxy: {e}")
            return False
