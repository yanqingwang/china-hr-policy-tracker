"""周报渲染：分类列举 + 社保公积金结构化数据表 + README 注入。"""
import datetime as dt

CAT_ORDER = [
    "社保公积金", "个税", "工资与劳动合同", "工作许可与人才引进",
    "补贴与保险待遇", "HR 服务情报", "其他",
]

CAT_BILINGUAL = {}

FUND_TABLE_HEADERS = {
    "zh_kwargs": ("| 城市 | 区域 | 保险类型 | 生效时间 | 发布时间 | 发布单位 "
                  "| 原基数 | 原比例 | 原下限 | 原上限 "
                  "| 新基数 | 新比例 | 新下限 | 新上限 | 原文 |"),
    "sep": "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
}

FIELD_ORDER = ["base_old", "ratio_old", "floor_old", "cap_old",
               "base_new", "ratio_new", "floor_new", "cap_new"]


def _d(x) -> str:
    return x or "—"


def _quotes_block(recs: list[dict], cat: str) -> list[str]:
    """关键原文摘录：每条政策 ≤3 句，逐句挂原文链接（条文引用保守截取）。"""
    out: list[str] = []
    for r in [x for x in recs if x["category"] == cat]:
        qs = r.get("quotes") or []
        if not qs:
            continue
        meta = f"{_d(r['region'])} · {_d(r['publish_date'])}"
        out.append(f"**{_d(r['policy_type']) if r['policy_type'] != '—' else CAT_BILINGUAL.get(cat, cat)}｜{meta}** — [{r['title'][:40]}]({r['url']})")
        for q in qs[:3]:
            out.append(f"> 「{q}」")
        out.append("")
    return out


def fund_table(recs: list[dict]) -> str:
    """社保公积金条目 → 规定列的数据表（城市/区域/保险类型 + 原/新基数比例上下限）。"""
    rows = [FUND_TABLE_HEADERS["zh_kwargs"], FUND_TABLE_HEADERS["sep"]]
    shown = []
    for r in recs:
        if r["category"] != "社保公积金":
            continue
        shown.append(r)
    shown.sort(key=lambda r: (r.get("effective_date") or "9999", -(r.get("publisher_rank") or 0)))
    if not shown:
        rows.append("| —（本期无本类条目）" + " |" * 14)
        return "\n".join(rows)
    for r in shown:
        ex = r.get("extracted") or {}
        vals = []
        for f in FIELD_ORDER:
            if f == "ratio_new" and ex.get("ratio_range"):
                vals.append(str(ex["ratio_range"]))   # 弹性缴存区间（如 5%–12%（可自行选择））
                continue
            v = ex.get(f)
            if v is None:
                vals.append("—")
            elif f.startswith("ratio") and isinstance(v, (int, float)):
                vals.append(f"{v:g}%")
            else:
                vals.append(f"{v:,}")
        link = f"[原文]({r['url']})"
        auto = "🤖 自动提取，读原文复核" if ex else "—（数字化待补）"
        rows.append(
            f"| {_d(r['region_city'])} | {_d(r['district']) if r.get('district') else '—（市级）'} "
            f"| {_d(r['policy_type'])} | {_d(r['effective_date'])} | {_d(r['publish_date'])} "
            f"| {_d(r['publisher'])[:20]} "
            f"| {' | '.join(vals)} | {link} <br>_{auto}_ |"
        )
    return "\n".join(rows)


def fund_history_section(recs: list[dict]) -> list[str]:
    """同 (区域, 保险类型) 折叠下来的历史版本（沿革），挂在数据表之后。"""
    out: list[str] = []
    for r in [x for x in recs if x["category"] == "社保公积金"]:
        hist = r.get("history") or []
        if not hist:
            continue
        hdr = f"{_d(r['region'])} · {_d(r['policy_type'])}（历史版本 {len(hist)} 条）"
        out.append(f"**{hdr}**")
        for h in hist:
            out.append(
                f"- {_d(h.get('publish_date'))} · [{h['title'][:46]}]({h['url']})"
                + (f" · 生效 {h.get('effective_date')}" if h.get("effective_date") else "")
            )
        out.append("")
    return out


def _bullets(recs: list[dict], cat: str, limit: int = 8) -> list[str]:
    rows = []
    for r in [x for x in recs if x["category"] == cat]:
        effective = f"，生效 {r['effective_date']}" if r.get("effective_date") else ""
        meta = f"{_d(r['publish_date'])} · {_d(r['publisher'])[:18]} · {_d(r['region'])}"
        rows.append(f"- 【{_d(r['publish_date'])}】[{r['title']}]({r['url']}) — {meta}{effective}")
        # 原文引用行（≤2 句）
        for q in (r.get("quotes") or [])[:2]:
            rows.append(f"  > 「{q}」")
    return rows[:limit + 16]


def coverage(recs: list[dict], all_cities: list[str]) -> tuple[int, list[str]]:
    """70 城覆盖统计：本周发现式采集实际命中的城市数 + 未覆盖清单。"""
    covered = set()
    for r in recs:
        if r.get("source_id") not in ("search-70cities", "city-portal"):
            continue
        region = (r.get("region") or "").replace("（省域）", "").replace("(省域)", "")
        covered.add(region)
    missing = [c for c in all_cities if c not in covered]
    return len(covered), missing


def report(recs: list[dict], path: str, week: str) -> str:
    today = dt.date.today().isoformat()
    fund_rec = fund_table(recs)
    # 70 城覆盖统计
    import yaml
    from pathlib import Path as _P
    cities = []
    try:
        ccfg = yaml.safe_load((_P(path).parent.parent / "data" / "cities.yml").read_text(encoding="utf-8"))
        cities = ccfg.get("cities") or []
    except Exception:
        cities = []
    n_cover, missing = coverage(recs, cities)
    cov_lines = [
        "## 📡 覆盖统计（70 大中城市）",
        "",
        f"本周发现式采集命中 **{n_cover}/70** 城（含省域命中的归入对应市）。",
    ]
    if missing:
        cov_lines += ["未覆盖城市：" + "、".join(missing), ""]
    else:
        cov_lines += ["✅ 全部 70 城均有官方页面命中。", ""]
    lines = [
        "# 中国人力资源政策周报",
        "",
        f"**周期：{week} · 生成于 {today}（UTC）**",
        "",
        "---",
        "",
        "## 📊 社保公积金变化（数据表格）",
        "",
        "> 提取方式：机器人自动从标题/正文提取关键数字（🤖），**必读原文确认**；解读类内容以原发布单位为准。",
        "",
        fund_rec,
        "",
    ]
    if cities:
        lines += cov_lines + ["---"]
    qs = _quotes_block(recs, "社保公积金")
    if qs:
        lines += ["### 关键原文摘录（社保公积金）", ""] + qs + ["---"]
    else:
        lines += ["---"]
    hist_lines = fund_history_section(recs)
    if hist_lines:
        lines += ["### 历史沿革（同区域同险种历史版本）", ""] + hist_lines + ["---"]
    for cat in CAT_ORDER:
        if cat == "社保公积金":
            continue
        bl = _bullets(recs, cat)
        if not bl:
            continue
        lines += [f"## {cat}", ""] + bl + ["", "---"]
    lines += ["", "**数据方法**：信息提取自人社部/gov.cn 政策文件库/税局/公积金中心/HR 服务商公告，"
                  "合并时优先原发布单位与权威机构（rank 高者优先），解读类仅作条目附注。每周一自动更新。", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def inject_readme(readme_path: str, recs: list[dict], generated_on: str) -> None:
    with open(readme_path, encoding="utf-8") as f:
        md = f.read()
    block = (
        "<!-- AUTO-TABLE-START -->\n"
        f"_{generated_on} 自动重建 · 数据管道见 [`src/`](src/)，源清单见 [`data/sources.yml`](data/sources.yml)_\n\n"
        + table(recs)
        + "\n<!-- AUTO-TABLE-END -->"
    )
    start = md.index("<!-- AUTO-TABLE-START -->")
    end = md.index("<!-- AUTO-TABLE-END -->") + len("<!-- AUTO-TABLE-END -->")
    md = md[:start] + block + md[end:]
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(md)


def table(recs: list[dict]) -> str:
    rows = [
        "| 城市/地区 | 发布时间 | 生效时间 | 政策类型 | 分类 | 发布单位 | 标题 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(recs, key=lambda x: (x.get("publish_date") or "9999")[:7], reverse=True)[:40]:
        rows.append(
            f"| {_d(r['region'])} | {_d(r['publish_date'])} | {_d(r['effective_date'])} "
            f"| {_d(r['policy_type'])} | {r['category']} | {_d(r['publisher'])[:16]} "
            f"| [{r['title'][:52]}]({r['url']}) |"
        )
    return "\n".join(rows)
