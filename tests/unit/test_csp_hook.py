"""Task-11: 页面 Hook — CSP 头删除 测试

验证 DanmakuAddon.response() 钩子：
- live.douyin.com + text/html + 有 CSP → CSP 被删除 → AC-006
- live.douyin.com + text/html + 无 CSP → 不报错
- 非抖音域名 + text/html + 有 CSP → 不删除
- live.douyin.com + 非 HTML → 不处理
- auto_pause=True → autoplay&quot;:true 替换为 autoplay&quot;:false
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class MockHeaders(dict):
    """可变 headers 容器，模拟 mitmproxy 的大小写不敏感 headers 行为"""

    def get(self, key, default=""):
        # 大小写不敏感查找
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


def _make_response_flow(
    host="live.douyin.com",
    content_type="text/html",
    status_code=200,
    headers=None,
    body=None,
):
    """构造 mock HTTPFlow 对象（带 response）"""
    flow = MagicMock()
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.pretty_url = f"https://{host}/path"

    flow.response = MagicMock()
    flow.response.status_code = status_code

    # 使用 MockHeaders 模拟可变 headers
    flow.response.headers = MockHeaders(headers or {})

    # 设置响应体
    if body is not None:
        flow.response.get_text = MagicMock(return_value=body)
        flow.response.set_text = MagicMock()
    else:
        flow.response.get_text = MagicMock(return_value="")
        flow.response.set_text = MagicMock()

    return flow


class TestCSPHeaderRemoval:
    """CSP 头删除测试 → AC-006"""

    def test_csp_removed_on_live_douyin_html(self):
        """live.douyin.com + text/html + 有 CSP → CSP 被删除 → AC-006"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Security-Policy": "default-src 'self'",
        }
        flow = _make_response_flow(host="live.douyin.com", headers=headers)
        addon.response(flow)

        assert "Content-Security-Policy" not in flow.response.headers

    def test_no_csp_no_error(self):
        """live.douyin.com + text/html + 无 CSP → 不报错"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        headers = {"Content-Type": "text/html; charset=utf-8"}
        flow = _make_response_flow(host="live.douyin.com", headers=headers)
        # 不应抛异常
        addon.response(flow)

    def test_csp_not_removed_on_other_domain(self):
        """www.baidu.com + text/html + 有 CSP → CSP 不被删除"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Security-Policy": "default-src 'self'",
        }
        flow = _make_response_flow(host="www.baidu.com", headers=headers)
        addon.response(flow)

        assert "Content-Security-Policy" in flow.response.headers

    def test_csp_not_removed_on_non_html(self):
        """live.douyin.com + application/json → 不处理"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        headers = {
            "Content-Type": "application/json",
            "Content-Security-Policy": "default-src 'self'",
        }
        flow = _make_response_flow(host="live.douyin.com", headers=headers)
        addon.response(flow)

        assert "Content-Security-Policy" in flow.response.headers

    def test_csp_removed_on_douyin_subdomain(self):
        """*.douyin.com + text/html → CSP 被删除"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings()
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        headers = {
            "Content-Type": "text/html",
            "Content-Security-Policy": "default-src 'self'",
        }
        flow = _make_response_flow(host="www.douyin.com", headers=headers)
        addon.response(flow)

        assert "Content-Security-Policy" not in flow.response.headers


class TestAutoPauseHook:
    """auto_pause 配置测试"""

    def test_auto_pause_true_replaces_autoplay(self):
        """auto_pause=True → autoplay&quot;:true 替换为 autoplay&quot;:false"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings(auto_pause=True)
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        body = '<script>var config = {autoplay&quot;:true, quality:"hd"}</script>'
        headers = {"Content-Type": "text/html"}
        flow = _make_response_flow(host="live.douyin.com", headers=headers, body=body)
        addon.response(flow)

        # set_text 应被调用，且内容中 autoplay&quot;:true 被替换
        flow.response.set_text.assert_called_once()
        new_text = flow.response.set_text.call_args[0][0]
        assert 'autoplay&quot;:false' in new_text
        assert 'autoplay&quot;:true' not in new_text

    def test_auto_pause_false_no_replacement(self):
        """auto_pause=False → 不替换 autoplay"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings(auto_pause=False)
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        body = '<script>var config = {autoplay&quot;:true, quality:"hd"}</script>'
        headers = {"Content-Type": "text/html"}
        flow = _make_response_flow(host="live.douyin.com", headers=headers, body=body)
        addon.response(flow)

        # set_text 不应被调用（仅 CSP 删除，不修改 body）
        flow.response.set_text.assert_not_called()

    def test_auto_pause_on_non_douyin_no_replacement(self):
        """auto_pause=True 但非抖音域名 → 不替换"""
        from danmaku_listener.engines.danmaku_addon import DanmakuAddon

        cb = AsyncMock()
        settings = _make_mock_settings(auto_pause=True)
        addon = DanmakuAddon(message_callback=cb, settings=settings)

        body = '<script>var config = {autoplay&quot;:true}</script>'
        headers = {"Content-Type": "text/html"}
        flow = _make_response_flow(host="www.baidu.com", headers=headers, body=body)
        addon.response(flow)

        flow.response.set_text.assert_not_called()
