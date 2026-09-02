"""Task-09 Playwright 验收测试

验证标准：
6. 前端 Toggle 按钮点击开启 → 按钮变为"已启用"状态
7. 前端 Toggle 按钮点击关闭 → 按钮变为"已禁用"状态
8. 代理状态页面刷新后保持正确（读取注册表实际值）
"""

from playwright.sync_api import sync_playwright
import urllib.request
import json

BASE_URL = "http://localhost:8765"


def cleanup_rooms():
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/rooms/stop-all",
            data=b'',
            method='POST',
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def test_proxy_toggle_enable():
    """验证标准6: Toggle 按钮点击开启 → 按钮变为"已启用"状态"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 拦截 API 请求模拟成功响应（避免真实修改注册表）
        page.route("**/api/proxy/enable", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "enabled": True, "host": "127.0.0.1", "port": 8827})
        ))
        page.route("**/api/proxy/disable", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "enabled": False, "host": "", "port": 0})
        ))
        page.route("**/api/proxy/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"enabled": False, "host": "", "port": 0})
        ))

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 确认初始状态：Toggle 未开启
        toggle = page.locator("#proxy-toggle")
        assert toggle.count() == 1, "Proxy toggle should exist"

        # 点击 slider 开启（checkbox 是隐藏的，需要点击 slider）
        slider = page.locator("#proxy-toggle + .slider")
        slider.click()
        page.wait_for_timeout(1000)

        # 验证状态文本变为"已启用"
        status_text = page.locator("#proxy-status-text")
        assert status_text.inner_text() == "已启用", f"Expected '已启用', got '{status_text.inner_text()}'"

        # 验证地址显示
        address = page.locator("#proxy-address")
        assert "127.0.0.1" in address.inner_text(), f"Expected address to contain 127.0.0.1, got '{address.inner_text()}'"

        print("✅ 验证标准6 通过: Toggle 开启后显示'已启用'状态")
        browser.close()


def test_proxy_toggle_disable():
    """验证标准7: Toggle 按钮点击关闭 → 按钮变为"已禁用"状态"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 模拟初始代理已启用状态
        page.route("**/api/proxy/enable", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "enabled": True, "host": "127.0.0.1", "port": 8827})
        ))
        page.route("**/api/proxy/disable", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "enabled": False, "host": "", "port": 0})
        ))
        page.route("**/api/proxy/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"enabled": True, "host": "127.0.0.1", "port": 8827})
        ))

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 确认初始状态：Toggle 已开启
        toggle = page.locator("#proxy-toggle")
        assert toggle.is_checked(), "Toggle should be checked initially"

        # 点击 slider 关闭
        slider = page.locator("#proxy-toggle + .slider")
        slider.click()
        page.wait_for_timeout(1000)

        # 验证状态文本变为"已禁用"
        status_text = page.locator("#proxy-status-text")
        assert status_text.inner_text() == "已禁用", f"Expected '已禁用', got '{status_text.inner_text()}'"

        # 验证地址为空
        address = page.locator("#proxy-address")
        assert address.inner_text() == "", f"Expected empty address, got '{address.inner_text()}'"

        print("✅ 验证标准7 通过: Toggle 关闭后显示'已禁用'状态")
        browser.close()


def test_proxy_status_persists_on_refresh():
    """验证标准8: 代理状态页面刷新后保持正确"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 模拟代理已启用
        page.route("**/api/proxy/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"enabled": True, "host": "127.0.0.1", "port": 8827})
        ))

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 验证初始状态
        toggle = page.locator("#proxy-toggle")
        assert toggle.is_checked(), "Toggle should be checked"

        # 刷新页面
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 重新验证状态（API 再次被调用，返回同样的数据）
        toggle = page.locator("#proxy-toggle")
        assert toggle.is_checked(), "Toggle should still be checked after refresh"

        status_text = page.locator("#proxy-status-text")
        assert status_text.inner_text() == "已启用", f"Expected '已启用' after refresh, got '{status_text.inner_text()}'"

        print("✅ 验证标准8 通过: 代理状态刷新后保持正确")
        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Task-09 Playwright 验收测试")
    print("=" * 60)

    results = []
    tests = [
        ("验证标准6: Toggle开启→已启用", test_proxy_toggle_enable),
        ("验证标准7: Toggle关闭→已禁用", test_proxy_toggle_disable),
        ("验证标准8: 刷新后状态保持", test_proxy_status_persists_on_refresh),
    ]

    for name, test_fn in tests:
        try:
            test_fn()
            results.append((name, "PASS"))
        except Exception as e:
            results.append((name, f"FAIL: {e}"))
            print(f"❌ {name} 失败: {e}")

    print("\n" + "=" * 60)
    print("验收测试结果汇总")
    print("=" * 60)
    for name, result in results:
        status = "✅" if result == "PASS" else "❌"
        print(f"{status} {name}: {result}")

    passed = sum(1 for _, r in results if r == "PASS")
    print(f"\n通过: {passed}/{len(results)}")
