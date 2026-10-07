"""M0 发送探针公共脚手架（2026-10-06 /autoplan 批准计划 T2）

探针纪律（计划义务）：
- 探针账号环境与实发一致（R17）——使用 cookie/ 既有 profile
- 连续 N 次发送 + 风控信号观察（R17）——每次发送间隔 >= MIN_INTERVAL 秒 + 抖动
- 发送成功判定（F5/R36）：DOM=消息回显于聊天流；API=响应码+体字段；
  不可判定=UNKNOWN（不计熔断语义，仅探针记录）
- spike 失败=BLOCKED + 公开降级路线（R19/3.1）
- 内容标记：所有探针弹幕带 [M0] 前缀 + 时间戳，便于回环识别（F8）

卡片输出：tools/send_probes/cards/<platform>-<yyyymmdd-hhmmss>.json
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
CARDS_DIR = Path(__file__).resolve().parent / "cards"
MIN_INTERVAL = 10.0          # 两次发送最小间隔（秒）
JITTER = 4.0                 # 随机抖动上限（秒）
MARKER_PREFIX = "[M0]"

# 平台 → 受控页面探针配置（profile 目录约定与 ControlledPageEngine 一致）
DOM_PLATFORMS = {
    "taobao": {"profile": "taobao_profile", "room_url_hint": "淘宝直播间 URL（淘宝 App 分享）"},
    "1688": {"profile": "1688_profile", "room_url_hint": "1688 直播间 URL"},
    "xiaohongshu": {"profile": "xhs_profile", "room_url_hint": "小红书直播间 URL"},
    "jd": {"profile": "jd_profile", "room_url_hint": "zhibo.jd.com/liveroom?liveId=..."},
    "wechat_channels": {"profile": None, "room_url_hint": "视频号直播管理后台 URL（助手发言入口）"},
    "douyin": {"profile": "douyin_profile", "room_url_hint": "live.douyin.com/<room_id>（profile 登录态，bd_ticket_guard 指纹绑定）"},
    "kuaishou": {"profile": None, "room_url_hint": "live.kuaishou.com/u/<主播>（登录态 storage_state）"},
    "douyu": {"profile": None, "room_url_hint": "douyu.com/<room_id>（登录态 cookie 文件）"},
    "huya": {"profile": "huya_login_profile", "room_url_hint": "huya.com/<room_id>"},
}

# 风控信号观察选择器（出现即记录；平台专用项在探针运行时补充）
RISK_SELECTORS = [
    "text=验证码", "text=滑动验证", "text=安全验证",
    "text=禁言", "text=被禁言", "text=操作过于频繁", "text=稍后再试",
]


def marker_content(seq: int) -> str:
    """探针弹幕内容：可识别 + 可去重 + 短（不过滤层长度上限）"""
    return f"{MARKER_PREFIX} 发送探针 {seq}/{time.strftime('%H%M%S')}"


def save_card(platform: str, card: dict[str, Any]) -> Path:
    """写探针卡片 JSON；返回路径"""
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = CARDS_DIR / f"{platform}-{ts}.json"
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_card(platform: str, card: dict[str, Any]) -> None:
    """打印人类可读卡片（回填 docs/testing 矩阵用）"""
    print(f"\n=== 探针卡片: {platform} ===")
    for key, value in card.items():
        if key == "sends":
            print(f"  sends: {len(value)} 次")
            for i, s in enumerate(value, 1):
                print(f"    #{i}: {s}")
        else:
            print(f"  {key}: {value}")
    print(f"  回填动作: 矩阵可行性终判 + docs/testing/m0-send-probe-cards.md")


def verdict_summary(sends: list[dict[str, Any]]) -> str:
    """按 F5 语义汇总：success/fail/unknown 计数"""
    counts: dict[str, int] = {}
    for s in sends:
        counts[s.get("verdict", "UNKNOWN")] = counts.get(s.get("verdict", "UNKNOWN"), 0) + 1
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "无发送"


async def paced_sends(n: int) -> list[int]:
    """生成 n 次发送的间隔序列（最小间隔+抖动）"""
    return [MIN_INTERVAL + random.uniform(0, JITTER) for _ in range(n)]


async def observe_risk_signals(page) -> list[str]:
    """页面风控信号观察（R17）——命中即返回描述列表"""
    hits: list[str] = []
    for sel in RISK_SELECTORS:
        try:
            locator = page.locator(sel).first
            if await locator.count() > 0 and await locator.is_visible():
                hits.append(sel)
        except Exception:  # noqa: BLE001 探针观察失败不中断
            continue
    return hits


def common_precheck(platform: str) -> dict[str, Any]:
    """探针前置检查：平台配置存在性"""
    if platform not in DOM_PLATFORMS:
        return {"ok": False, "reason": f"未知平台 {platform}；可选: {sorted(DOM_PLATFORMS)}"}
    return {"ok": True, "config": DOM_PLATFORMS[platform]}


def launch_args() -> list[str]:
    """与 controlled_base.COMMON_LAUNCH_ARGS 对齐的反检测参数"""
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-setuid-sandbox",
        "--hide-crash-restore-bubble",
    ]


COMMON_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/131.0.0.0 Safari/537.36")
