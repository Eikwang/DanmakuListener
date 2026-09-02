"""Task-08 Playwright 验收测试

验证标准：
1. 收到 {"type": "danmaku", "data": {...}} → 弹幕区域出现新条目，显示用户名和内容
2. 普通弹幕样式与礼物弹幕样式不同（礼物高亮）
3. 系统消息样式为灰色
4. 弹幕区域自动滚动到底部
5. 超过 500 条时，最旧的弹幕被移除（DOM 节点数不超过 500）
6. 点击暂停按钮 → 弹幕继续接收但不自动滚动
"""

from playwright.sync_api import sync_playwright
import json
import urllib.request
import time

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


def test_danmaku_display():
    """验证标准1: 收到弹幕消息 → 弹幕区域出现新条目，显示用户名和内容"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 监听 WebSocket 消息
        ws_messages = []
        page.on("websocket", lambda ws: ws.on("framereceived",
            lambda payload: ws_messages.append(payload) if hasattr(payload, 'payload') else None))

        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 通过 JS 注入模拟 WebSocket 弹幕消息
        page.evaluate("""
            () => {
                const msg = JSON.stringify({
                    type: "danmaku",
                    data: {
                        platform: "douyin",
                        room_id: "123456",
                        user_name: "测试用户",
                        content: "你好世界",
                        timestamp: 1722000000,
                        message_type: "normal"
                    }
                });
                window.app.handleMessage(msg);
            }
        """)
        page.wait_for_timeout(500)

        # 验证弹幕区域出现新条目
        items = page.locator(".danmaku-item")
        assert items.count() >= 1, f"Expected at least 1 danmaku item, got {items.count()}"

        # 验证显示用户名和内容
        first_item = items.first
        inner_text = first_item.inner_text()
        assert "测试用户" in inner_text, f"Expected user name in danmaku, got: {inner_text}"
        assert "你好世界" in inner_text, f"Expected content in danmaku, got: {inner_text}"

        print("✅ 验证标准1 通过: 弹幕区域出现新条目，显示用户名和内容")
        browser.close()


def test_gift_vs_normal_style():
    """验证标准2: 普通弹幕样式与礼物弹幕样式不同（礼物高亮）"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 注入普通弹幕
        page.evaluate("""
            () => {
                window.app.handleMessage(JSON.stringify({
                    type: "danmaku",
                    data: { platform: "douyin", room_id: "123", user_name: "用户1",
                            content: "普通弹幕", timestamp: 1722000000, message_type: "normal" }
                }));
            }
        """)

        # 注入礼物弹幕
        page.evaluate("""
            () => {
                window.app.handleMessage(JSON.stringify({
                    type: "danmaku",
                    data: { platform: "douyin", room_id: "123", user_name: "用户2",
                            content: "送出了火箭", timestamp: 1722000001, message_type: "gift",
                            gift_info: { gift_name: "火箭", gift_count: 1 } }
                }));
            }
        """)
        page.wait_for_timeout(500)

        # 验证普通弹幕有 danmaku-item 类
        normal_item = page.locator(".danmaku-item.normal")
        assert normal_item.count() >= 1, "Expected normal danmaku item"

        # 验证礼物弹幕有 gift 类
        gift_item = page.locator(".danmaku-item.gift")
        assert gift_item.count() >= 1, "Expected gift danmaku item"

        # 验证样式不同（礼物有背景色）
        normal_bg = normal_item.first.evaluate("el => getComputedStyle(el).backgroundColor")
        gift_bg = gift_item.first.evaluate("el => getComputedStyle(el).backgroundColor")
        assert normal_bg != gift_bg, f"Normal and gift should have different backgrounds: normal={normal_bg}, gift={gift_bg}"

        print("✅ 验证标准2 通过: 普通弹幕和礼物弹幕样式不同")
        browser.close()


def test_system_message_style():
    """验证标准3: 系统消息样式为灰色"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 注入系统消息
        page.evaluate("""
            () => {
                window.app.handleMessage(JSON.stringify({
                    type: "danmaku",
                    data: { platform: "douyin", room_id: "123", user_name: "用户A",
                            content: "进入了直播间", timestamp: 1722000000, message_type: "system" }
                }));
            }
        """)
        page.wait_for_timeout(500)

        # 验证系统消息有 system 类
        system_item = page.locator(".danmaku-item.system")
        assert system_item.count() >= 1, "Expected system danmaku item"

        # 验证颜色为灰色（italic 或灰色文字）
        color = system_item.first.evaluate("el => getComputedStyle(el).color")
        font_style = system_item.first.evaluate("el => getComputedStyle(el).fontStyle")
        # 灰色文字或斜体
        is_gray = "128" in color or "160" in color or "170" in color or "a0" in color
        is_italic = font_style == "italic"
        assert is_gray or is_italic, f"System message should be gray or italic: color={color}, fontStyle={font_style}"

        print("✅ 验证标准3 通过: 系统消息样式为灰色/斜体")
        browser.close()


def test_auto_scroll():
    """验证标准4: 弹幕区域自动滚动到底部"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 注入大量弹幕使容器可滚动
        page.evaluate("""
            () => {
                for (let i = 0; i < 50; i++) {
                    window.app.handleMessage(JSON.stringify({
                        type: "danmaku",
                        data: { platform: "douyin", room_id: "123", user_name: "用户" + i,
                                content: "弹幕内容 " + i, timestamp: 1722000000 + i, message_type: "normal" }
                    }));
                }
            }
        """)
        page.wait_for_timeout(500)

        # 验证容器滚动到底部
        container = page.locator("#danmaku-container")
        scroll_result = container.evaluate("el => ({ scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight })")
        # scrollTop + clientHeight 应接近 scrollHeight
        at_bottom = scroll_result["scrollTop"] + scroll_result["clientHeight"] >= scroll_result["scrollHeight"] - 10
        assert at_bottom, f"Container should be scrolled to bottom: scrollTop={scroll_result['scrollTop']}, scrollHeight={scroll_result['scrollHeight']}"

        print("✅ 验证标准4 通过: 弹幕区域自动滚动到底部")
        browser.close()


def test_max_500_items():
    """验证标准5: 超过 500 条时，最旧的弹幕被移除"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 注入 600 条弹幕
        page.evaluate("""
            () => {
                for (let i = 0; i < 600; i++) {
                    window.app.handleMessage(JSON.stringify({
                        type: "danmaku",
                        data: { platform: "douyin", room_id: "123", user_name: "用户" + i,
                                content: "弹幕 " + i, timestamp: 1722000000 + i, message_type: "normal" }
                    }));
                }
            }
        """)
        page.wait_for_timeout(1000)

        # 验证 DOM 节点数不超过 500
        container = page.locator("#danmaku-container")
        child_count = container.evaluate("el => el.children.length")
        assert child_count <= 500, f"Expected at most 500 items, got {child_count}"

        # 验证最旧的消息被移除（第一条应该是 "弹幕 100" 而不是 "弹幕 0"）
        first_item = page.locator(".danmaku-item").first
        first_text = first_item.inner_text()
        assert "弹幕 0" not in first_text, f"Oldest items should be removed, but found: {first_text}"

        print("✅ 验证标准5 通过: 超过 500 条时最旧的弹幕被移除")
        browser.close()


def test_scroll_toggle():
    """验证标准6: 点击暂停按钮 → 弹幕继续接收但不自动滚动"""
    cleanup_rooms()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 先注入一些弹幕
        page.evaluate("""
            () => {
                for (let i = 0; i < 30; i++) {
                    window.app.handleMessage(JSON.stringify({
                        type: "danmaku",
                        data: { platform: "douyin", room_id: "123", user_name: "用户" + i,
                                content: "弹幕 " + i, timestamp: 1722000000 + i, message_type: "normal" }
                    }));
                }
            }
        """)
        page.wait_for_timeout(500)

        # 点击暂停滚动按钮
        scroll_btn = page.locator("#scroll-toggle-btn")
        assert scroll_btn.count() == 1, "Scroll toggle button should exist"
        btn_text_before = scroll_btn.inner_text()
        scroll_btn.click()

        # 验证按钮文字变化
        btn_text_after = scroll_btn.inner_text()
        assert btn_text_before != btn_text_after, f"Button text should change after click: before={btn_text_before}, after={btn_text_after}"

        # 验证 autoScroll 状态
        auto_scroll = page.evaluate("() => window.app.autoScroll")
        assert auto_scroll == False, "autoScroll should be false after clicking pause"

        # 注入更多弹幕
        container = page.locator("#danmaku-container")
        scroll_before = container.evaluate("el => el.scrollTop")

        page.evaluate("""
            () => {
                for (let i = 30; i < 60; i++) {
                    window.app.handleMessage(JSON.stringify({
                        type: "danmaku",
                        data: { platform: "douyin", room_id: "123", user_name: "用户" + i,
                                content: "弹幕 " + i, timestamp: 1722000030 + i, message_type: "normal" }
                    }));
                }
            }
        """)
        page.wait_for_timeout(500)

        # 验证弹幕继续接收（数量增加）
        item_count = page.locator(".danmaku-item").count()
        assert item_count >= 60, f"Danmaku should still be received: got {item_count} items"

        # 验证不自动滚动（scrollTop 不变或变化很小）
        scroll_after = container.evaluate("el => el.scrollTop")
        # 暂停后 scrollTop 不应大幅增加
        scroll_delta = scroll_after - scroll_before
        # 允许小幅度变化（浏览器可能自动调整），但不应滚动到底部
        scroll_height = container.evaluate("el => el.scrollHeight")
        client_height = container.evaluate("el => el.clientHeight")
        not_at_bottom = (scroll_after + client_height) < scroll_height - 5
        assert not_at_bottom or scroll_delta < 50, \
            f"Should not auto-scroll to bottom when paused: delta={scroll_delta}, scrollHeight={scroll_height}"

        print("✅ 验证标准6 通过: 暂停后弹幕继续接收但不自动滚动")
        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Task-08 Playwright 验收测试")
    print("=" * 60)

    results = []
    tests = [
        ("验证标准1: 弹幕显示用户名和内容", test_danmaku_display),
        ("验证标准2: 普通/礼物弹幕样式不同", test_gift_vs_normal_style),
        ("验证标准3: 系统消息灰色样式", test_system_message_style),
        ("验证标准4: 自动滚动到底部", test_auto_scroll),
        ("验证标准5: 500条上限", test_max_500_items),
        ("验证标准6: 暂停/恢复滚动", test_scroll_toggle),
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
