"""合并去重：uid 主键；同题多源时保留原发布单位/权威机构，服务商解读降级为主题关联；
社保公积金条目按 (区域, 保险类型) 折叠——同一生效期只保留一条当前有效政策，历史版本入沿革。"""
import difflib
import datetime as dt

from src import util


def _cur_date() -> str:
    return dt.date.today().isoformat()


def _rank_key(r: dict) -> tuple:
    """当前有效性排序：生效日期（已生效且最新的优先）> 发布新近 > 权威级。"""
    def iso_neg(s: str) -> tuple:
        parts = (s or "9999").split("-")
        return tuple(-int(x or 0) for x in parts)
    eff = r.get("effective_date")
    pub = r.get("publish_date") or "0000"
    flag = 0 if (eff and eff <= _cur_date()) else 1
    return (flag, iso_neg(eff), iso_neg(pub), -(r.get("publisher_rank") or 0))


def _title_key(t: str) -> str:
    import re
    # 去掉机构名/文号头，仅保留句子核心，同题检测用
    t = re.sub(r"^(关于|公布|通知|发布|转发)\s*", "", t)
    t = re.sub(r"[\s（）()【】\[\]，,。.、…\-—]+'", "", t)
    return t


def _same_year_policy(a: dict, b: dict) -> bool:
    """社保公积金条目：跨年公告（如 2025/2026 基数调整）视为不同版本，不并入同题。

    同题合并只用于同一公告的多处转载；跨年版本交给 fold_history 做沿革。
    """
    if a.get("category") != "社保公积金":
        return False
    import re as _re
    ya = _year_of(a.get("publish_date")) or _year_in_title(a.get("title") or "")
    yb = _year_of(b.get("publish_date")) or _year_in_title(b.get("title") or "")
    return bool(ya) and bool(yb) and ya != yb


def _year_of(date: str | None) -> int | None:
    if not date or len(date) < 4:
        return None
    try:
        return int(date[:4])
    except ValueError:
        return None


def _year_in_title(title: str) -> int | None:
    import re as _re
    m = _re.search(r"(20\d{2})\s*年", title)
    return int(m.group(1)) if m else None


def merge(records: list[dict]) -> list[dict]:
    """核心合并：同 URL 直接 dedupe；同题（相似度>0.8）保留 publisher_rank 更高者。"""
    by_uid: dict[str, dict] = {}
    by_title: list[tuple[str, dict]] = []   # (title_key, rec)

    for r in records:
        r = dict(r)
        same_title = None
        best = -1.0
        for tk, other in by_title:
            ratio = difflib.SequenceMatcher(None, _title_key(r["title"]), tk).ratio()
            if ratio > best:
                best, same_title = ratio, (tk, other)
        if same_title and best > 0.80 and not _same_year_policy(r, other):
            tk, other = same_title
            # 原发布单位/权威机构优先
            if r["publisher_rank"] > other["publisher_rank"]:
                merged = r
            else:
                merged = other
            # 数字提取/原文引用合并更强者
            for k, v in r.items():
                if k not in ("title", "url") and merged.get(k) in (None, "", 0, "—"):
                    if v not in (None, "", 0, "—"):
                        merged[k] = v
            if not merged.get("quotes") and r.get("quotes"):
                merged["quotes"] = r["quotes"]   # 原文引用随权威记录保留
            merged.setdefault("dup_links", [])
            if r["url"] != merged["url"]:
                merged["dup_links"].append(r["url"])
            # 用 merged 替换
            idx = [i for i, (a, _b) in enumerate(by_title) if a == tk][0]
            by_title[idx] = (tk, merged)
            by_uid[merged["uid"]] = merged
            if r["uid"] != merged["uid"]:
                by_uid.pop(r["uid"], None)
            continue
        by_uid[r["uid"]] = r
        by_title.append((_title_key(r["title"]), r))
    return list(by_uid.values())


def fold_history(records: list[dict]) -> list[dict]:
    """社保公积金按 (区域, 保险类型) 折叠：每组保留当前有效政策为主行，历史版本入沿革。

    - 同一生效期只保留一条（排序后取第一个）；
    - 其余（更早生效/更旧发布）折叠进主记录的 history，避免同城同险种多条公告挤在主表；
    - 非社保公积金条目原样保留。
    """
    groups: dict[str, list[dict]] = {}
    keep: list[dict] = []
    for r in records:
        if r.get("category") != "社保公积金" or not r.get("key"):
            keep.append(r)
            continue
        groups.setdefault(r["key"], []).append(r)

    for key, recs in groups.items():
        recs.sort(key=_rank_key)
        cur = recs[0]
        cur["history"] = [h for h in recs[1:]]
        keep.append(cur)
    return keep
