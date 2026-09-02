"""DanmakuListener 配置模型

使用 Pydantic Settings 实现类型安全的配置管理，支持环境变量覆盖。
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DanmakuListener 全局配置模型

    Attributes:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        proxy_port: 代理服务器端口
        listen_any: 是否监听所有网络接口 (True=0.0.0.0, False=127.0.0.1)
        max_rooms: 同时监听的最大房间数
        browser_headless: 浏览器是否使用无头模式
        cookie_dir: Cookie 存储目录
        reconnect_max_retries: 重连最大尝试次数
        reconnect_base_delay: 重连基础延迟（秒）
        heartbeat_interval: 心跳检测间隔（秒）
        dedup_window_size: 去重窗口大小（条消息）
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ===== 日志配置 =====
    log_level: str = "INFO"

    # ===== 代理服务器配置 =====
    proxy_port: int = 8827
    listen_any: bool = False

    # ===== 浏览器引擎配置 =====
    max_rooms: int = 10
    browser_headless: bool = True

    # ===== Cookie 存储 =====
    cookie_dir: str = "./cookie"

    # ===== 重连策略 =====
    reconnect_max_retries: int = 3
    reconnect_base_delay: float = 1.0

    # ===== 心跳保活 =====
    heartbeat_interval: int = 30

    # ===== 去重窗口 =====
    dedup_window_size: int = 300

    # ===== 代理引擎配置 =====
    used_proxy: bool = True
    cert_dir: str = "~/.mitmproxy"
    process_filter: str = "chrome,msedge,QQBrowser,360se,firefox,2345Explorer,iexplore"
    force_polling: bool = False
    auto_pause: bool = False
    ssl_decrypt_hostnames: str = ""

    @property
    def process_filter_list(self) -> list:
        """返回进程过滤白名单列表（逗号分割）"""
        if not self.process_filter:
            return []
        return [p.strip() for p in self.process_filter.split(",") if p.strip()]

    @property
    def ssl_decrypt_extra_hostnames(self) -> list:
        """返回额外的 SSL 解密域名列表（逗号分割）"""
        if not self.ssl_decrypt_hostnames:
            return []
        return [h.strip() for h in self.ssl_decrypt_hostnames.split(",") if h.strip()]

    @property
    def proxy_host(self) -> str:
        """返回代理服务器监听地址"""
        return "0.0.0.0" if self.listen_any else "127.0.0.1"

    @property
    def proxy_address(self) -> str:
        """返回完整的代理服务器地址"""
        return f"{self.proxy_host}:{self.proxy_port}"


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例

    Returns:
        Settings 实例
    """
    return Settings()