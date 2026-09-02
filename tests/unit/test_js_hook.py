"""Task-12: JS Hook — 无操作检测绕过 测试

验证 DanmakuAddon._hook_js() 方法：
- PausePop.js + JS + 200 + 匹配正则 → 替换为 if(false){ → AC-015
- 非 pausepop 文件 → 不修改
- status_code=304 → 不处理
- 非 JS → 不处理
- JS 中无匹配 → 不修改，不报错
- force_polling=True → if(!this.stopPolling) 替换为 if(true)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class MockHeaders(dict):
    """可变 headers 容器，大小写不敏感"""

    def get(self, key, default=""):
        key_lower = key.lower()
        for k, v in self.items():
            if k.lower() == key_lower:
                return v
        return default

    def __contains__(self, key):
        key_lower = key.lower()
        return any(k.lower() == key_lower for k in self.keys())


def _make_mock_settings(**overrides):
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


def _make_js_flow(
    url="https://lf-webcast-platform.bytetos.com/obj/fe-app-live/PausePop.ec38fcf8.js",
    content_type="application/javascript",
    status_code=200,
    body="",
):
    """构造 mock JS HTTPFlow"""
    flow = MagicMock()
    flow.request = MagicMock()
    flow.request.pretty_url = url

    # 提取 host 用于 domain 检查
    from urllib.parse import urlparse
    flow.request.host = urlparse(url).hostname or "example.com"

    flow.response = MagicMock()
    flow.response.status_code = status_code
    flow.response.headers = MockHeaders({"Content-Type": content_type})
    flow.response.get_text = MagicMock(return_value=body)
    flow.response.set_text = MagicMock()

    return flow


class TestJSHookPausePop:
    """PausePop 无操作检测绕过测试 → AC-015"""

    def test_pausepop_js_replaced(self):
        """PausePop.js + JS + 200 + 匹配正则 → 替换为 if(false){ → AC-015"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        js_body = 'some code;if(!(0,a.DJ)()&&a.includes("live")){more code}'
        flow = _make_js_flow(body=js_body)
        addon.response(flow)

        flow.response.set_text.assert_called_once()
        new_js = flow.response.set_text.call_args[0][0]
        assert "if(false){" in new_js
        # 原始模式不应存在
        assert 'if(!(0,a.DJ)()&&a.includes("live")){' not in new_js

    def test_non_pausepop_file_not_modified(self):
        """文件名不以 pausepop 开头 → 不修改响应体"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_js_flow(
            url="https://lf-webcast-platform.bytetos.com/obj/fe-app-live/SomeOther.ec38fcf8.js",
            body='some code;if(!(0,a.DJ)()&&a.includes("live")){more code}',
        )
        addon.response(flow)

        flow.response.set_text.assert_not_called()

    def test_304_response_not_processed(self):
        """status_code=304 → 不处理"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_js_flow(
            status_code=304,
            body='if(!(0,a.DJ)()&&a.includes("live")){code}',
        )
        addon.response(flow)

        flow.response.set_text.assert_not_called()

    def test_non_js_content_type_not_processed(self):
        """content_type="text/html" → 不处理"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_js_flow(
            content_type="text/html",
            body='if(!(0,a.DJ)()&&a.includes("live")){code}',
        )
        addon.response(flow)

        flow.response.set_text.assert_not_called()

    def test_no_matching_pattern_no_modification(self):
        """JS 中无匹配正则 → 不修改响应体，不报错"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        flow = _make_js_flow(body="var x = 1; console.log(x);")
        addon.response(flow)

        flow.response.set_text.assert_not_called()

    def test_pausepop_case_insensitive(self):
        """文件名 PausePop（大写）也能匹配"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        js_body = 'if(!(0,a.DJ)()&&a.includes("live")){code}'
        flow = _make_js_flow(
            url="https://cdn.example.com/PausePop.abc123.js",
            body=js_body,
        )
        addon.response(flow)

        flow.response.set_text.assert_called_once()


class TestJSHookForcePolling:
    """force_polling 配置测试"""

    def test_force_polling_replaces_stop_polling(self):
        """force_polling=True → if(!this.stopPolling) 替换为 if(true)"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings(force_polling=True)
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        js_body = 'if(!this.stopPolling){this.startPolling()}'
        flow = _make_js_flow(body=js_body)
        addon.response(flow)

        flow.response.set_text.assert_called_once()
        new_js = flow.response.set_text.call_args[0][0]
        assert "if(true){" in new_js
        assert "if(!this.stopPolling){" not in new_js

    def test_force_polling_false_no_replacement(self):
        """force_polling=False → 不替换 stopPolling"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings(force_polling=False)
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        js_body = 'if(!this.stopPolling){this.startPolling()}'
        flow = _make_js_flow(body=js_body)
        addon.response(flow)

        # 没有 PausePop 模式也没有 force_polling 的 PausePop 文件
        # force_polling 只在 PausePop 文件中生效
        flow.response.set_text.assert_not_called()
