#!/usr/bin/env python3
"""每日增量邮件（GitHub Actions 调用）：读 data/digest_new.json（阿里云服务器每日
抓取后生成的新增条目），有新增才发给选了「每日」频率的订阅者。

环境变量：SMTP_USER/SMTP_PASS（必需），SMTP_HOST/SMTP_PORT/MAIL_FROM（可选），
SUBSCRIBER_KEY（解密订阅名单，缺失则不发送）。
"""

import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import mailer, subscribers, util, render  # noqa: E402

DIGEST_PATH = REPO_ROOT / "data" / "digest_new.json"


def _quotes(r: dict, limit: int = 2) -> list[str]:
    if r.get("quotes"):
        return r["quotes"][:limit]
    if r.get("detail_text"):
        return util.pick_quotes(r["detail_text"], limit=limit, maxlen=140)
    return []


def render_digest(items: list[dict], today: str) -> str:
    si = [r for r in items if r.get("category") == "社保公积金"]
    lines = [
        f"# 📬 中国 HR/SI/PHF 政策 · 每日增量（{today}）",
        "",
        f"今日新增 **{len(items)}** 条（其中社保公积金类 {len(si)} 条）。",
        "全量数据见仓库 [`reports/社保公积金政策.md`](https://github.com/yanqingwang/china-hr-si-phf-policy-tracker/blob/main/reports/社保公积金政策.md)。",
        "",
    ]
    if si:
        lines += ["## 📊 社保公积金变化（数据表格）", "", render.fund_table(si), ""]
    lines += ["## 📑 全部新增条目", ""]
    for r in items:
        meta = f"{r.get('publish_date') or '—'} · {r.get('region') or '—'} · {(r.get('publisher') or '—')[:18]}"
        eff = f" · 生效 {r['effective_date']}" if r.get("effective_date") else ""
        lines.append(f"- 【{r.get('category') or '—'}】[{r['title']}]({r['url']}) — {meta}{eff}")
        for q in _quotes(r, limit=1):
            lines.append(f"  > 「{q}」")
    lines += ["", "---", "*本邮件由 china-hr-si-phf-policy 每日增量推送 · 仅在发现新政策时发送 · 逐条以官方原文为准。*"]
    return "\n".join(lines)


def main() -> int:
    items = []
    if DIGEST_PATH.exists():
        try:
            items = json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"digest_new.json 读取失败: {exc}", file=sys.stderr)
    if not items:
        print("今日无新增条目，不发送", file=sys.stderr)
        return 0
    if not mailer.enabled():
        print("SMTP secrets 缺失，跳过发送", file=sys.stderr)
        return 0
    try:
        subs = subscribers.sendable(freq="daily")
    except SystemExit:
        subs = []
    if not subs:
        print("无「每日」频率订阅者，跳过发送", file=sys.stderr)
        return 0

    today = dt.date.today().isoformat()
    n_si = sum(1 for r in items if r.get("category") == "社保公积金")
    subject = f"中国 HR/SI/PHF 政策每日增量 {today}（新增 {len(items)} 条，社保公积金 {n_si} 条）"
    body = render_digest(items, today)
    for email, _freq in subs:
        try:
            mailer.send(subject, body, None, to=email)
            print(f"每日增量已发送（{email[:3]}***）", file=sys.stderr)
        except Exception as exc:
            print(f"订阅者发送失败: {type(exc).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
