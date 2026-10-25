#!/bin/bash
# 汇总各批次抓取结果到 combined_cities_2026.json（中间落盘，防 token 限速丢进度）
# 用法：bash merge_batches.sh
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
DIR=/www/china-hr-si-phf-policy/repo/data/insurance_batches
OUT=/www/china-hr-si-phf-policy/repo/data/city_insurance_2026_raw.json
PY=/www/china-hr-si-phf-policy/venv/bin/python

$PY - << PYEOF
import json, glob, os
merged = {}
meta = {"批次": [], "日期": "2026-10-23"}
for f in sorted(glob.glob(os.path.join("$DIR", "batch_*.json"))):
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception as e:
        print("跳过", f, e)
        continue
    model = d.get("模型", os.path.basename(f))
    batch = d.get("批次", "?")
    meta["批次"].append(f"{batch} ({model})")
    for city, v in d.items():
        if city in ("模型", "批次", "完成日期"):
            continue
        if city not in merged:
            merged[city] = v
        else:
            # 已有则仅补充缺失字段
            for k, val in v.items():
                merged[city].setdefault(k, val)
with open("$OUT", "w", encoding='utf-8') as f:
    json.dump({"meta": meta, "cities": merged}, f, ensure_ascii=False, indent=2)
print("已合并城市数:", len(merged))
print("城市:", "、".join(sorted(merged.keys())))
print("批次:", meta["批次"])
PYEOF
