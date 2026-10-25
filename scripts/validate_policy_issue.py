#!/usr/bin/env python3
"""校验「📝 社保公积金政策纠错」issue 表单提交。

由 .github/workflows/policy-data-check.yml 在 issue 打开时调用：
解析表单字段 → 格式与数值逻辑校验 → 回帖列出结果 → 打「校验通过/需补充信息」标签。

环境变量：GITHUB_TOKEN, ISSUE_NUMBER, ISSUE_BODY
"""

import os
import re
import subprocess
import sys

NO_RESPONSE = "_No response_"

REQUIRED_FIELDS = ["问题类型", "省 / 自治区 / 直辖市", "城市", "险种", "官方原文链接", "问题说明"]

ALLOWED_INSURANCE = ["养老", "医疗", "生育", "失业", "工伤", "公积金", "补充公积金"]

NON_NUMERIC_TOKENS = {"—", "-", "—", "无", "并入医保", "不适用"}


def parse_body(body: str) -> dict:
    """GitHub issue forms 的正文以 `### 字段名` 分节，返回 {字段名: 值}。"""
    fields = {}
    current = None
    for line in body.splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    return {k: "\n".join(v).strip() for k, v in fields.items()}


def get(fields: dict, key_prefix: str) -> str:
    for k, v in fields.items():
        if k.startswith(key_prefix):
            return v
    return ""


def parse_number(text: str):
    """返回 (ok, values)。支持 27603 / 27,603 / 5~12 / 0.2-1.9。"""
    t = text.strip().rstrip("%")
    if t in NON_NUMERIC_TOKENS:
        return True, []
    t = t.replace(",", "")
    parts = re.split(r"[~～\-–—]", t)
    values = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        try:
            values.append(float(p))
        except ValueError:
            return False, []
    return True, values


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    number = os.environ.get("ISSUE_NUMBER", "")
    fields = parse_body(body)

    errors, warnings, passes = [], [], []

    # 必填项
    for name in REQUIRED_FIELDS:
        val = get(fields, name)
        if not val or val == NO_RESPONSE:
            errors.append(f"缺少必填项：**{name}**")
        else:
            passes.append(f"{name} 已填写")

    # 险种取值合法性
    insurance = get(fields, "险种")
    if insurance and insurance != NO_RESPONSE and insurance not in ALLOWED_INSURANCE:
        errors.append(f"险种 `{insurance}` 不在允许范围（{'、'.join(ALLOWED_INSURANCE)}）")

    # 生效日期格式
    date = get(fields, "生效日期")
    if date and date != NO_RESPONSE:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date.strip()) or date.strip() in NON_NUMERIC_TOKENS:
            passes.append("生效日期格式正确")
        else:
            errors.append(f"生效日期 `{date}` 不是 YYYY-MM-DD 格式（官方未公布请填 —）")

    # 基数上下限：数值合法 + 上限 >= 下限
    cap, floor = get(fields, "基数上限"), get(fields, "基数下限")
    cap_ok, cap_vals = parse_number(cap) if cap not in ("", NO_RESPONSE) else (True, [])
    floor_ok, floor_vals = parse_number(floor) if floor not in ("", NO_RESPONSE) else (True, [])
    if not cap_ok:
        errors.append(f"基数上限 `{cap}` 不是合法数字")
    if not floor_ok:
        errors.append(f"基数下限 `{floor}` 不是合法数字")
    if cap_ok and floor_ok and cap_vals and floor_vals:
        if cap_vals[0] >= floor_vals[0]:
            passes.append("基数上限 ≥ 基数下限")
        else:
            errors.append(f"基数上限 {cap_vals[0]:g} 小于基数下限 {floor_vals[0]:g}，请核对")
    for label, vals in (("基数上限", cap_vals), ("基数下限", floor_vals)):
        if vals and not (500 <= vals[0] <= 200000):
            warnings.append(f"{label} {vals[0]:g} 超出常见区间（500~200000），请确认是否为月缴基数")

    # 个人% / 公司%：0~100 的数字或区间
    for label in ("个人%", "公司%"):
        val = get(fields, label)
        if val in ("", NO_RESPONSE):
            continue
        ok, vals = parse_number(val)
        if not ok:
            errors.append(f"{label} `{val}` 不是合法数字或区间（示例：8、5~12、0.2~1.9）")
            continue
        bad = [v for v in vals if not (0 <= v <= 100)]
        if bad:
            errors.append(f"{label} `{val}` 中的数值 {bad} 不在 0~100 范围")
        else:
            passes.append(f"{label} 数值范围合法")

    # 官方来源链接
    url = get(fields, "官方原文链接")
    if url and url != NO_RESPONSE:
        if not re.match(r"^https?://", url.strip()):
            errors.append(f"官方原文链接 `{url}` 不是 http(s) 链接")
        elif "gov.cn" not in url:
            warnings.append(f"链接不含 gov.cn 域名（`{url}`），非官方来源需人工核实后才会采纳")

    emoji_errors = "\n".join(f"- ❌ {e}" for e in errors)
    emoji_warnings = "\n".join(f"- ⚠️ {w}" for w in warnings)
    emoji_passes = "\n".join(f"- ✅ {p}" for p in passes)

    if errors:
        verdict = "❌ **自动校验未通过**，请按下方提示修改后评论 `retry` 或直接编辑原 issue，机器人会在 issue 重新打开时复核。"
        label = "需补充信息"
        color = "d93f0b"
    else:
        verdict = "✅ **自动校验通过**，等待维护者核对官方原文后更新总表。"
        label = "校验通过"
        color = "0e8a16"

    comment = "\n\n".join(
        ["## 🤖 表单自动校验结果", verdict, "### 检查明细", emoji_passes or "- （无）"]
    )
    if emoji_warnings:
        comment += "\n### 提醒\n" + emoji_warnings
    if emoji_errors:
        comment += "\n### 需要修正\n" + emoji_errors

    env = {**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")}

    def gh(*args: str) -> bool:
        r = subprocess.run(["gh", *args], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return False
        return True

    # 标签可能不存在，--force 幂等创建
    gh("label", "create", label, "--color", color, "--force",
       "--description", "社保公积金政策纠错表单自动校验")
    gh("issue", "edit", number, "--add-label", label)
    gh("issue", "comment", number, "--body", comment)
    print(f"issue #{number}: {label}（errors={len(errors)} warnings={len(warnings)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
