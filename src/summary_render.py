#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变化摘要渲染：邮件开头 + README 汇总段（只保留最新一次，历史不堆积）。"""
import json
from pathlib import Path


def _fmt_policy(p: dict) -> list:
    lines = []
    n, c = p.get("new_count", 0), p.get("new_cities", 0)
    if n:
        lines.append(f"**📌 政策条目：本次新增 {n} 条，涉及 {c} 个城市/地区**")
        types = p.get("top_types") or {}
        if types:
            ts = "、".join(f"{k} {v} 条" for k, v in list(types.items())[:4])
            lines.append(f"- 主要类型：{ts}")
        cities = p.get("cities") or []
        if cities:
            shown = "、".join(cities[:8]) + ("…" if len(cities) > 8 else "")
            lines.append(f"- 涉及城市：{shown}")
    else:
        lines.append("**📌 政策条目：本次无新增政策**")
    return lines


def _fmt_insurance(i: dict) -> list:
    lines = []
    if i.get("changed") and i.get("cities"):
        c, f = i["cities"], i["fields"]
        lines.append(f"**💰 五险一金数值：{c} 个城市 / {f} 个字段发生变化**")
        detail = i.get("detail") or {}
        for city, items in list(detail.items())[:5]:
            if isinstance(items, list):
                lines.append(f"- {city}：" + "；".join(str(x)[:60] for x in items[:3]))
        if len(detail) > 5:
            lines.append(f"- ……另有 {len(detail)-5} 个城市，详见附件总表")
    else:
        lines.append("**💰 五险一金数值：各城市标准无变化**")
    return lines


def render_text(summary: dict) -> str:
    """生成邮件开头的变化说明。"""
    if not summary:
        return ""
    lines = ["## 🔔 本次变化一览", ""]
    lines += _fmt_policy(summary.get("policy") or {})
    lines += _fmt_insurance(summary.get("insurance") or {})
    gen = summary.get("generated_at", "")
    if gen:
        lines.append("")
        lines.append(f"_对比基准：上一轮采集（摘要生成于 {gen[:10]}）_")
    return "\n".join(lines) + "\n"


def render_readme_section(summary: dict) -> str:
    """README 汇总段（覆盖式：只保留最新一次）。"""
    lines = ["<!-- CHANGES-SUMMARY-START -->", "## 🔔 最近一次变化", ""]
    lines += _fmt_policy(summary.get("policy") or {})
    lines += _fmt_insurance(summary.get("insurance") or {})
    gen = summary.get("generated_at", "")
    if gen:
        lines.append("")
        lines.append(f"_更新时间：{gen[:16].replace('T', ' ')} UTC · 历史变化不保留_")
    lines.append("<!-- CHANGES-SUMMARY-END -->")
    return "\n".join(lines)


def inject_readme(readme_path: str, summary: dict) -> None:
    """覆盖式注入 README：有锚点则替换，无锚点则在标题后插入。只保留最新一次。"""
    p = Path(readme_path)
    md = p.read_text(encoding="utf-8")
    block = render_readme_section(summary)
    start_anchor = "<!-- CHANGES-SUMMARY-START -->"
    end_anchor = "<!-- CHANGES-SUMMARY-END -->"
    if start_anchor in md and end_anchor in md:
        s0 = md.index(start_anchor)
        e0 = md.index(end_anchor) + len(end_anchor)
        md = md[:s0] + block + md[e0:]
    else:
        # 插在第一个二级标题之前（紧跟主标题与简介）
        idx = md.find("\n## ")
        if idx == -1:
            md = md + "\n\n" + block
        else:
            md = md[:idx] + "\n\n" + block + md[idx:]
    p.write_text(md, encoding="utf-8")
