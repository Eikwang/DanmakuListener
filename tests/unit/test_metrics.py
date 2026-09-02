"""性能指标收集测试

验证 MetricsCollector 的核心功能。
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from danmaku_listener.core import MetricsCollector


class TestMetricsCollector:
    """性能指标收集器测试"""

    @pytest.fixture
    def collector(self):
        """创建指标收集器实例"""
        return MetricsCollector()

    def test_initial_metrics_are_zero(self, collector):
        """测试初始指标为零"""
        metrics = collector.get_metrics()
        assert metrics["messages_received"] == 0
        assert metrics["messages_published"] == 0
        assert metrics["messages_filtered"] == 0
        assert metrics["reconnect_count"] == 0
        assert metrics["errors_count"] == 0
        assert metrics["active_rooms"] == 0

    def test_record_message_received(self, collector):
        """测试记录接收消息"""
        collector.record_message_received("room1")
        collector.record_message_received("room1")
        collector.record_message_received("room2")

        metrics = collector.get_metrics()
        assert metrics["messages_received"] == 3

    def test_record_message_published(self, collector):
        """测试记录发布消息"""
        collector.record_message_published()
        collector.record_message_published()

        metrics = collector.get_metrics()
        assert metrics["messages_published"] == 2

    def test_record_message_filtered(self, collector):
        """测试记录过滤消息"""
        collector.record_message_filtered()

        metrics = collector.get_metrics()
        assert metrics["messages_filtered"] == 1

    def test_record_reconnect(self, collector):
        """测试记录重连"""
        collector.record_reconnect("room1")
        collector.record_reconnect("room1")

        metrics = collector.get_metrics()
        assert metrics["reconnect_count"] == 2

    def test_record_error(self, collector):
        """测试记录错误"""
        collector.record_error()
        collector.record_error()
        collector.record_error()

        metrics = collector.get_metrics()
        assert metrics["errors_count"] == 3

    def test_set_active_rooms(self, collector):
        """测试设置活跃房间数"""
        collector.set_active_rooms(5)

        metrics = collector.get_metrics()
        assert metrics["active_rooms"] == 5

    def test_get_metrics_includes_runtime(self, collector):
        """测试获取指标包含运行时间"""
        metrics = collector.get_metrics()
        assert "uptime_seconds" in metrics
        assert metrics["uptime_seconds"] >= 0

    def test_get_metrics_includes_memory(self, collector):
        """测试获取指标包含内存信息"""
        metrics = collector.get_metrics()
        assert "memory_mb" in metrics
        assert isinstance(metrics["memory_mb"], (int, float))
        assert metrics["memory_mb"] >= 0

    def test_get_metrics_includes_throughput(self, collector):
        """测试获取指标包含吞吐量"""
        # 记录一些消息
        for _ in range(10):
            collector.record_message_received("room1")
            collector.record_message_published()

        metrics = collector.get_metrics()
        assert "messages_per_second" in metrics
        assert metrics["messages_per_second"] >= 0

    def test_reset_metrics(self, collector):
        """测试重置指标"""
        collector.record_message_received("room1")
        collector.record_message_published()
        collector.record_error()

        collector.reset()

        metrics = collector.get_metrics()
        assert metrics["messages_received"] == 0
        assert metrics["messages_published"] == 0
        assert metrics["errors_count"] == 0

    def test_get_metrics_returns_dict(self, collector):
        """测试获取指标返回字典"""
        metrics = collector.get_metrics()
        assert isinstance(metrics, dict)

    def test_get_metrics_has_all_keys(self, collector):
        """测试获取指标包含所有键"""
        metrics = collector.get_metrics()
        expected_keys = {
            "messages_received",
            "messages_published",
            "messages_filtered",
            "reconnect_count",
            "errors_count",
            "active_rooms",
            "uptime_seconds",
            "memory_mb",
            "messages_per_second",
        }
        assert expected_keys.issubset(set(metrics.keys()))

    def test_per_room_metrics(self, collector):
        """测试按房间统计消息"""
        collector.record_message_received("room1")
        collector.record_message_received("room1")
        collector.record_message_received("room2")

        metrics = collector.get_metrics()
        assert "per_room" in metrics
        assert metrics["per_room"]["room1"] == 2
        assert metrics["per_room"]["room2"] == 1

    def test_per_room_metrics_cleared_on_reset(self, collector):
        """测试重置后按房间统计清空"""
        collector.record_message_received("room1")
        collector.reset()

        metrics = collector.get_metrics()
        assert metrics["per_room"] == {}
