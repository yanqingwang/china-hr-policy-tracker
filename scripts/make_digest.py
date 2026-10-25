#!/usr/bin/env python3
"""对比每日抓取前后的 state.json，产出当日新增条目 data/digest_new.json。

由 scripts/run_daily.sh 在阿里云服务器上调用（抓取 src.main 之前把 state.json
备份到临时文件）。新增判定 = 抓取后 seen uid − 抓取前 seen uid，与 GitHub
Actions 侧的订阅 state 解耦（CI 不重复消费 seen）。

用法: make_digest.py <state_before> <state_after> <items.json> <out.json>
"""

import json
import sys
from pathlib import Path

KEEP_KEYS = ["uid", "title", "url", "region", "region_city", "district", "category",
             "policy_type", "publish_date", "effective_date", "publisher", "is_key",
             "extracted", "history", "detail_text"]
DETAIL_CAP = 800  # 控制产物体积，摘要邮件只需要开头几句


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    before_p, after_p, items_p, out_p = sys.argv[1:5]

    before = set()
    try:
        before = set(json.loads(Path(before_p).read_text(encoding="utf-8")).get("seen") or [])
    except Exception as exc:
        print(f"[make_digest] state_before 读取失败（视为全量新增）: {exc}", file=sys.stderr)
    after = set(json.loads(Path(after_p).read_text(encoding="utf-8")).get("seen") or [])
    new_uids = after - before

    items = json.loads(Path(items_p).read_text(encoding="utf-8"))
    new = []
    for r in items:
        if r.get("uid") not in new_uids:
            continue
        slim = {k: r.get(k) for k in KEEP_KEYS}
        if slim.get("detail_text") and len(slim["detail_text"]) > DETAIL_CAP:
            slim["detail_text"] = slim["detail_text"][:DETAIL_CAP] + "…"
        new.append(slim)
    new.sort(key=lambda r: (r.get("category") or "", r.get("region") or ""))
    Path(out_p).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[make_digest] {len(new)} new items -> {out_p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
