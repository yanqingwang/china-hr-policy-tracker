"""gov.cn 政策文件库全文检索 adapter（title/url/pubtimeStr/puborg 结构已验证）。"""
import json
import urllib.parse

from src import util

API = ("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary&q={q}"
       "&timetype=timeqb&mintime=&maxtime=&sort=pubtime&sortType=1&searchfield="
       "&childtype=&subchildtype=&tsbq=&pubtimeyear=&puborg=&pcodeYear=&pcodeNum="
       "&filetype=&p={p}&n={n}&inpro=&bmfl=&dup=&orpro=&jue=no")

# 检索词 → （标题匹配关键词集合）——API 相关性偏松，靠标题二级过滤收敛
HR_QUERIES = {
    "社保": ("社保|社会保险|缴费基数|社保基数|养老保险|医疗保险|工伤保险|失业保险",),
    "公积金": ("住房公积金|公积金",),
    "最低工资": ("最低工资|工资支付",),
    "外国人工作许可": ("来华工作许可|外国人工作|工作许可证|工作类居留",),
    "人才引进": ("人才引进|引进人才|积分落户|落户|人力资源市场",),
    "个人所得税": ("个人所得税|个税|专项附加",),
    "就业补贴": ("就业补贴|岗位补贴|创业补贴|稳岗|就业促进",),
    "劳动合同": ("劳动合同|劳务派遣|女职工|生育假|育儿假",),
    "残保金": ("残疾人就业保障金|残保金|残疾人就业",),
}


def _kw_ok(title: str, words: str) -> bool:
    import re
    return re.search(words, title or "") is not None


def fetch(source: dict) -> list[dict]:
    items = []
    region = source.get("region") or "全国"
    rank = source.get("priority") or 5
    n_per = int(source.get("n_per_query") or 20)
    for kw, (w,) in HR_QUERIES.items():
        path = API.format(q=urllib.parse.quote(kw), p=1, n=n_per)
        raw = util.http_get(path)
        if raw is None:
            continue
        try:
            data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"), strict=False)
        except Exception:
            continue
        docs = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("title") and node.get("url"):
                    docs.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        walk(data.get("searchVO") or {})
        for d in docs:
            title = util.text_of(d["title"]).strip()
            if not _kw_ok(title, w):
                continue  # API 相关性偏松 → 标题必须命中人力相关词
            url = d["url"]
            if "www.gov.cn/zhengce" not in url:
                continue
            pub = util.text_of(d.get("puborg") or "国务院") or "国务院"
            pubdate = (d.get("pubtimeStr") or "").replace(".", "-")
            pubdate = pubdate[:10] if len(pubdate) >= 10 and pubdate.count("-") == 2 else None
            items.append({
                "title": title, "url": url, "publisher": pub, "publisher_rank": rank,
                "region": util.guess_region(title) if region == "全国" else region,
                "publish_date": pubdate, "source_id": source["id"], "source_kw": kw,
            })
    return items
