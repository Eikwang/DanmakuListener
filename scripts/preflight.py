#!/usr/bin/env python
"""部署前置检测脚本（阶段 0 DX 交付束 D：六平台统一框架）

用法：python scripts/preflight.py --platforms bilibili,douyin
退出码：0=全部通过；1=存在失败项（JSON 明细走 stdout）

每平台检查项：
- 协议平台（bilibili/douyu/huya/kuaishou）：网络可达、端口、凭据文件
- 代理平台（douyin）：证书、代理端口、杀软清单、直播伴侣版本
- 浏览器平台（wechat_channels）：浏览器内核、登录态文件
"""

import argparse
import json
import socket
import sys
from pathlib import Path

PROTOCOL_PLATFORMS = {"bilibili", "douyu", "huya", "kuaishou"}
ALL_PLATFORMS = PROTOCOL_PLATFORMS | {"douyin", "wechat_channels"}


def check_port_free(port: int) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return {"ok": True, "detail": f"端口 {port} 可用"}
        except OSError as e:
            return {"ok": False, "detail": f"端口 {port} 被占用: {e}", "fix_hint": "换端口或释放占用（netstat -ano | findstr " + str(port) + "）", "docs_anchor": "docs/ops/compliance-review.md"}


def check_host_reachable(host: str, port: int = 443) -> dict:
    try:
        with socket.create_connection((host, port), timeout=5):
            return {"ok": True, "detail": f"{host}:{port} 可达"}
    except OSError as e:
        return {"ok": False, "detail": f"{host} 不可达: {e}", "fix_hint": "检查网络/防火墙/代理设置", "docs_anchor": "docs/ops/compliance-review.md"}


def check_path_exists(path: str, what: str) -> dict:
    ok = Path(path).exists()
    return {"ok": ok, "detail": f"{what}: {path} {'存在' if ok else '不存在'}", "fix_hint": None if ok else f"确认 {what} 路径配置或完成登录", "docs_anchor": "docs/contract/migration.md"}


def platform_checks(platform: str, cookie_dir: str, proxy_port: int) -> list[dict]:
    checks = []
    if platform in PROTOCOL_PLATFORMS:
        checks.append(check_port_free(proxy_port))
        hosts = {
            "bilibili": "api.live.bilibili.com",
            "douyu": "open-dyserv.douyucdn.cn",
            "huya": "ws.huya.com",
            "kuaishou": "www.kuaishou.com",
        }
        checks.append(check_host_reachable(hosts[platform]))
        checks.append(check_path_exists(cookie_dir, "凭据目录"))
    elif platform == "douyin":
        checks.append(check_port_free(proxy_port))
        checks.append({
            "ok": False,
            "detail": "TLS 证书信任与直播伴侣版本需人工确认（杀软清单见合规评审）",
            "fix_hint": "完成根 CA 安装与直播伴侣版本核对；hook 路线需单独知情确认",
            "docs_anchor": "docs/ops/compliance-review.md",
        })
    elif platform == "wechat_channels":
        checks.append(check_path_exists(cookie_dir, "storageState 目录"))
        checks.append({
            "ok": None,
            "detail": "同账号多开风控需部署前实测（人工）",
            "fix_hint": "先小规模实测互踢行为；触发则降级为每房间独立微信账号",
            "docs_anchor": "docs/plans/six-platform-danmaku-rebuild-plan.md",
        })
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="部署前置检测（六平台统一框架）")
    parser.add_argument("--platforms", default=",".join(sorted(ALL_PLATFORMS)), help="逗号分隔平台列表")
    parser.add_argument("--cookie-dir", default="./cookie")
    parser.add_argument("--proxy-port", type=int, default=8827)
    args = parser.parse_args()

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    unknown = [p for p in platforms if p not in ALL_PLATFORMS]
    report: dict = {"platforms": {}, "unknown": unknown}
    all_ok = True
    for platform in platforms:
        if platform not in ALL_PLATFORMS:
            continue
        results = platform_checks(platform, args.cookie_dir, args.proxy_port)
        report["platforms"][platform] = results
        if any(r["ok"] is False for r in results):
            all_ok = False

    report["all_ok"] = all_ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
