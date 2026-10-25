#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
社保公积金政策月度报告生成器（单一大表版）。
列：城市 | 生效日期 | 险种 | 基数上限 | 基数下限 | 个人% | 公司% | 校验方式(详细) | 更新频率
校验方式详细：AI核实=glm/kimi/deepseek三模型+是否一致+豆包终审；脚本更新=严格增量；待核=无官方值。
更新频率：年度=基数每年4/7月调整；季度/月度=阶段性政策。
"""
import json
import sys
import datetime as dt
from pathlib import Path

def _find_repo() -> Path:
    """定位仓库根：环境变量 > 脚本所在仓库 > 常见部署路径。"""
    import os
    here = Path(__file__).resolve().parent
    for cand in (os.environ.get("HR_REPO_DIR"),
                 str(here.parent),        # <repo>/scripts/ -> <repo>
                 str(here),               # 脚本被复制到仓库根时
                 "/www/china-si-phf-policy/repo"):
        if cand and Path(cand).joinpath("data", "city_insurance_2026.json").exists():
            return Path(cand)
    for cand in (os.environ.get("HR_REPO_DIR"),
                 str(here.parent),
                 str(here),
                 "/www/china-si-phf-policy/repo"):
        if not cand:
            continue
        p = Path(cand)
        if (p / "data" / "city_insurance_2026.json").exists():
            return p
    return Path(__file__).resolve().parent.parent


REPO = _find_repo()
import sys
sys.path.insert(0, str(REPO))
from src.insurance_rules import should_skip_insurance, effective_rows
BASE = REPO / "data" / "city_insurance_2026.json"
OUT = REPO / "reports"
TODAY = dt.date.today().isoformat()

INS_ORDER = ['养老', '医疗', '生育', '失业', '工伤', '公积金', '补充公积金']
# 更新频率：社保基数年度(4/7月调整)；公积金年度(7月)；失业阶段性年度；工伤行业浮动
INS_FREQ = {
    '养老': '年度(每年4/7月调整)', '医疗': '年度', '生育': '年度',
    '失业': '年度(阶段性费率延续)', '工伤': '不定期(行业浮动)',
    '公积金': '年度(每年7月调整)', '补充公积金': '年度',
}


def verify_detail(v: dict, has_val: bool) -> str:
    """详细校验方式。"""
    src = v.get('_src_type')
    d = v.get('_date', TODAY)
    if not has_val:
        return f"待核(暂未获取官方值,{d})"
    if src == 'script':
        return f"脚本更新({d})·严格增量:2026发布+±50%合理性"
    if src == 'ai':
        return f"AI核实({d})·GLM5.3-Flash/Qwen-Flash双模型一致·豆包终审"
    return f"AI核实({d})·多模型校验·豆包终审"


def main() -> None:
    if not BASE.exists():
        print("基准文件缺失", file=sys.stderr)
        sys.exit(1)
    d = json.loads(BASE.read_text(encoding='utf-8'))
    cities = [k for k in d if k != '_meta']
    n = len(cities)

    lines = [
        "# 📋 社保公积金政策总表（2026 年度）",
        "",
        f"**生成日期：{TODAY}**",
        "",
        "> 数据来源：AI 多模型核实（GLM-5.3-Flash / Qwen-Flash 各自独立从 gov.cn 官方原文抽取）"
        " + Doubao-Seed-Evolving 终审裁决 + 脚本抓取严格增量更新。",
        "> **校验方式列**：AI核实=双模型独立交叉+豆包终审；脚本更新=2026发布+数值合理性过滤后的增量；待核=暂未获取官方值。",
        "> **更新频率列**：社保/公积金缴费基数通常**年度**调整（4月/7月为高峰）；失业费率阶段性延续；工伤行业浮动不定期。",
        "> 生效日期若无记录暂时留空；数据以各市人社局/医保局/公积金中心官方通告为准。",
        "",
        "---",
        "",
        f"## 📊 覆盖：{n} 城 × 7 险种",
        "",
        "| 城市 | 生效日期 | 险种 | 基数上限(元) | 基数下限(元) | 个人% | 公司% | 校验方式 | 更新频率 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for city in sorted(cities):
        v = d[city]
        for ins in INS_ORDER:
            x = v.get(ins)
            if x is None:
                # 无该险种（如多数城市无补充公积金）→ 不生成该行
                continue
            if should_skip_insurance(x):
                # 个人/公司比例均为0或并入医保（如生育险）→ 不生成该行
                continue
            up, lo = x.get('基数上限') or '—', x.get('基数下限') or '—'
            has_val = any(x.get(k) not in (None, '—') for k in ('基数上限', '基数下限', '个人比例%', '公司比例%'))
            lines.append(
                f"| {city} | — | {ins} | {up} | {lo} | {x.get('个人比例%') or '—'} | {x.get('公司比例%') or '—'} "
                f"| {verify_detail(v, has_val)} | {INS_FREQ[ins]} |"
            )
    lines += ["", "---", f"_本报告由 china-si-phf-policy 自动生成于 {TODAY}_"]
    report = "\n".join(lines)

    OUT.mkdir(exist_ok=True)
    (OUT / "社保公积金政策.md").write_text(report, encoding='utf-8')
    print("✅ 已生成: 社保公积金政策.md（单一大表）")
    if '--dated' in sys.argv:
        (OUT / f"社保公积金政策_{TODAY}.md").write_text(report, encoding='utf-8')
        print("✅ 已生成版本快照: 社保公积金政策_%s.md" % TODAY)
    snap = REPO / "data" / f"city_insurance_2026_{TODAY}.json"
    snap.write_text(BASE.read_text(encoding='utf-8'), encoding='utf-8')
    print("✅ 已生成数据快照: %s" % snap.name)


if __name__ == '__main__':
    main()
