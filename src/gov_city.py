"""城市官方门户直扫适配器（人社局/公积金中心/政府门户）。

依赖 data/city_channels.yml（每城 ≥1 个已复验可达的官方 URL），不依赖外部搜索引擎，
因此 GitHub Actions（会拦 DDG/bing/mojeek）也能工作；城市站个别被 WAF/网络拦时优雅降级。

- 关键词锚定的静态链接扫描（与 gov_list 同套逻辑）；
- region 标为城市名（供 70 城覆盖统计），source_id=city-portal；
- 只索引 *.gov.cn（city_channels 本身已限定官方域名）。
"""
import re
from pathlib import Path

import yaml

from src import util

ROOT = Path(__file__).resolve().parent.parent

KW = re.compile(
    r"社保|社会保险|缴费基数|公积金|住房公积金|缴存|最低工资|个税|个人所得税"
    r"|工作许可|外国人|人才引进|落户|稳岗|就业|失业|工伤|生育|养老金|退休"
    r"|劳动|用工|职业病|残保金|残疾人就业|缴费比例|缴存比例|基数调整"
)
A_RE = re.compile(r"<a[^>]*?href=\"([^\"]+)\"[^>]*?>([^<>]{6,110})</a>", re.I)


def load_channels() -> dict[str, str]:
    cfg = yaml.safe_load((ROOT / "data" / "city_channels.yml").read_text(encoding="utf-8"))
    return cfg.get("channels") or {}


def scan_city(city: str, page: str) -> list[dict]:
    """扫单个城市门户页，返回命中条目（带 region/source_id）。"""
    items = []
    html = util.http_get(page, timeout=12)
    if html is None:
        return items
    txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
    for href, label in A_RE.findall(txt):
        title = re.sub(r"\s+", "", util.text_of(label))
        if len(title) < 8 or not KW.search(title):
            continue
        url = util.ensure_absolute(href, page)
        if not url or url.lower().endswith((".png", ".jpg", ".css", ".js", ".ico", ".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            continue
        if ".gov.cn" not in url:
            continue
        date = util.first_date(label) or util.first_date(txt[max(0, txt.find(label)):txt.find(label) + 200])
        items.append({
            "title": title, "url": url, "publisher": f"{city}官方",
            "publisher_rank": 4, "region": city,
            "publish_date": date, "source_id": "city-portal",
        })
    return items


def scan_many(city_urls: list[tuple[str, str]]) -> list[dict]:
    out = []
    for city, page in city_urls:
        out.extend(scan_city(city, page))
    return out


def fetch(source: dict) -> list[dict]:
    """内联全量（本地/无分片时用）：扫描全部城市通道。"""
    channels = load_channels()
    if source.get("limit_cities"):
        channels = dict(list(channels.items())[: source["limit_cities"]])
    return scan_many([(c, u) for c, u in channels.items()])
