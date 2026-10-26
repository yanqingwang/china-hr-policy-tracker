#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新变化摘要 JSON（每日脚本用）：读最新 items/变更明细 → changes_summary.json"""
import json
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys_path = str(REPO)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    # 政策条目：items.json 最新窗口（items 本身就是最近300条，本轮与上轮差异由 weekly 管线算；
    # 每日视角：统计 items 中最近24h发布的条目）
    items = load_json(REPO / "data" / "items.json", [])
    import datetime as dtt
    now = dtt.datetime.now(dtt.timezone.utc)
    day_ago = now - dtt.timedelta(hours=24)
    new_recs = []
    for r in items:
        pub = str(r.get("publish_date") or "")
        try:
            pdt = dtt.datetime.fromisoformat(pub).replace(tzinfo=dtt.timezone.utc)
        except Exception:
            continue
        if pdt >= day_ago:
            new_recs.append(r)
    cities = sorted({str(r.get("region_city") or "全国") for r in new_recs})
    types = {}
    for r in new_recs:
        t = str(r.get("policy_type") or "其他")
        types[t] = types.get(t, 0) + 1
    detail = load_json(REPO / "data" / "insurance_changes.json", {})
    summary = {
        "generated_at": now.isoformat(timespec="seconds"),
        "policy": {
            "new_count": len(new_recs),
            "new_cities": len(cities),
            "cities": cities[:15],
            "top_types": dict(sorted(types.items(), key=lambda x: -x[1])[:6]),
        },
        "insurance": {
            "changed": bool(detail),
            "cities": len(detail),
            "fields": sum(len(v) for v in detail.values() if isinstance(v, list)),
            "detail": detail,
        },
    }
    (REPO / "data" / "changes_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"变化摘要已刷新：新增政策 {len(new_recs)} 条/{len(cities)} 城；"
          f"五险一金变化 {len(detail)} 城")


if __name__ == "__main__":
    main()
