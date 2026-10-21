"""HR 服务商（FESCO/中智/RIS 等/行业媒体）新闻与政策解读 adapter——尽力而为。

政策解读类内容会和官方公告做"同题关联"，表格里解读永远挂在原文之后，不给独立行。
"""
import re

from src import util

A_RE = re.compile(r"<a[^>]*?href=\"([^\"]+)\"[^>]*?>([^<>]{6,120})</a>", re.I)
KW = re.compile(
    r"社保|公积金|最低工资|个税|工作许可|人才引进|落户|用工|人力|招聘|灵活用工"
    r"|灵活就业|薪酬|员工福利|年终奖|社保基数|企业版|HR|裁员|劳动法|劳动合同"
)


def fetch(source: dict) -> list[dict]:
    items = []
    rank = source.get("priority") or 2   # 服务商解读 < 官方
    for page in source.get("pages") or []:
        html = util.http_get(page)
        if html is None:
            continue
        txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
        for href, label in A_RE.findall(txt):
            title = re.sub(r"\s+", "", util.text_of(label))
            if len(title) < 10 or not KW.search(title):
                continue
            url = util.ensure_absolute(href, page)
            if not url or url.lower().endswith((".png", ".jpg", ".css", ".js", ".ico")):
                continue
            date = util.first_date(label) or util.first_date(txt[max(0, txt.find(label)):txt.find(label) + 300])
            items.append({
                "title": title, "url": url, "publisher": source.get("name") or source["id"],
                "publisher_rank": rank, "region": source.get("region") or "全国",
                "publish_date": date, "source_id": source["id"], "is_vendor": True,
            })
    return items
