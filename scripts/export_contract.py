#!/usr/bin/env python
"""导出契约 JSON Schema（单源：pydantic 模型 → docs/contract/schema.json）

用法：python scripts/export_contract.py
CI 校验：python scripts/export_contract.py --check（diff 非空则退出 1）
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from danmaku_listener.contract.models import UnifiedMessage  # noqa: E402


def main() -> int:
    check = "--check" in sys.argv
    schema = UnifiedMessage.model_json_schema()
    schema["$id"] = "danmaku-listener/contract/v1"
    schema["title"] = "DanmakuListener Unified Message Contract v1"
    out = REPO / "docs" / "contract" / "schema.json"
    text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    if check:
        if not out.exists():
            print(f"FAIL: {out} missing; run scripts/export_contract.py to generate")
            return 1
        if out.read_text(encoding="utf-8") != text:
            print("FAIL: schema.json drifted from models.py — 契约变更必须经评审（additive-only）")
            return 1
        print("contract schema in sync")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
