# -*- coding: utf-8 -*-
"""美团直播弹幕冒烟工具

用法：
    python tools/meituan_smoke.py <live_id 或 dpurl.cn 短链或美团链接> [--duration 60]

验证 mapi 轮询通道连通性；首个快照全量 JSON dump 到 meituan_snapshot.json
（供进入/点赞等消息形态校准）。
"""

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from danmaku_listener.engines.protocol.meituan import (
    MeituanPollEngine,
    extract_live_id,
)


async def main(spec: str, duration: float, dump_all: bool) -> int:
    eng = MeituanPollEngine()
    dump_fh = None
    n_raw = 0
    if dump_all:
        dump_fh = open("meituan_dump.jsonl", "a", encoding="utf-8")

        def raw_hook(jsdata):
            nonlocal n_raw
            n_raw += 1
            dump_fh.write(json.dumps({"ts": time.time(), "kind": "raw",
                                      "data": jsdata},
                                     ensure_ascii=False, default=str) + "\n")
            dump_fh.flush()

        eng._raw_hook = raw_hook
    live_id = await eng._resolve_live_id(extract_live_id(spec))
    print(f"[spec] live_id = {live_id}")

    def on_msg(m):
        t = m.get("type")
        p = m.get("payload") or {}
        if t == "DANMU":
            print(f"[DANMU] {p.get('user_name')}({p.get('user_id')}): {p.get('content')}")
        else:
            print(f"[{t}] {json.dumps(p, ensure_ascii=False)[:150]}")

    eng.on_message(on_msg)

    # 拉一次快照全量 dump（消息形态校准用）
    js = await eng._poll_once(live_id)
    with open("meituan_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)
    msgs = ((js.get("messageVO") or {}).get("msgs")) or []
    print(f"[snapshot] code={js.get('code')} msgs={len(msgs)} "
          f"liveInfoVo.keys={sorted((js.get('liveInfoVo') or {}).keys())[:8]}")
    print("[snapshot] 已 dump 全量快照 → meituan_snapshot.json")

    await eng.start(live_id)
    print(f"[listen] 监听中 {duration:.0f} 秒——请去直播间发几条弹幕！"
          + ("（原始快照 → meituan_dump.jsonl）" if dump_all else ""))
    await asyncio.sleep(duration)
    await eng.stop(live_id)
    if dump_fh:
        dump_fh.close()
        print(f"[done] 原始快照共 {n_raw} 条 → meituan_dump.jsonl")
    else:
        print("[done]")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="live_id / dpurl.cn 短链 / 美团直播间链接")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--dump-all", action="store_true",
                    help="轮询原始快照写 meituan_dump.jsonl（形态校准）")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.spec, a.duration, a.dump_all)))
