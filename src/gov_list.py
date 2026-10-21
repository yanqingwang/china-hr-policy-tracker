"""政府/机构频道列表页通用扫描器：关键词锚定的 <a> 链接 + 邻近日期提取。

不依赖站点具体 DOM 结构（政府站结构各异且常带反爬）；
同时尝试 JSON 检索接口的站点配置一个 use_json 可扩展。
"""
import re

from src import util

KW = re.compile(
    r"社保|社会保险|缴费基数|公积金|住房公积金|最低工资|个税|个人所得税"
    r"|工作许可|外国人|人才引进|落户|稳岗|就业|失业|工伤|生育|养老金|退休"
    r"|劳动|用工|职业病|残保金|残疾人就业"
)
A_RE = re.compile(r"<a[^>]*?href=\"([^\"]+)\"[^>]*?>([^<>]{6,110})</a>", re.I)


def fetch(source: dict) -> list[dict]:
    items = []
    rank = source.get("priority") or 3
    region = source.get("region") or "—"
    for page in source.get("pages") or []:
        html = util.http_get(page)
        if html is None:
            continue
        txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
        for href, label in A_RE.findall(txt):
            title = re.sub(r"\s+", "", util.text_of(label))
            if len(title) < 8 or not KW.search(title):
                continue
            url = util.ensure_absolute(href, page)
            if not url or url.lower().endswith((".png", ".jpg", ".css", ".js", ".ico")):
                continue
            date = util.first_date(label) or util.first_date(txt[max(0, txt.find(label) - 4):txt.find(label) + len(label) + 120])
            items.append({
                "title": title, "url": url, "publisher": source.get("name") or source["id"],
                "publisher_rank": rank, "region": region,
                "publish_date": date, "source_id": source["id"],
            })
    if source.get("use_json_search"):   # 有站内检索 JSON API 时次要路径
        try:
            import json as _json
            import urllib.parse
            js_url = source["use_json_search"].format(q=urllib.parse.quote(source.get("json_query", "")))
            raw = util.http_get(js_url)
            if raw:
                data = _json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"), strict=False)
                for d in _find_docs(data):
                    title = util.text_of(d.get("title", ""))
                    if KW.search(title):
                        items.append({"title": title, "url": d.get("url", ""),
                                      "publisher": source.get("name") or source["id"],
                                      "publisher_rank": rank, "region": region,
                                      "publish_date": util.first_date(d.get("pubtimeStr", "")),
                                      "source_id": source["id"]})
        except Exception:
            pass
    return items


def _find_docs(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("title") and node.get("url"):
            out.append(node)
        for v in node.values():
            _find_docs(v, out)
    elif isinstance(node, list):
        for x in node:
            _find_docs(x, out)
    return out
