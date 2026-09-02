"""Task-03: SSL 白名单检查器 测试

验证 check_host() 和 SSLWhitelistChecker 的白名单匹配逻辑。
"""

import pytest


class TestCheckHost:
    """check_host 函数测试"""

    def test_webcast_ws_domain_matches(self):
        """webcast WS 域名匹配（正则 .*webcast.*）"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("webcast3-ws-web-1.douyin.com") is True

    def test_live_douyin_com_matches(self):
        """live.douyin.com 精确匹配"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("live.douyin.com") is True

    def test_webcast_amemv_com_matches(self):
        """webcast.amemv.com 精确匹配"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("webcast.amemv.com") is True

    def test_bytetos_wildcard_matches(self):
        """*-webcast-platform.bytetos.com 通配符匹配"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("lf-webcast-platform.bytetos.com") is True

    def test_baidu_not_matches(self):
        """www.baidu.com 不在白名单"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("www.baidu.com") is False

    def test_github_not_matches(self):
        """github.com 不在白名单"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("github.com") is False

    def test_case_insensitive(self):
        """大小写不敏感"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("WEBCAST3-WS-WEB-1.DOUYIN.COM") is True
        assert check_host("LIVE.DOUYIN.COM") is True

    def test_empty_string_not_matches(self):
        """空字符串不在白名单"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("") is False

    def test_script_cdn_matches(self):
        """lf-cdn-tos.bytescm.com 脚本CDN精确匹配"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("lf-cdn-tos.bytescm.com") is True

    def test_webcast_in_subdomain_matches(self):
        """含 webcast 的子域名匹配"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("webcast5-ws-web-abc.amemv.com") is True

    def test_partial_match_not_false_positive(self):
        """部分匹配不误判：webcast.com（不含 webcast 子域名模式）"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        # webcast.com 本身含 webcast，应匹配 .*webcast.* 正则
        assert check_host("webcast.com") is True

    def test_non_webcast_subdomain(self):
        """douyin.com（不含 webcast）不在白名单"""
        from danmaku_listener.engines.ssl_whitelist import check_host
        assert check_host("www.douyin.com") is False


class TestSSLWhitelistChecker:
    """SSLWhitelistChecker 类测试"""

    def test_default_whitelist(self):
        """默认白名单实例化"""
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        checker = SSLWhitelistChecker()
        assert checker is not None

    def test_extra_hostnames_appended(self):
        """额外域名追加到白名单"""
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        checker = SSLWhitelistChecker(extra_hostnames=["custom.example.com"])
        assert checker.check("custom.example.com") is True

    def test_extra_hostnames_not_replace_default(self):
        """额外域名不替换默认白名单"""
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        checker = SSLWhitelistChecker(extra_hostnames=["custom.example.com"])
        # 默认白名单仍生效
        assert checker.check("live.douyin.com") is True

    def test_extra_hostnames_empty(self):
        """空额外域名列表不影响默认白名单"""
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        checker = SSLWhitelistChecker(extra_hostnames=[])
        assert checker.check("live.douyin.com") is True
        assert checker.check("www.baidu.com") is False

    def test_check_method_delegates_to_check_host(self):
        """check() 方法与 check_host() 行为一致"""
        from danmaku_listener.engines.ssl_whitelist import SSLWhitelistChecker
        checker = SSLWhitelistChecker()
        assert checker.check("webcast3-ws-web-1.douyin.com") is True
        assert checker.check("github.com") is False
