"""Task-07: DanmakuAddon 骨架 测试

验证 DanmakuAddon 类：
- 可实例化，注入 message_callback 和 settings
- 包含 ssl_checker (SSLWhitelistChecker) 和 process_filter (ProcessFilter) 属性
- 所有 mitmproxy 钩子方法骨架不抛异常
- http_connect 钩子根据 SSL 白名单决定是否解密
- tls_clienthello 钩子根据白名单设置 ignore_connection
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass


def _make_mock_settings(**overrides):
    """构造 mock Settings 对象"""
    defaults = {
        "used_proxy": True,
        "cert_dir": "~/.mitmproxy",
        "process_filter": "chrome,msedge",
        "force_polling": False,
        "auto_pause": False,
        "ssl_decrypt_hostnames": "",
        "process_filter_list": ["chrome", "msedge"],
        "ssl_decrypt_extra_hostnames": [],
        "dedup_window_size": 300,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_mock_flow(
    host="example.com", port=443,
    client_port=12345,
    content_type="text/html",
    status_code=200,
    ws_messages=None,
):
    """构造 mock HTTPFlow 对象"""
    flow = MagicMock()
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.port = port
    flow.request.pretty_url = f"https://{host}/path"
    flow.request.url = f"https://{host}/path"

    flow.client_conn = MagicMock()
    flow.client_conn.peername = ("127.0.0.1", client_port)

    flow.response = MagicMock()
    flow.response.headers = MagicMock()
    flow.response.headers.get = MagicMock(return_value=content_type)
    flow.response.status_code = status_code

    if ws_messages is not None:
        flow.websocket = MagicMock()
        flow.websocket.messages = ws_messages
    else:
        flow.websocket = None

    return flow


def _make_mock_tls_data(hostname="example.com"):
    """构造 mock ClientHelloData 对象"""
    data = MagicMock()
    data.client_hello = MagicMock()
    data.client_hello.sni = hostname
    data.context = MagicMock()
    data.ignore_connection = False
    data.establish_server_tls_first = False
    return data


class TestDanmakuAddonInit:
    """DanmakuAddon 初始化测试"""

    def test_instantiation_with_callback_and_settings(self):
        """DanmakuAddon(message_callback, settings) 可实例化"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert addon is not None

    def test_has_message_callback(self):
        """addon._message_callback 是传入的回调函数"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert addon._message_callback is cb

    def test_has_settings(self):
        """addon._settings 是传入的配置"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert addon._settings is settings

    def test_has_ssl_checker(self):
        """addon.ssl_checker 是 SSLWhitelistChecker 实例"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert isinstance(addon.ssl_checker, SSLWhitelistChecker)

    def test_has_process_filter(self):
        """addon.process_filter 是 ProcessFilter 实例"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        from danmaku_listener.engines.process_filter import ProcessFilter
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert isinstance(addon.process_filter, ProcessFilter)

    def test_ssl_checker_with_extra_hostnames(self):
        """settings.ssl_decrypt_extra_hostnames 传入 SSLWhitelistChecker"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings(ssl_decrypt_extra_hostnames=["custom.example.com"])
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        assert "custom.example.com" in addon.ssl_checker.extra_hostnames


class TestDanmakuAddonHooksSkeleton:
    """钩子方法骨架测试 — 不抛异常"""

    def test_http_connect_no_exception(self):
        """addon.http_connect(flow) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        flow = _make_mock_flow()
        # 不应抛异常
        addon.http_connect(flow)

    def test_tls_clienthello_no_exception(self):
        """addon.tls_clienthello(data) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data()
        # 不应抛异常
        addon.tls_clienthello(data)

    def test_response_no_exception(self):
        """addon.response(flow) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        flow = _make_mock_flow()
        # 不应抛异常
        addon.response(flow)

    def test_websocket_start_no_exception(self):
        """addon.websocket_start(flow) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        flow = _make_mock_flow(ws_messages=[])
        # 不应抛异常
        addon.websocket_start(flow)

    def test_websocket_message_no_exception(self):
        """addon.websocket_message(flow) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        msg = MagicMock()
        msg.from_client = False
        msg.content = b"test"
        flow = _make_mock_flow(ws_messages=[msg])
        # 不应抛异常
        addon.websocket_message(flow)

    def test_websocket_end_no_exception(self):
        """addon.websocket_end(flow) 不抛异常"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        flow = _make_mock_flow(ws_messages=[])
        # 不应抛异常
        addon.websocket_end(flow)


class TestDanmakuAddonSSLDecision:
    """SSL 解密决策测试 → AC-002, AC-014, AC-016"""

    def test_tls_clienthello_whitelist_host_decrypt(self):
        """白名单域名 → ignore_connection=False（允许解密）→ AC-002"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data(hostname="webcast3-ws-web-1.douyin.com")
        addon.tls_clienthello(data)
        assert data.ignore_connection is False

    def test_tls_clienthello_non_whitelist_host_passthrough(self):
        """非白名单域名 → ignore_connection=True（直接转发不解密）→ AC-014"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data(hostname="www.baidu.com")
        addon.tls_clienthello(data)
        assert data.ignore_connection is True

    def test_tls_clienthello_live_douyin_decrypt(self):
        """live.douyin.com → 允许解密"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data(hostname="live.douyin.com")
        addon.tls_clienthello(data)
        assert data.ignore_connection is False

    def test_tls_clienthello_github_passthrough(self):
        """github.com → 不解密 → AC-016"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data(hostname="github.com")
        addon.tls_clienthello(data)
        assert data.ignore_connection is True

    def test_tls_clienthello_extra_hostname_decrypt(self):
        """额外域名 → 允许解密"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon
        cb = AsyncMock()
        settings = _make_mock_settings(ssl_decrypt_extra_hostnames=["custom.example.com"])
        addon = DanmakuAddon(message_callback=cb, settings=settings)
        data = _make_mock_tls_data(hostname="custom.example.com")
        addon.tls_clienthello(data)
        assert data.ignore_connection is False
