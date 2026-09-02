"""Task-10 Playwright 验收测试

验证标准：
8. 前端添加关键词 → 列表出现新标签
9. 前端删除关键词 → 列表移除该标签
10. 前端关闭过滤开关 → 开关状态变化
"""

from playwright.sync_api import sync_playwright
import urllib.request
import urllib.parse
import json

BASE_URL = "http://localhost:8765"


def cleanup():
    """清理服务端所有关键词和房间状态"""
    # 清空所有关键词
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}/api/keywords", timeout=3)
        data = json.loads(resp.read())
        for kw in data.get("keywords", []):
            encoded = urllib.parse.quote(kw, safe='')
            del_req = urllib.request.Request(
                f"{BASE_URL}/api/keywords/{encoded}",
                method='DELETE',
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(del_req, timeout=3)
    except Exception:
        pass
    # 清空房间
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
    # 确保过滤开关开启
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/keywords/toggle",
            data=json.dumps({"enabled": True}).encode(),
            method='PUT',
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def test_add_keyword_ui():
    """验证标准8: 前端添加关键词 → 列表出现新标签"""
    cleanup()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 确认初始为空
        kw_tags = page.locator(".keyword-tag")
        assert kw_tags.count() == 0, f"Expected 0 tags initially, got {kw_tags.count()}"

        # 输入关键词
        kw_input = page.locator("#keyword-input")
        kw_input.fill("广告")

        # 点击添加按钮
        add_btn = page.locator("#add-keyword-btn")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证关键词标签出现
        kw_tags = page.locator(".keyword-tag")
        assert kw_tags.count() == 1, f"Expected 1 keyword tag, got {kw_tags.count()}"

        # 验证标签内容
        first_tag = kw_tags.first
        assert "广告" in first_tag.inner_text(), f"Expected '广告' in tag, got: {first_tag.inner_text()}"

        # 验证输入框已清空
        assert kw_input.input_value() == "", "Input should be cleared after adding"

        print("✅ 验证标准8 通过: 添加关键词后列表出现新标签")
        browser.close()


def test_remove_keyword_ui():
    """验证标准9: 前端删除关键词 → 列表移除该标签"""
    cleanup()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 先添加关键词
        kw_input = page.locator("#keyword-input")
        kw_input.fill("代练")
        add_btn = page.locator("#add-keyword-btn")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证标签存在
        kw_tags = page.locator(".keyword-tag")
        assert kw_tags.count() == 1, f"Expected 1 tag, got {kw_tags.count()}"

        # 点击删除按钮
        remove_btn = page.locator(".keyword-tag .remove-btn")
        assert remove_btn.count() >= 1, "Remove button should exist"
        remove_btn.first.click()
        page.wait_for_timeout(1000)

        # 验证标签被移除
        kw_tags = page.locator(".keyword-tag")
        assert kw_tags.count() == 0, f"Expected 0 keyword tags, got {kw_tags.count()}"

        print("✅ 验证标准9 通过: 删除关键词后列表移除该标签")
        browser.close()


def test_keyword_filter_toggle_ui():
    """验证标准10: 前端关闭过滤开关 → 开关状态变化"""
    cleanup()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 确认过滤开关初始为开启
        filter_toggle = page.locator("#keyword-filter-toggle")
        assert filter_toggle.is_checked(), "Filter toggle should be enabled initially"

        # 关闭过滤
        filter_slider = page.locator("#keyword-filter-toggle + .slider")
        filter_slider.click()
        page.wait_for_timeout(1000)

        # 验证开关已关闭
        assert not filter_toggle.is_checked(), "Filter toggle should be disabled after click"

        # 刷新页面验证持久化
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 验证状态从服务器加载
        filter_toggle = page.locator("#keyword-filter-toggle")
        assert not filter_toggle.is_checked(), "Filter toggle should remain disabled after refresh"

        # 重新开启
        filter_slider = page.locator("#keyword-filter-toggle + .slider")
        filter_slider.click()
        page.wait_for_timeout(1000)

        assert filter_toggle.is_checked(), "Filter toggle should be re-enabled"

        print("✅ 验证标准10 通过: 过滤开关可以切换并持久化")
        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Task-10 Playwright 验收测试")
    print("=" * 60)

    results = []
    tests = [
        ("验证标准8: 添加关键词", test_add_keyword_ui),
        ("验证标准9: 删除关键词", test_remove_keyword_ui),
        ("验证标准10: 过滤开关", test_keyword_filter_toggle_ui),
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
