"""WS 消费助手：连接 danmaku-serve 推送通道，按类别打印消息

用法：
    python tools/ws_listen.py [--url ws://127.0.0.1:8765/ws] [--token TOKEN] [--count N]

用途：
- 联调 serve 推送通道（配合 serve --replay 冒烟）
- 真实引擎测试时作为 AUTOlive 消费端替身
- 每条消息独立一行 JSON（与契约线格式一致），GAP/NEEDS_LOGIN 等系统消息高亮提示
"""

import argparse
import asyncio
import json
import sys
import time

import websockets


async def main() -> int:
    parser = argparse.ArgumentParser(description="DanmakuListener WS 消费助手")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--token", default=None, help="预共享 token（与服务端一致；未配置 token 的服务端可省略）")
    parser.add_argument("--count", type=int, default=0, help="收满 N 条后退出（0=持续运行，Ctrl+C 退出）")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    t0 = time.perf_counter()
    first = True
    count = 0

    try:
        async with websockets.connect(args.url, additional_headers=headers) as ws:
            print(f"[connected] {args.url}", file=sys.stderr)
            while True:
                raw = await ws.recv()
                if first:
                    print(f"[tthw] first message after {(time.perf_counter() - t0) * 1000:.0f} ms", file=sys.stderr)
                    first = False
                msg = json.loads(raw)
                if msg.get("type") == "GAP":
                    p = msg.get("payload", {})
                    print(f"⚠ GAP {p.get('window_start')}~{p.get('window_end')} reason={p.get('reason')} approx={p.get('approx')}", file=sys.stderr)
                elif msg.get("type") == "NEEDS_LOGIN":
                    p = msg.get("payload", {})
                    print(f"⚠ NEEDS_LOGIN reason={p['failure']['reason_code']} fix={p['failure']['fix_hint']}", file=sys.stderr)
                    if p.get("interactive_login") and p["interactive_login"].get("qr_image_b64"):
                        print("  (二维码 base64 已随消息到达，长度见 payload)", file=sys.stderr)
                elif msg.get("type") == "ROUTE_FAILED":
                    p = msg.get("payload", {})
                    print(f"⚠ ROUTE_FAILED {p['failure']['reason_code']} docs={p['failure']['docs_anchor']}", file=sys.stderr)
                count += 1
                print(json.dumps(msg, ensure_ascii=False), flush=True)
                if args.count and count >= args.count:
                    break
    except KeyboardInterrupt:
        print(f"\n[stopped] received {count} messages", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
