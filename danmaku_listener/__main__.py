"""danmaku-listen / danmaku-serve 命令行入口（契约 v1 阶段 0 DX 交付束 A）

用法（等价于 pip install -e 后的 ``danmaku-listen`` / ``danmaku-serve`` 命令）：

    python -m danmaku_listener listen <platform:room_id>   # 演示：单平台单房间，
                                                           # 标准化 JSON 打印 stdout，
                                                           # TTHW 计时输出 stderr
    python -m danmaku_listener serve [--config cfg.toml]   # 常驻服务（阶段 0 骨架）
    python -m danmaku_listener contract                    # 打印契约版本信息

TTHW 口径：进程启动 → 首条统一消息输出（毫秒），打印到 stderr（不污染 stdout 的
JSON 流）。单平台验收以此解耦 AUTOlive 可用性（DX 回归项：每引擎接入时本命令
必须保持可用）。
"""

import argparse
import asyncio
import json
import sys
import time

from loguru import logger

from danmaku_listener.contract import CONTRACT_VERSION

_T0 = time.perf_counter()

# stdout 只承载标准化 JSON 流；日志一律走 stderr（DX：管线友好）
logger.remove()
logger.add(sys.stderr, level="INFO")


def _tthw_print(first: bool) -> None:
    """TTHW 计时输出（stderr）"""
    if first:
        elapsed_ms = (time.perf_counter() - _T0) * 1000
        print(f"[tthw] first message after {elapsed_ms:.0f} ms", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="danmaku-listener", description="六平台弹幕监听")
    sub = parser.add_subparsers(dest="command", required=True)

    listen = sub.add_parser("listen", help="演示模式：监听单房间，标准化 JSON 打印 stdout")
    listen.add_argument("target", help="平台:房间ID，如 bilibili:23058")
    listen.add_argument("--timeout", type=float, default=60.0, help="等待首条消息的超时秒数")

    serve = sub.add_parser("serve", help="常驻服务：全引擎 + WS 推送（阶段 0 骨架）")
    serve.add_argument("--config", default=None, help="TOML 配置文件路径")

    sub.add_parser("contract", help="打印契约版本信息")
    return parser


def cmd_contract() -> int:
    print(json.dumps({
        "contract_version": CONTRACT_VERSION,
        "schema": "docs/contract/schema.json",
        "docs": ["docs/contract/schema.md", "docs/contract/mapping.md", "docs/contract/migration.md"],
    }, ensure_ascii=False, indent=2))
    return 0


async def cmd_listen(target: str, timeout: float) -> int:
    from danmaku_listener import DanmakuListener

    if ":" not in target:
        print(
            json.dumps({
                "error": "invalid_target",
                "reason": f"目标格式须为 平台:房间ID，收到 {target!r}",
                "fix": "示例：python -m danmaku_listener listen bilibili:23058",
                "docs": "docs/integration/autolive.md",
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    first = True
    got_message = asyncio.Event()

    async def handle(data: dict) -> None:
        nonlocal first
        _tthw_print(first)
        first = False
        got_message.set()
        print(json.dumps(data, ensure_ascii=False), flush=True)

    listener = DanmakuListener()
    listener.on_danmaku(handle)

    try:
        await asyncio.wait_for(listener.start([target]), timeout=timeout)
    except asyncio.TimeoutError:
        print(
            json.dumps({
                "error": "start_timeout",
                "reason": f"引擎启动超过 {timeout}s 未完成",
                "fix": "检查网络与平台房间号；部署前置检查见 docs/ops/compliance-review.md",
                "docs": "docs/ops/compliance-review.md",
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 3

    try:
        await asyncio.wait_for(got_message.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        print(
            json.dumps({
                "error": "no_message",
                "reason": "连接建立但超时未收到弹幕（房间可能未开播）",
                "fix": "确认房间正在直播；查看 docs/platforms/ 对应平台手册",
                "docs": "docs/contract/schema.md",
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 4

    await asyncio.sleep(1.0)
    await listener.stop()
    return 0


async def cmd_serve(config: str | None) -> int:
    """常驻服务骨架：WS 推送通道 + 引擎生命周期（阶段 0；引擎随阶段 1-5 接入）"""
    from danmaku_listener.config.settings import get_settings, load_toml_overrides

    settings = get_settings()
    overrides = load_toml_overrides(config) if config else {}
    if overrides:
        settings = settings.__class__(**overrides)

    print(
        json.dumps({
            "service": "danmaku-serve",
            "ws": f"ws://{settings.ws_bind}:{settings.ws_port}/ws",
            "contract_version": CONTRACT_VERSION,
            "engines_online": [],  # 阶段 1-5 接入后由引擎注册表填充
        }, ensure_ascii=False),
        flush=True,
    )
    # 阶段 0 骨架：WS 推送服务器与引擎注册表在后续单元接入；
    # 本命令保持存在以固定 CLI 面（DX 回归项）。
    print(
        "serve: engines registry lands with phase 1-5; contract channel wiring is next",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "contract":
        return cmd_contract()
    if args.command == "listen":
        return asyncio.run(cmd_listen(args.target, args.timeout))
    if args.command == "serve":
        return asyncio.run(cmd_serve(args.config))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
