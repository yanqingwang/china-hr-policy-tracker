"""合并去重：uid 主键；同题多源时保留原发布单位/权威机构，服务商解读降级为主题关联。"""
import difflib

from src import util


def _title_key(t: str) -> str:
    import re
    # 去掉机构名/文号头，仅保留句子核心，同题检测用
    t = re.sub(r"^(关于|公布|通知|发布|转发)\s*", "", t)
    t = re.sub(r"[\s（）()【】\[\]，,。.、…\-—]+'", "", t)
    return t


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
        if same_title and best > 0.80:
            tk, other = same_title
            # 原发布单位/权威机构优先
            if r["publisher_rank"] > other["publisher_rank"]:
                merged = r
            else:
                merged = other
            # 数字提取/原文链接合并更强者
            for k, v in r.items():
                if k not in ("title", "url") and merged.get(k) in (None, "", 0, "—"):
                    if v not in (None, "", 0, "—"):
                        merged[k] = v
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
