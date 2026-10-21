"""china-hr-policy-tracker orchestrator.

用法:
    python -m src.main            # 抓取 → 规范化 → 合并 → 周报 + README
    python -m src.main --mail     # 上同 + 周报邮件（库主 + 密文订阅名单）
    python -m src.main --detail   # 抓取社保公积金详情页正文用于数字提取（慢）
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml                                        # noqa: E402
from src import util, normalize, merge             # noqa: E402
from src import gov_search, gov_list, vendor_news  # noqa: E402
from src import render, mailer                     # noqa: E402

ADAPTERS = {"gov_search": gov_search, "gov_list": gov_list, "vendor_news": vendor_news}


def load_sources() -> list[dict]:
    with open(REPO_ROOT / "data" / "sources.yml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out = []
    for s in data.get("sources") or []:
        if not s.get("enabled", True):
            continue
        for a_name, mod in ADAPTERS.items():
            if s.get("adapter") == a_name:
                s = dict(s)
                s["source_adapter"] = a_name
                s["_mod"] = mod
                out.append(s)
    return out


def collect(args) -> list[dict]:
    recs = []
    for s in load_sources():
        try:
            raws = s["_mod"].fetch(s)
        except Exception as exc:
            print(f"[{s['id']}] adapter error: {exc}", file=sys.stderr)
            raws = []
        for raw in raws:
            raw["source_adapter"] = s["source_adapter"]
            rec = normalize.build(raw)
            # 社保公积金类：可选抓详情页正文提取数字
            if rec["category"] == "社保公积金" and args.detail and rec["extracted"] is None:
                html = util.http_get(rec["url"])
                if html:
                    text = util.text_of(html)
                    rec["extracted"] = ext(rec["title"], text)
            recs.append(rec)
        print(f"[{s['id']}] items={len(raws)}", file=sys.stderr)
    return recs


def ext(title: str, text: str) -> dict:
    from src import normalize as N
    return N.extract_fields(title, text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mail", action="store_true")
    ap.add_argument("--detail", action="store_true", help="社保公积金条目抓详情页做数字提取")
    args = ap.parse_args()

    recs = collect(args)
    merged = merge.merge(recs)

    # state: 见过的 uid
    state_path = REPO_ROOT / "data" / "state.json"
    seen = set()
    if state_path.exists():
        try:
            seen = set(json.loads(state_path.read_text(encoding="utf-8")).get("seen") or [])
        except Exception:
            seen = set()
    new_recs = [r for r in merged if r["uid"] not in seen]
    seen |= {r["uid"] for r in merged}

    for r in new_recs:
        if r["category"] == "社保公积金" and (r.get("extracted") is None):
            r["extracted"] = ext(r["title"], r.get("detail_text") or "")

    # report
    today = dt.date.today()
    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    rep_dir = REPO_ROOT / "reports"
    rep_dir.mkdir(exist_ok=True)
    render.report(merged, str(rep_dir / f"{week}.md"), week)
    render.report(merged, str(rep_dir / "weekly.md"), week)

    # README 注入（最近 40 条总览表）
    render.inject_readme(str(REPO_ROOT / "README.md"), merged, today.isoformat())

    # state/bucket
    items_path = REPO_ROOT / "data" / "items.json"
    try:
        keep = json.loads(items_path.read_text(encoding="utf-8")) if items_path.exists() else []
    except Exception:
        keep = []
    keep = new_recs + keep
    items_path.write_text(json.dumps(keep[:300], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    state_path.write_text(json.dumps({"seen": sorted(seen)[-2000:], "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                                     ensure_ascii=False, indent=2), encoding="utf-8")

    # 邮件（secret 缺失则跳过，不影响报告）
    if args.mail:
        if mailer.enabled():
            body = (rep_dir / "weekly.md").read_text(encoding="utf-8")
            attach = str(rep_dir / "weekly.md")
            mailer.send(f"中国人力资源政策周报 {today.isoformat()}", body, attach)
            print("邮件已发送（库主）", file=sys.stderr)
            try:
                from src import subscribers
                subs = subscribers.sendable()
            except SystemExit:
                subs = []
            for email, freq in subs:
                try:
                    mailer.send(f"中国人力资源政策周报 {today.isoformat()}", body, attach, to=email)
                    print(f"邮件已发送（订阅者）", file=sys.stderr)
                except Exception as exc:
                    print(f"订阅者发送失败: 天义 {type(exc).__name__}", file=sys.stderr)
        else:
            print("SMTP secrets 缺失，跳过邮件", file=sys.stderr)

    print(f"done: total={len(merged)} new={len(new_recs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
