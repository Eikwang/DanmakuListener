"""relogin 端点层 HTTP 契约测试（/ship Step 9.4 测试补充）

覆盖 web/app.py 的 POST /api/relogin 与 GET /api/relogin/status 的鉴权与
形态校验：token 未配置 503 / 错 token 401（POST 与 GET 同源）/ id 形态非法
400 / 未知 id 404（停止轮询契约）/ 坏平台 400 无副作用。编排内部逻辑见
test_web_relogin.py。
"""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from danmaku_listener.config import settings as settings_mod
from danmaku_listener.config.settings import Settings
from danmaku_listener.web.app import create_app

TOKEN = "endpoint-test-token"


def _install_token_env(monkeypatch, token_file=None):
    """植入确定性鉴权环境（monkeypatch 自动还原）：

    - _override_settings 覆盖 get_settings 单例（lru_cache 不动——最小侵入），
      ws_token_file 显式置 None 或指向 tmp_path token 文件（init 传参优先级
      最高，不受环境/toml 污染）
    - DANMAKU_TOKEN 环境变量清除，load_token 只走 token 文件路径
    """
    monkeypatch.setattr(settings_mod, "_override_settings",
                        Settings(ws_token_file=token_file))
    monkeypatch.delenv("DANMAKU_TOKEN", raising=False)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _write_token_file(tmp_path) -> str:
    token_file = tmp_path / "ws_token"
    token_file.write_text(TOKEN, encoding="utf-8")
    return str(token_file)


@pytest.fixture
async def client():
    """aiohttp TestClient（create_app 无参直用；bridge 懒加载，纯内存无外部副作用）"""
    async with TestClient(TestServer(create_app())) as c:
        yield c


# ---- 鉴权（503/401）----

async def test_relogin_post_503_when_token_unconfigured(client, monkeypatch):
    """无 token 配置（DANMAKU_TOKEN 清除 + ws_token_file=None）→ 503 AUTH_UNCONFIGURED"""
    _install_token_env(monkeypatch, token_file=None)
    resp = await client.post("/api/relogin", json={"platform": "huya", "room_id": "1"})
    assert resp.status == 503
    body = await resp.json()
    assert body["success"] is False
    assert body["error"] == "AUTH_UNCONFIGURED"
    assert "ws_token_file" in body["fix_hint"]


async def test_relogin_401_wrong_token_post_and_status_get(client, monkeypatch, tmp_path):
    """token 文件已配置 + 错 Bearer → 401（POST 与 GET status 同源鉴权）"""
    _install_token_env(monkeypatch, token_file=_write_token_file(tmp_path))
    resp = await client.post("/api/relogin",
                             json={"platform": "huya", "room_id": "1"},
                             headers=_auth("wrong-token"))
    assert resp.status == 401
    body = await resp.json()
    assert body["error"] == "unauthorized"

    # GET status 鉴权同源（id 合法形态无关——鉴权先短路）
    resp = await client.get("/api/relogin/status",
                            params={"id": "0" * 32},
                            headers=_auth("wrong-token"))
    assert resp.status == 401
    body = await resp.json()
    assert body["error"] == "unauthorized"


# ---- id 形态校验与未知 id（400/404）----

async def test_relogin_status_rejects_malformed_id(client, monkeypatch, tmp_path):
    """id 形态非法（路径穿越形态）→ 400，uuid 字符集校验前置"""
    _install_token_env(monkeypatch, token_file=_write_token_file(tmp_path))
    resp = await client.get("/api/relogin/status",
                            params={"id": "../../etc/passwd"},
                            headers=_auth(TOKEN))
    assert resp.status == 400
    body = await resp.json()
    assert "id 形态非法" in body["error"]


async def test_relogin_status_unknown_uuid_404(client, monkeypatch, tmp_path):
    """合法 uuid 形态但注册表无记录 → 404（AUTOlive 契约：停止轮询按未知终局处理）"""
    _install_token_env(monkeypatch, token_file=_write_token_file(tmp_path))
    resp = await client.get("/api/relogin/status",
                            params={"id": "00000000-0000-4000-8000-000000000000"},
                            headers=_auth(TOKEN))
    assert resp.status == 404
    body = await resp.json()
    assert "relogin_id 不可得" in body["error"]
    assert "停止轮询" in body["error"]


# ---- 坏平台（400 无副作用）----

async def test_relogin_post_unsupported_platform_400_no_side_effect(client, monkeypatch, tmp_path):
    """POST 坏平台 → ReloginUnsupported 映射 400（error 含「不支持」），异常不冒泡、
    注册表无新记录（ReloginUnsupported 在建记录之前抛出）"""
    from danmaku_listener.web.relogin import REGISTRY

    _install_token_env(monkeypatch, token_file=_write_token_file(tmp_path))
    resp = await client.post("/api/relogin",
                             json={"platform": "notaplatform", "room_id": "1"},
                             headers=_auth(TOKEN))
    assert resp.status == 400  # 异常被端点映射，未冒泡为 500
    body = await resp.json()
    assert body["success"] is False
    assert "不支持" in body["error"]
    assert len(REGISTRY._sessions) == 0
