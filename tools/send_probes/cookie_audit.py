"""R19 cookie 存档字段充分性审计（离线可跑，2026-10-06）

核对 cookie/ 目录各平台登录存档的 cookie 名集合，对照发送鉴权需求：
- bilibili: 发送 API 需要 SESSDATA + bili_jct（csrf）
- douyu/huya: 登录闭包存的「cookie 文件」（login_gate.py 诚实边界：存档未注入协议）
  ——发送若走网页侧需要 ltkid/stk/vk（WS）或网页 cookie（DOM 用浏览器登录，不走此文件）
- 抖音: douyin_cookies.json（WS 直连用）；DOM 发送用浏览器登录态
- 受控页面组: profile 目录（cookie 内嵌于 profile 数据库，此处仅报告存在性）

运行：python tools/send_probes/cookie_audit.py
输出：stdout 报告（供探针卡片 R19 行引用）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
COOKIE_DIR = ROOT / "cookie"

# 平台 → 存档文件 → 发送相关字段需求
BILI_NEEDS = ("SESSDATA", "bili_jct")
DOUYU_WEB_NEEDS = ("acf_uid", "acf_auth", "ltkid", "stk", "vk")  # 任一组存在即可初步判定


def audit_json_file(path: Path, needs: tuple[str, ...], label: str) -> dict:
    """审计 JSON 形态 cookie 存档（storage_state / {cookies:[...]} / 平面 dict）"""
    info: dict = {"file": str(path.relative_to(ROOT)), "exists": path.is_file()}
    if not path.is_file():
        info["verdict"] = "MISSING"
        return info
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        info["verdict"] = "UNREADABLE"
        info["error"] = f"{type(e).__name__}: {e}"
        return info
    # 归一化为 {name: value} 并做值掩码
    pairs: dict[str, str] = {}
    if isinstance(raw, dict) and "cookies" in raw:
        items = raw["cookies"]
    elif isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = [{"name": k, "value": v} for k, v in raw.items()]
    else:
        items = []
    for c in items:
        name = str(c.get("name", ""))
        value = str(c.get("value", ""))
        if name:
            pairs[name] = f"len={len(value)}"
    info["cookie_names_sample"] = sorted(pairs)[:20]
    info["cookie_count"] = len(pairs)
    hits = [n for n in needs if n in pairs and pairs[n] != "len=0"]
    info["needs_hit"] = hits
    if not needs:
        info["verdict"] = "OK(info)"  # 无硬需求清单——仅报告存在性（DOM 发送走浏览器会话）
    else:
        info["verdict"] = "OK" if hits else "NEEDS_MISSING"
    info["label"] = label
    return info


def main() -> None:
    print("== R19 cookie 存档字段充分性审计（离线）==\n")
    results: dict[str, dict] = {}

    # B站：发送 API 硬需求
    results["bilibili"] = audit_json_file(
        COOKIE_DIR / "bilibili_storage_state.json", BILI_NEEDS,
        "发送 API 需 SESSDATA+bili_jct（csrf）")
    # 斗鱼/虎牙：存档 vs 网页发送需求
    for name, fname in (("douyu", "douyu_login_cookies.json"), ("huya", "huya_login_cookies.json")):
        results[name] = audit_json_file(
            COOKIE_DIR / fname, DOUYU_WEB_NEEDS,
            "登录闭包存档（login_gate 诚实边界：未注入 TCP 协议）；网页发送需 acf_* 或 ltkid/stk/vk")
    # 抖音/快手：登录态文件（DOM 发送走浏览器登录态，此处报告存在性）
    results["douyin"] = audit_json_file(COOKIE_DIR / "douyin_cookies.json", (), "WS 直连登录态；DOM 发送用浏览器会话")
    results["kuaishou"] = audit_json_file(COOKIE_DIR / "kuaishou_storage_state.json", (), "storage_state；DOM 发送可注入")

    # profile 目录存在性（受控页面组：发送复用监听引擎 profile）
    for plat, prof in (("taobao", "taobao_profile"), ("1688", "1688_profile"),
                       ("xiaohongshu", "xhs_profile"), ("jd", "jd_profile"),
                       ("pdd", "pdd_profile"), ("huya", "huya_login_profile")):
        p = COOKIE_DIR / prof
        results[plat + "_profile"] = {
            "file": f"cookie/{prof}", "exists": p.is_dir(),
            "verdict": "OK(profile)" if p.is_dir() else "MISSING",
            "label": "受控页面 profile（发送经监听引擎实例，E5）",
        }

    for plat, info in results.items():
        verdict = info.get("verdict", "?")
        mark = "OK " if verdict.startswith("OK") else "!! "
        print(f"{mark}{plat:16s} {verdict:14s} {info.get('label', '')}")
        if "needs_hit" in info:
            print(f"     发送相关字段命中: {info['needs_hit'] or '无'}（cookie 总数 {info.get('cookie_count', 0)}）")
        if verdict == "NEEDS_MISSING":
            print(f"     !! 探针动作：登录窗口补齐后再探针（字段缺失见 cookie_names_sample）")
    print("\n结论口径：OK=可直接进入 DOM/API 探针；NEEDS_MISSING=先补登录；MISSING=无存档（DOM 登录态在浏览器会话内不受影响）")


if __name__ == "__main__":
    sys.exit(main())
