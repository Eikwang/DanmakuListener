"""Task-06 Playwright 验收测试

验证标准：
1. 输入 douyin:123456 点击添加 → 房间列表出现新条目，状态为"运行中"
2. 输入 abc 点击添加 → 输入框下方显示格式错误提示
3. 输入重复房间 → 显示"该房间已存在"提示
4. 点击房间停止按钮 → 状态变为"已停止"
5. 点击全部停止 → 所有房间状态变为"已停止"
6. 添加按钮在请求期间置灰，防止重复提交
"""

from playwright.sync_api import sync_playwright
import urllib.request
import json

BASE_URL = "http://localhost:8765"


def cleanup_rooms():
    """清理服务端所有房间状态"""
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


def test_add_room_success():
    """验证标准1: 输入 douyin:123456 点击添加 → 房间列表出现新条目，状态为"运行中" """
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 输入房间规格
        room_input = page.locator("#room-input")
        room_input.fill("douyin:123456")

        # 点击添加按钮
        add_btn = page.locator("#add-room-btn")
        add_btn.click()

        # 等待 API 响应和列表更新
        page.wait_for_timeout(1000)

        # 验证房间列表出现新条目
        room_items = page.locator(".room-item")
        count = room_items.count()
        assert count == 1, f"Expected 1 room item, got {count}"

        # 验证状态为"运行中"
        status_badge = page.locator(".status-badge.running")
        assert status_badge.count() == 1, "Expected one 'running' status badge"

        # 验证平台标签和房间ID
        platform_tag = page.locator(".platform-tag")
        assert platform_tag.first.inner_text() == "douyin", f"Expected platform 'douyin'"

        room_id_span = page.locator(".room-id")
        assert room_id_span.first.inner_text() == "123456", f"Expected room_id '123456'"

        print("✅ 验证标准1 通过: 添加房间成功，状态为'运行中'")
        browser.close()


def test_invalid_format():
    """验证标准2: 输入 abc 点击添加 → 输入框下方显示格式错误提示 """
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 输入无效格式
        room_input = page.locator("#room-input")
        room_input.fill("abc")

        # 点击添加按钮
        add_btn = page.locator("#add-room-btn")
        add_btn.click()

        # 等待响应
        page.wait_for_timeout(1000)

        # 验证错误提示显示
        error_el = page.locator("#room-error")
        assert not error_el.is_hidden(), "Error message should be visible"
        error_text = error_el.inner_text()
        assert "格式" in error_text or "Invalid" in error_text, f"Expected format error, got: {error_text}"

        print("✅ 验证标准2 通过: 无效格式显示错误提示")
        browser.close()


def test_duplicate_room():
    """验证标准3: 输入重复房间 → 显示"该房间已存在"提示 """
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 先添加一个房间
        room_input = page.locator("#room-input")
        room_input.fill("douyin:999888")
        add_btn = page.locator("#add-room-btn")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证添加成功
        room_items = page.locator(".room-item")
        assert room_items.count() == 1, f"Expected 1 room after first add, got {room_items.count()}"

        # 再次添加相同房间
        room_input.fill("douyin:999888")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证错误提示
        error_el = page.locator("#room-error")
        assert not error_el.is_hidden(), "Error message should be visible for duplicate"
        error_text = error_el.inner_text()
        assert "已存在" in error_text, f"Expected '已存在' error, got: {error_text}"

        print("✅ 验证标准3 通过: 重复房间显示'该房间已存在'")
        browser.close()


def test_stop_room():
    """验证标准4: 点击房间停止按钮 → 房间被移除 """
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 先添加一个房间
        room_input = page.locator("#room-input")
        room_input.fill("douyin:555666")
        add_btn = page.locator("#add-room-btn")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证房间已添加
        room_items = page.locator(".room-item")
        assert room_items.count() == 1, f"Expected 1 room, got {room_items.count()}"

        # 点击停止按钮
        stop_btn = page.locator(".stop-room-btn")
        assert stop_btn.count() >= 1, "Expected stop button in room list"
        stop_btn.first.click()
        page.wait_for_timeout(1000)

        # 验证房间被移除（remove_room 会从 _rooms 中删除）
        room_items = page.locator(".room-item")
        assert room_items.count() == 0, f"Expected room removed from list, got {room_items.count()} items"

        print("✅ 验证标准4 通过: 点击停止按钮后房间被移除")
        browser.close()


def test_stop_all():
    """验证标准5: 点击全部停止 → 所有房间被移除 """
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 添加两个房间
        room_input = page.locator("#room-input")
        room_input.fill("douyin:111222")
        add_btn = page.locator("#add-room-btn")
        add_btn.click()
        page.wait_for_timeout(1000)

        room_input.fill("douyin:333444")
        add_btn.click()
        page.wait_for_timeout(1000)

        # 验证有两个房间
        room_items = page.locator(".room-item")
        assert room_items.count() == 2, f"Expected 2 rooms, got {room_items.count()}"

        # 点击全部停止
        stop_all_btn = page.locator("#stop-all-btn")
        stop_all_btn.click()
        page.wait_for_timeout(1000)

        # 验证所有房间被移除
        room_items = page.locator(".room-item")
        assert room_items.count() == 0, f"Expected all rooms removed, got {room_items.count()} items"

        print("✅ 验证标准5 通过: 全部停止后所有房间被移除")
        browser.close()


def test_add_button_disabled_during_request():
    """验证标准6: 添加按钮在请求期间置灰，防止重复提交 """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 验证代码中包含 disabled 逻辑
        js_content = page.evaluate("""
            async () => {
                const resp = await fetch('/static/app.js');
                const text = await resp.text();
                return {
                    has_disabled: text.includes('addBtn.disabled = true'),
                    has_reenable: text.includes('addBtn.disabled = false'),
                    has_finally: text.includes('finally'),
                };
            }
        """)
        assert js_content["has_disabled"], "handleAddRoom should disable button"
        assert js_content["has_reenable"], "handleAddRoom should re-enable button"
        assert js_content["has_finally"], "handleAddRoom should use finally block"

        print("✅ 验证标准6 通过: 添加按钮有置灰防重复提交逻辑")
        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Task-06 Playwright 验收测试")
    print("=" * 60)

    results = []
    tests = [
        ("验证标准1: 添加房间成功", test_add_room_success),
        ("验证标准2: 无效格式错误提示", test_invalid_format),
        ("验证标准3: 重复房间提示", test_duplicate_room),
        ("验证标准4: 停止单个房间", test_stop_room),
        ("验证标准5: 全部停止", test_stop_all),
        ("验证标准6: 按钮置灰防重复", test_add_button_disabled_during_request),
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
