#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变化摘要生成器：对比本轮与上轮数据，产出供邮件/README 使用的汇总。

输出 data/changes_summary.json：
{
  "generated_at": "2026-10-26T03:43:00",
  "policy": {            # 政策条目（周报管线）
      "new_count": 12, "new_cities": 8,
      "cities": ["北京","上海",...],
      "top_types": {"公积金": 5, "社保-养老": 3}
  },
  "insurance": {         # 五险一金数值（每日增量脚本）
      "changed": true, "cities": 3, "fields": 5,
      "detail": {"保定": ["公积金.基数上限: 24000 → 24345"]}
  }
}
"""
import json
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "data" / "changes_state.json"      # 上轮摘要（用于对比）
OUT = REPO / "data" / "changes_summary.json"      # 本轮摘要


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def summarize_policy(items_path: Path, prev_uids: set):
    """政策条目：本轮新增 = uid 不在上轮集合中。"""
    items = load_json(items_path, [])
    cur_uids, new_recs = set(), []
    for r in items:
        uid = str(r.get("uid") or r.get("url") or r.get("title"))
        cur_uids.add(uid)
        if prev_uids and uid not in prev_uids:
            new_recs.append(r)
    cities = sorted({str(r.get("region_city") or "全国") for r in new_recs})
    types = {}
    for r in new_recs:
        t = str(r.get("policy_type") or "其他")
        types[t] = types.get(t, 0) + 1
    top_types = dict(sorted(types.items(), key=lambda x: -x[1])[:6])
    return {
        "new_count": len(new_recs),
        "new_cities": len(cities),
        "cities": cities[:15],
        "top_types": top_types,
        "total_in_window": len(items),
        "_uids": sorted(cur_uids)[-2000:],   # 供下轮对比
    }


def summarize_insurance(changed_flag: Path, repo: Path):
    """五险一金数值变化：读 update_insurance.py 落盘的变更明细。"""
    detail_path = repo / "data" / "insurance_changes.json"
    detail = load_json(detail_path, {})
    return {
        "changed": changed_flag.exists() or bool(detail),
        "cities": len(detail),
        "fields": sum(len(v) for v in detail.values()),
        "detail": detail,
    }


def main():
    prev = load_json(STATE, {})
    prev_uids = set(prev.get("policy_uids") or [])

    items_path = REPO / "data" / "items.json"
    policy = summarize_policy(items_path, prev_uids)

    ins = summarize_insurance(Path("/tmp/hr-insurance-changed"), REPO)

    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "policy": {k: v for k, v in policy.items() if k != "_uids"},
        "insurance": ins,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    STATE.write_text(json.dumps({"policy_uids": policy["_uids"]}, ensure_ascii=False),
                     encoding="utf-8")

    # 控制台摘要
    p, i = summary["policy"], summary["insurance"]
    print(f"变化摘要：新增政策 {p['new_count']} 条 / {p['new_cities']} 城；"
          f"五险一金数值变化 {i['cities']} 城 {i['fields']} 字段")


if __name__ == "__main__":
    main()
