"""china-hr-si-phf-policy orchestrator.

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
from src import gov_search, gov_list, vendor_news, search_discovery, gov_city  # noqa: E402
from src import render, mailer                     # noqa: E402

ADAPTERS = {"gov_search": gov_search, "gov_list": gov_list,
            "vendor_news": vendor_news, "search_discovery": search_discovery,
            "gov_city": gov_city}


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


def _load_shard_items() -> list[dict]:
    """读取分片发现产物（data/discovery-shard-*.json）+ 阿里云侧产物（discovery-aliyun.json），供汇总模式构建周报。"""
    raws = []
    for p in sorted((REPO_ROOT / "data").glob("discovery-shard-*.json")):
        try:
            raws.extend(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"[shard] {p.name} 读取失败: {exc}", file=sys.stderr)
    aliyun_path = REPO_ROOT / "data" / "discovery-aliyun.json"
    if aliyun_path.exists():
        try:
            raws.extend(json.loads(aliyun_path.read_text(encoding="utf-8")))
            print(f"[aliyun] 合并 {aliyun_path.stat().st_size} 字节", file=sys.stderr)
        except Exception as exc:
            print(f"[aliyun] 读取失败: {exc}", file=sys.stderr)
    return raws


def collect(args) -> list[dict]:
    recs = []
    for s in load_sources():
        # 分片汇总模式：内联城市门户/搜索发现已由分片产物覆盖，跳过避免重复
        if args.use_discovery and s.get("adapter") in ("search_discovery", "gov_city"):
            continue
        try:
            if args.limit_cities and s.get("adapter") == "search_discovery":
                s = dict(s); s["limit_cities"] = args.limit_cities
            raws = s["_mod"].fetch(s)
        except Exception as exc:
            print(f"[{s['id']}] adapter error: {exc}", file=sys.stderr)
            raws = []
        for raw in raws:
            raw["source_adapter"] = s["source_adapter"]
            rec = normalize.build(raw)
            if rec is None:
                continue                       # 非政策类噪声（决算/采购/人事等）
            if extra := (raw.get("snippet") and {"_snippet": raw["snippet"]}):
                rec["detail_text"] = extra["_snippet"]   # 摘要先行，详情页补提
            recs.append(rec)
        print(f"[{s['id']}] items={len(raws)}", file=sys.stderr)

    if args.use_discovery:
        sharded = _load_shard_items()
        for raw in sharded:
            raw.setdefault("source_adapter", "search_discovery")
            rec = normalize.build(raw)
            if rec is None:
                continue                       # 非政策类噪声
            if raw.get("snippet"):
                rec["detail_text"] = raw["snippet"]
            recs.append(rec)
        print(f"[shard-assemble] items={len(sharded)}", file=sys.stderr)

    # 社保公积金发现条目：抓详情页正文做数字提取（70 城覆盖的核心表格）
    try:
        if args.detail:
            search_discovery.enrich_details(recs)
    except Exception as exc:
        print(f"[enrich] error: {exc}", file=sys.stderr)
    return recs


def ext(title: str, text: str) -> dict:
    from src import normalize as N
    return N.extract_fields(title, text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mail", action="store_true")
    ap.add_argument("--detail", action="store_true", help="社保公积金条目抓详情页做数字提取")
    ap.add_argument("--limit-cities", type=int, default=0, help="测试用：限制发现自己式的城市数")
    ap.add_argument("--use-discovery", action="store_true",
                    help="汇总模式：读取 data/discovery-shard-*.json，跳过内联 70 城扫描")
    ap.add_argument("--detail-cap", type=int, default=60,
                    help="详情页数字提取上限（默认 60，防撞 workflow 时长）")
    args = ap.parse_args()
    if args.detail_cap:
        search_discovery.DETAIL_FETCH_CAP = args.detail_cap
        search_discovery.DETAIL_FETCH_MAX = max(search_discovery.DETAIL_FETCH_MAX, args.detail_cap * 3)

    recs = collect(args)
    merged = merge.merge(recs)
    merged_prefold = merged                    # state 基于折叠前全集（历史 URL 也算见过）
    merged = merge.fold_history(merged)        # 同(区域,保险类型)折叠，主表同刻唯一

    # state: 见过的 uid
    state_path = REPO_ROOT / "data" / "state.json"
    seen = set()
    if state_path.exists():
        try:
            seen = set(json.loads(state_path.read_text(encoding="utf-8")).get("seen") or [])
        except Exception:
            seen = set()
    new_recs = [r for r in merged_prefold if r["uid"] not in seen]
    seen |= {r["uid"] for r in merged_prefold}

    for r in new_recs:
        if r["category"] == "社保公积金" and (r.get("extracted") is None):
            r["extracted"] = ext(r["title"], r.get("detail_text") or "")
        # 原文引用：未做详情抓取时，用搜索摘要源文本兜底摘录
        if not r.get("quotes") and r.get("detail_text"):
            r["quotes"] = util.pick_quotes(r["detail_text"], limit=2, maxlen=140)

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
            attaches = [str(rep_dir / "weekly.md")]
            detail_report = rep_dir / "社保公积金政策.md"
            if detail_report.exists():
                attaches.append(str(detail_report))
                body = ("> 📎 本邮件附件含《社保公积金政策总表》"
                        "（144 城 × 7 险种缴费基数/比例明细，长表 9 列）与周报 markdown 原文。\n\n" + body)
            mailer.send(f"中国 HR/SI/PHF 政策仓库 {today.isoformat()}", body, attaches)
            print("邮件已发送（库主）", file=sys.stderr)
            try:
                from src import subscribers
                subs = subscribers.sendable(freq="weekly")
            except SystemExit:
                subs = []
            for email, _freq in subs:
                try:
                    mailer.send(f"中国 HR/SI/PHF 政策仓库 {today.isoformat()}", body, attaches, to=email)
                    print(f"邮件已发送（订阅者 {email[:3]}***）", file=sys.stderr)
                except Exception as exc:
                    print(f"订阅者发送失败: {type(exc).__name__}", file=sys.stderr)
        else:
            print("SMTP secrets 缺失，跳过邮件", file=sys.stderr)

    print(f"done: total={len(merged)} new={len(new_recs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
