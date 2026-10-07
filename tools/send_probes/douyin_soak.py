"""抖音常驻会话浸泡验收（DX-D2/T3 完成判定——计划义务 CEO-F3 验收必需）

形态：常驻会话（headless_new）保持进程存活，每 10min 发一条 [M0] 探针弹幕，
观察风控/掉登录/面板停止渲染任一信号；visibilityState 断言随每次发送记录
（CEO-F3 运行时观测）。验收=2h（12 发）无 FAIL 恶化趋势。

输出：persistence_data/douyin-soak-<ts>.jsonl（逐发记录）+ cards 汇总卡片。
运行：python -X utf8 tools/send_probes/douyin_soak.py --duration-hours 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

sys_path = Path(__file__).resolve().parent.parent.parent
sys_path_str = str(sys_path)
if sys_path_str not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path_str)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-hours", type=float, default=2.0)
    ap.add_argument("--interval-min", type=float, default=10.0)
    ap.add_argument("--room-id", default="964657735367")
    args = ap.parse_args()

    from danmaku_listener.config.settings import get_settings
    from danmaku_listener.senders.douyin import DouyinProfileSender

    settings = get_settings()
    sender = DouyinProfileSender(settings=settings)
    out = Path("persistence_data") / f"douyin-soak-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.parent.mkdir(exist_ok=True)
    deadline = time.monotonic() + args.duration_hours * 3600
    seq = 0
    counts: dict[str, int] = {}
    print(f"浸泡开始: {args.duration_hours}h / 每 {args.interval_min}min / room={args.room_id}", flush=True)
    while time.monotonic() < deadline:
        seq += 1
        content = f"[M0] soak {seq}/{time.strftime('%H%M%S')}"
        rec: dict = {"seq": seq, "content": content, "ts": time.strftime("%H:%M:%S")}
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(sender.send(args.room_id, content), timeout=120)
            rec["status"] = result.status.value
            rec["reason"] = result.reason_code
            rec["took_s"] = round(time.monotonic() - t0, 1)
        except Exception as e:  # noqa: BLE001
            rec["status"] = "UNKNOWN"
            rec["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{seq}] {rec['ts']} status={rec['status']} took={rec.get('took_s')}s "
              f"累计={counts}", flush=True)
        if time.monotonic() + args.interval_min * 60 >= deadline:
            break
        await asyncio.sleep(args.interval_min * 60)

    summary = {
        "platform": "douyin", "mode": "soak-2h", "seq_total": seq,
        "counts": counts, "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": ("PASS——浸泡验收通过（无 FAIL 恶化/掉登录/风控）"
                    if counts.get("failed", 0) == 0 and counts.get("sent", 0) >= seq * 0.8
                    else "REVIEW——浸泡出现异常，见 jsonl 明细"),
    }
    card_path = Path("tools/send_probes/cards") / f"douyin-soak-{time.strftime('%Y%m%d-%H%M%S')}.json"
    card_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"浸泡结束: {summary['verdict']} counts={counts}", flush=True)
    print(f"汇总卡片: {card_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
