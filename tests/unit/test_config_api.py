"""配置参数 API 测试（S2 设置面板）"""

import os

import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, MagicMock

from danmaku_listener.web.app import create_app
from danmaku_listener.web.bridge import DanmakuBridge


@pytest.fixture()
def config_file(tmp_path):
    return str(tmp_path / "config.local.toml")


@pytest.fixture()
def client(config_file):
    bridge = DanmakuBridge()
    app = create_app()
    app["bridge"] = bridge
    app["config_path"] = config_file

    async def _start():
        client = TestClient(TestServer(app))
        await client.start_server()
        return client

    return _start


@pytest.mark.asyncio
async def test_get_config_returns_whitelist(client, config_file):
    c = await client()
    resp = await c.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    expected = {"ws_port", "ws_token_file", "web_port", "max_rooms", "fast_retry_max",
                "slow_retry_cap_seconds", "bus_ring_capacity",
                "bus_dedup_window_seconds", "session_lifetime_seconds",
                # AutoDanmu [send] 白名单（ADR-002 T5）
                "send_enabled_platforms", "send_dry_run", "send_min_interval_seconds",
                "send_jitter_seconds", "send_rate_key", "send_circuit_threshold",
                "send_dedup_window_seconds", "send_max_length",
                "send_lock_timeout_seconds", "send_audit_file",
                "send_idempotency_index",
                "send_session_idle_timeout_seconds", "send_window_mode",
                "send_min_interval_overrides"}
    assert set(data["config"].keys()) == expected
    assert data["all_require_restart"] is True


@pytest.mark.asyncio
async def test_put_config_roundtrip_and_restart_echo(client, config_file):
    c = await client()
    resp = await c.put("/api/config", json={"config": {"bus_ring_capacity": 20000}})
    assert resp.status == 200
    data = await resp.json()
    assert data["config"]["bus_ring_capacity"] == 20000
    assert data["all_require_restart"] is True
    # TOML 持久化
    assert os.path.exists(config_file)
    content = open(config_file, encoding="utf-8").read()
    assert "ring_capacity = 20000" in content


@pytest.mark.asyncio
async def test_put_config_unknown_key_rejected(client):
    c = await client()
    resp = await c.put("/api/config", json={"config": {"not_a_setting": 1}})
    assert resp.status == 400
    data = await resp.json()
    assert "not_a_setting" in data["error"]


@pytest.mark.asyncio
async def test_put_config_invalid_value_rejected(client):
    c = await client()
    resp = await c.put("/api/config", json={"config": {"bus_ring_capacity": -5}})
    assert resp.status == 400
    data = await resp.json()
    assert "校验失败" in data["error"]


@pytest.mark.asyncio
async def test_put_config_persists_then_get_echoes(client, config_file):
    c = await client()
    await c.put("/api/config", json={"config": {"ws_port": 9999}})
    resp = await c.get("/api/config")
    data = await resp.json()
    assert data["config"]["ws_port"] == 9999
