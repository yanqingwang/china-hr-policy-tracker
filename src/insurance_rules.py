# -*- coding: utf-8 -*-
"""
社保公积金数据展示/更新 统一规则（所有脚本共用）。

排除规则：
1. 城市无该险种（如多数城市无补充公积金）→ 省略该行；
2. 个人比例=0 且 公司比例=0 / 并入医保(视为0) / 无 → 省略该行（如生育险并入医保）；
3. 仅当 基数/比例/上下限 发生真实变化时才更新对应条目（增量更新脚本用）。

用法：
    from src.insurance_rules import should_skip_insurance, is_skip_city_insurance
"""
import re

# 视为"无实际缴费"的公司比例表述
_ZERO_OR_MERGED = ('0', '0.0', '0%', '并入医保', '并入', '无', '—')


def should_skip_insurance(x: dict) -> bool:
    """是否应省略该险种行：个人比例=0 且 公司比例=0或并入医保(视为0) → True。"""
    if not isinstance(x, dict):
        return True                     # 无数据 → 省略
    p = x.get('个人比例%')
    c = x.get('公司比例%')
    if p is None or str(p) not in ('0', '0.0'):
        return False                    # 个人比例非0 → 保留
    if c is None:
        return False                    # 公司比例缺失但个人非0 → 保留（保守）
    cs = str(c).strip()
    if cs in _ZERO_OR_MERGED:
        return True
    if '并入' in cs or '含在' in cs or '含于' in cs:
        return True                     # "并入医保/含在医保内" 视为0
    return False


def effective_rows(city_data: dict, ins_order):
    """按规则过滤出应显示的行列表：[(险种, 数据dict), ...]。"""
    out = []
    if not isinstance(city_data, dict):
        return out
    for ins in ins_order:
        x = city_data.get(ins)
        if x is None:
            continue                     # 无该险种 → 省略
        if should_skip_insurance(x):
            continue                     # 0/并入医保 → 省略
        out.append((ins, x))
    return out
