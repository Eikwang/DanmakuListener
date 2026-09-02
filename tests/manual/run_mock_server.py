"""Task-06 验收测试脚本

启动带 mock engine 的 web 服务，用 Playwright 验证房间管理 UI。
运行后手动停止（Ctrl+C 或 kill 进程）。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import TestServer

from web.app import create_app
from web.bridge import DanmakuBridge


def create_mock_bridge():
    """创建 mock 桥接器"""
    bridge = DanmakuBridge()
    bridge._listener = MagicMock()
    bridge._listener.start = AsyncMock()
    bridge._listener.stop = AsyncMock()
    return bridge


async def run_server():
    """启动测试服务器"""
    bridge = create_mock_bridge()
    app = create_app()
    app["bridge"] = bridge

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8765, reuse_address=True)
    await site.start()
    print("Mock server started on http://localhost:8765")
    print("Bridge stored in app['bridge']")
    # 保存 bridge 到全局供测试脚本访问
    import __main__
    __main__.bridge = bridge
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(run_server())
