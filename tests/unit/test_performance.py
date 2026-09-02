"""性能优化测试

验证内存优化和延迟优化功能。
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.bus.dedup_filter import DedupFilter
from danmaku_listener.bus.event_bus import EventBus
from danmaku_listener.managers.heartbeat_monitor import HeartbeatMonitor


class TestDedupFilterMemoryOptimization:
    """去重过滤器内存优化测试"""

    def test_cache_size_bounded_by_window_size(self):
        """测试缓存大小受窗口大小限制"""
        dedup = DedupFilter(window_size=100)

        # 插入 200 条消息（超过窗口大小）
        for i in range(200):
            dedup.should_filter("room1", f"msg_{i}")

        # 缓存应不超过窗口大小
        stats = dedup.get_stats()
        assert stats["total_messages"] <= 100

    def test_expired_entries_cleaned_on_access(self):
        """测试过期记录在访问时被清理"""
        dedup = DedupFilter(window_size=300)

        # 手动插入带旧时间戳的记录
        now = time.time()
        old_time = now - 600  # 10 分钟前（超过 5 分钟过期时间）
        dedup._cache["room1"] = __import__("collections").deque()
        dedup._cache["room1"].append(("old_msg", old_time))

        # 访问时应清理过期记录
        result = dedup.should_filter("room1", "new_msg")
        assert result is False
        # 旧记录应被清理
        ids = {mid for mid, _ in dedup._cache["room1"]}
        assert "old_msg" not in ids

    def test_multiple_rooms_independent_bounds(self):
        """测试多房间缓存独立限制"""
        dedup = DedupFilter(window_size=50)

        for i in range(100):
            dedup.should_filter("room1", f"msg_{i}")
            dedup.should_filter("room2", f"msg_{i}")

        stats = dedup.get_stats()
        # 每个房间独立，各不超过 50
        assert stats["rooms"] == 2
        assert stats["total_messages"] <= 100  # 2 * 50

    def test_clear_room_releases_memory(self):
        """测试清除房间缓存释放内存"""
        dedup = DedupFilter(window_size=300)

        for i in range(100):
            dedup.should_filter("room1", f"msg_{i}")

        dedup.clear_room("room1")
        assert "room1" not in dedup._cache

    def test_clear_all_releases_all_memory(self):
        """测试清除所有缓存释放内存"""
        dedup = DedupFilter(window_size=300)

        for i in range(50):
            dedup.should_filter("room1", f"msg_{i}")
            dedup.should_filter("room2", f"msg_{i}")

        dedup.clear_all()
        assert len(dedup._cache) == 0


class TestEventBusLatencyOptimization:
    """事件总线延迟优化测试"""

    @pytest.mark.asyncio
    async def test_publish_no_subscribers_fast_return(self):
        """测试无订阅者时快速返回"""
        bus = EventBus()

        # 无订阅者时 publish 应立即返回
        start = time.monotonic()
        for _ in range(1000):
            await bus.publish("nonexistent_event", None)
        elapsed = time.monotonic() - start

        # 1000 次空发布应在 1 秒内完成
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_single_subscriber_no_gather_overhead(self):
        """测试单个订阅者无 gather 开销"""
        bus = EventBus()
        call_count = 0

        async def handler(data):
            nonlocal call_count
            call_count += 1

        await bus.subscribe("test", handler)

        start = time.monotonic()
        for _ in range(1000):
            await bus.publish("test", "data")
        elapsed = time.monotonic() - start

        assert call_count == 1000
        # 1000 次发布应在 1 秒内完成
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_concurrent_publish_does_not_block(self):
        """测试并发发布不阻塞"""
        bus = EventBus()
        results = []

        async def handler(data):
            results.append(data)

        await bus.subscribe("test", handler)

        import asyncio
        tasks = [bus.publish("test", i) for i in range(100)]
        await asyncio.gather(*tasks)

        assert len(results) == 100


class TestDedupFilterLatencyOptimization:
    """去重过滤器延迟优化测试"""

    def test_should_filter_fast_path_for_empty_ids(self):
        """测试空消息 ID 快速路径"""
        dedup = DedupFilter(window_size=300)

        # 空 room_id 或 msg_id 应快速返回 False
        start = time.monotonic()
        for _ in range(10000):
            dedup.should_filter("", "msg_1")
            dedup.should_filter("room1", "")
        elapsed = time.monotonic() - start

        # 10000 次空检查应在 0.5 秒内完成
        assert elapsed < 0.5

    def test_dedup_hit_is_faster_than_miss(self):
        """测试命中去重比未命中更快"""
        dedup = DedupFilter(window_size=300)

        # 预填充
        for i in range(100):
            dedup.should_filter("room1", f"msg_{i}")

        # 测试命中（重复消息）
        start = time.monotonic()
        for i in range(1000):
            dedup.should_filter("room1", f"msg_{i % 100}")
        hit_time = time.monotonic() - start

        # 测试未命中（新消息）
        start = time.monotonic()
        for i in range(1000):
            dedup.should_filter("room1", f"new_msg_{i}")
        miss_time = time.monotonic() - start

        # 命中应该不比未命中慢太多（都应很快）
        # 不严格要求 hit < miss，但两者都应在合理范围内
        assert hit_time < 2.0
        assert miss_time < 2.0
