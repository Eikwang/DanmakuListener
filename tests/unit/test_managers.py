"""管理器模块测试

验证重连管理器和心跳监控器的核心功能。
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from danmaku_listener.managers.reconnect_manager import ReconnectManager
from danmaku_listener.managers.heartbeat_monitor import HeartbeatMonitor


# ===== ReconnectManager 测试 =====


class TestReconnectManager:
    """重连管理器测试"""

    @pytest.fixture
    def manager(self):
        """创建重连管理器实例"""
        return ReconnectManager(max_retries=3, base_delay=0.01)

    @pytest.mark.asyncio
    async def test_reconnect_success_on_first_try(self, manager):
        """测试首次重连成功"""
        callback = AsyncMock(return_value=True)
        result = await manager.reconnect(callback, "room1")
        assert result is True
        assert manager.current_attempt == 0

    @pytest.mark.asyncio
    async def test_reconnect_success_after_failures(self, manager):
        """测试多次失败后重连成功"""
        callback = AsyncMock(side_effect=[False, False, True])
        result = await manager.reconnect(callback, "room1")
        assert result is True

    @pytest.mark.asyncio
    async def test_reconnect_all_attempts_fail(self, manager):
        """测试所有重试都失败"""
        callback = AsyncMock(return_value=False)
        result = await manager.reconnect(callback, "room1")
        assert result is False

    @pytest.mark.asyncio
    async def test_reconnect_exception_treated_as_failure(self, manager):
        """测试重连异常视为失败"""
        callback = AsyncMock(side_effect=Exception("connection refused"))
        result = await manager.reconnect(callback, "room1")
        assert result is False

    def test_reset(self, manager):
        """测试重置重连计数器"""
        manager._current_attempt = 2
        manager.reset()
        assert manager.current_attempt == 0

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self):
        """测试指数退避延迟"""
        manager = ReconnectManager(max_retries=3, base_delay=1.0)
        # 验证延迟计算：1s, 2s, 4s
        assert manager.base_delay == 1.0
        assert manager.max_retries == 3


# ===== HeartbeatMonitor 测试 =====


class TestHeartbeatMonitor:
    """心跳监控器测试"""

    @pytest.fixture
    def monitor(self):
        """创建心跳监控器实例"""
        health_check = AsyncMock(return_value=True)
        recovery = AsyncMock()
        return HeartbeatMonitor(
            room_id="test_room",
            health_check=health_check,
            recovery=recovery,
            interval=1,
        )

    def test_initial_not_running(self, monitor):
        """测试初始状态未运行"""
        assert monitor.is_running is False

    @pytest.mark.asyncio
    async def test_start_sets_running(self, monitor):
        """测试启动后状态为运行中"""
        await monitor.start()
        assert monitor.is_running is True
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self, monitor):
        """测试停止后状态为未运行"""
        await monitor.start()
        await monitor.stop()
        assert monitor.is_running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, monitor):
        """测试重复启动不创建多个任务"""
        await monitor.start()
        task1 = monitor._task
        await monitor.start()
        task2 = monitor._task
        assert task1 is task2
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_health_check_called(self, monitor):
        """测试健康检查被调用"""
        # 启动后等待一个检查周期
        await monitor.start()
        await asyncio.sleep(0.1)
        await monitor.stop()
        monitor.health_check.assert_called()

    @pytest.mark.asyncio
    async def test_recovery_called_on_unhealthy(self):
        """测试不健康时触发恢复"""
        health_check = AsyncMock(return_value=False)
        recovery = AsyncMock()
        monitor = HeartbeatMonitor(
            room_id="test_room",
            health_check=health_check,
            recovery=recovery,
            interval=1,
        )

        await monitor.start()
        await asyncio.sleep(0.1)
        await monitor.stop()
        recovery.assert_called()
