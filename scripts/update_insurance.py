#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
城市五险一金数据「变更检测式」增量更新（严格版）。

核心规则（按需求明确固化）：
  1. **仅当 基数上限 / 基数下限 / 个人比例 / 公司比例 发生真实变化时**，才更新该字段。
  2. 无变化时：**原始数据完全不动**（不刷新 _date，不改 _src_type，不写文件）。
  3. 有变化时：仅改动变化的字段，并写入 _date=抓取日、_src_type=script。
  4. 三重防误覆盖保护：
     - 记录必须是 2026 年发布（publish_date 以 2026 开头），防旧年数据降级；
     - 数值合理性：新基数须在基准值 ±50% 内（防月缴存额/年缴额误提取）；
     - 险种映射严格：公积金记录只更新公积金，社保记录只更新五险基数。

退出码：
  0 = 正常（无论是否变化）
  变化标记：/tmp/hr-insurance-changed（仅确有变化时创建）
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

def _find_repo() -> Path:
    """定位仓库根：环境变量 > 脚本所在仓库 > 常见部署路径。"""
    import os
    here = Path(__file__).resolve().parent
    for cand in (os.environ.get("HR_REPO_DIR"),
                 str(here.parent),        # <repo>/scripts/ -> <repo>
                 str(here),               # 脚本被复制到仓库根时
                 "/www/china-hr-si-phf-policy/repo"):
        if cand and Path(cand).joinpath("data", "city_insurance_2026.json").exists():
            return Path(cand)
    for cand in (os.environ.get("HR_REPO_DIR"),
                 str(here.parent),
                 str(here),
                 "/www/china-hr-si-phf-policy/repo"):
        if not cand:
            continue
        p = Path(cand)
        if (p / "data" / "city_insurance_2026.json").exists():
            return p
    return Path(__file__).resolve().parent.parent


REPO = _find_repo()
sys.path.insert(0, str(REPO))
try:
    from src.insurance_rules import should_skip_insurance
except Exception:                                    # 兼容缺模块场景
    def should_skip_insurance(x):
        return not isinstance(x, dict)

BASE = REPO / "data" / "city_insurance_2026.json"
ITEMS = REPO / "data" / "items.json"
TODAY = dt.date.today().isoformat()
PLAUSIBLE = 0.5          # 基数合理性 ±50%
CHANGED_FLAG = Path("/tmp/hr-insurance-changed")

# 参与变更检测的 4 个字段（严格按要求）
WATCH_FIELDS = ("基数上限", "基数下限", "个人比例%", "公司比例%")
# 只有基数需要 ±50% 合理性校验；比例不做幅度过滤（比例可能合法跨档）
BASE_FIELDS = ("基数上限", "基数下限")


def target_insurances(pt: str) -> list:
    """险种映射：公积金记录只更新公积金，其余更新五险基数。"""
    pt = pt or ""
    if "公积金" in pt:
        return ["公积金", "补充公积金"]
    return ["养老", "医疗", "失业", "工伤", "生育"]


def same(a, b) -> bool:
    """等价比较：8 与 8.0、'5~12' 与 '5-12' 视为不同（字符串严格），数值按精度比较。"""
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def plausible(cur, new) -> bool:
    """基数合理性：新值须在基准 ±50% 内，防误提取（月缴存额/年缴额等）。"""
    if cur is None:
        return True
    try:
        c, n = float(cur), float(new)
    except (TypeError, ValueError):
        return False
    if c == 0:
        return n < 100000
    return abs(n - c) / c <= PLAUSIBLE


def merge_fields(city: str, pt: str, ex: dict, base: dict) -> tuple:
    """把一条抓取记录合并进基准。返回 (是否变化, 变更明细)。"""
    cur_city = base.get(city)
    if not isinstance(cur_city, dict):
        return False, []
    details = []
    for ins in target_insurances(pt):
        cur = cur_city.get(ins)
        if not isinstance(cur, dict):
            continue                      # 该市无此险种 → 不新增（防臆造）
        if should_skip_insurance(cur):
            continue                      # 双0/并入医保 → 跳过
        for fld in WATCH_FIELDS:
            v = ex.get(fld)
            if v is None or v == "":
                continue
            if fld in BASE_FIELDS and not plausible(cur.get(fld), v):
                details.append(f"{ins}.{fld} 被合理性过滤({cur.get(fld)}→{v})")
                continue
            if same(cur.get(fld), v):
                continue                  # ★ 无变化 → 绝不改动原始数据
            details.append(f"{ins}.{fld}: {cur.get(fld)} → {v}")
            cur[fld] = v
    if details:
        cur_city["_date"] = TODAY
        cur_city["_src_type"] = "script"
        return True, details
    return False, []


def main() -> None:
    if not BASE.exists():
        print(f"❌ 基准文件缺失: {BASE}", file=sys.stderr)
        sys.exit(1)
    base = json.loads(BASE.read_text(encoding="utf-8"))

    if not ITEMS.exists():
        print("ℹ️ items.json 不存在，本日无抓取结果，原始数据保持不变")
        CHANGED_FLAG.unlink(missing_ok=True)
        return

    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    changed_cities, scanned, skipped = {}, 0, 0

    for r in items:
        if r.get("category") != "社保公积金":
            continue
        city = r.get("region_city")
        ex = r.get("extracted") or {}
        pub = str(r.get("publish_date") or "").strip()
        if city not in base or not ex:
            continue
        if not pub.startswith("2026"):     # 严格：仅认 2026 年起发布
            skipped += 1
            continue
        # 提取标题中的 4 位年份（如 2025 / 2026），旧年度记录一律拒绝
        ym = re.search(r"(20\d{2})\s*(?:年|年度)?", str(r.get("title") or ""))
        if ym and int(ym.group(1)) < 2026:  # 标题指向旧年度 → 拒绝
            skipped += 1
            continue
        if ym and int(ym.group(1)) < 2026:
            skipped += 1
            continue
        scanned += 1
        did, det = merge_fields(city, str(r.get("policy_type") or ""), ex, base)
        if did:
            changed_cities[city] = det

    print(f"扫描 2026 年发布社保条目 {scanned} 条（跳过旧年度 {skipped} 条）")
    if changed_cities:
        BASE.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
        CHANGED_FLAG.touch()
        print(f"✅ 检出真实变化 {len(changed_cities)} 城，已更新并写变更标记：")
        for c, det in changed_cities.items():
            print(f"   {c}: " + "; ".join(det[:4]))
    else:
        CHANGED_FLAG.unlink(missing_ok=True)
        print("ℹ️ 基数/比例/上下限均无变化 → 原始数据保持不变（不刷新日期、不改来源）")


if __name__ == "__main__":
    main()
