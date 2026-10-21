"""70 大中城市搜索发现式采集（DuckDuckGo HTML 端点，结果仅收 *.gov.cn）。

设计与隐私：
- 每城两条定向查询：{城市} 社保缴费基数调整 / {城市} 住房公积金 缴存基数；
- 结果域名过滤到 *.gov.cn / *.gov.cn.* —— 原发布单位（政府站）优先原则由域名硬约束保证；
- 探测失败（限流/断网）优雅降级为 0 条，并写 data/discovery-cache.json 供下轮比对；
- 只索引公开政策页，不接触个人信息。
"""
import datetime as dt
import json
import random
import re
import time
import urllib.parse
from pathlib import Path

import yaml

from src import util

ROOT = Path(__file__).resolve().parent.parent
DDG = "https://html.duckduckgo.com/html/?q={q}&kl=cn-zh"
RESULT_A = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I
)
SNIPPET = re.compile(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S | re.I)
UDM_RE = re.compile(r"uddg=([^&=]+)")

QUERIES = [
    "{city} 社保 缴费基数 调整",
    "{city} 住房公积金 缴存基数",
    "{city} 住房公积金 缴存比例 自主选择",
]
DELAY = (2.0, 3.5)
DETAIL_FETCH_CAP = 30   # 每次 run 抓正文提取的社保类条目上限（防撞 workflow 时长）


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", util.text_of(s)).strip()


def _decode_href(href: str) -> str | None:
    m = UDM_RE.search(href)
    raw = urllib.parse.unquote(m.group(1)) if m else href
    if not raw.startswith("http"):
        return None
    return raw


def _is_gov(url: str) -> bool:
    import urllib.parse
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return host.endswith(".gov.cn") or host.endswith(".gov")


def _resolve_publishers(url: str, city: str) -> tuple[str, int]:
    host = urllib.parse.urlparse(url).netloc.lower()
    # 城市级官方（人社局/公积金中心/政府门户）
    if "gjj" in host or "rsj" in host or "rs" in host or "renshe" in host:
        return f"{city}官方", 4
    if "rsj" in host or "hrss" in host:
        return f"{city}人社局", 4
    return f"{city}政府网", 4


def fetch(source: dict) -> list[dict]:
    cities = (source.get("cities") or "").split(",") if isinstance(source.get("cities"), str) else source.get("cities")
    if not cities:
        cfg = yaml.safe_load((ROOT / "data" / "cities.yml").read_text(encoding="utf-8"))
        cities = cfg.get("cities") or []
    limit_cities = int(source.get("limit_cities") or 0)
    if limit_cities:
        cities = cities[:limit_cities]

    out, cache = [], []
    for city in cities:
        for tpl in QUERIES:
            q = tpl.format(city=city)
            url = DDG.format(q=urllib.parse.quote(q))
            html = util.http_get(url)
            time.sleep(random.uniform(*DELAY))
            if html is None:
                cache.append({"city": city, "q": q, "ok": False})
                continue
            txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
            wins = RESULT_A.findall(txt)
            snippets = SNIPPET.findall(txt)
            hit = 0
            for i, (href, label) in enumerate(wins):
                final = _decode_href(href)
                if not final or not _is_gov(final):
                    continue
                title = _strip(label)
                if len(title) < 8:
                    continue
                snippet = _strip(snippets[i]) if i < len(snippets) else ""
                region = city
                if "省" in title and city not in title:
                    region = f"{city}(省域)"
                publisher, rank = _resolve_publishers(final, city)
                cache.append({"city": city, "q": q, "ok": True, "n": len(wins)})
                out.append({
                    "title": title[:120],
                    "url": final,
                    "publisher": publisher,
                    "publisher_rank": rank,
                    "region": region,
                    "publish_date": util.first_date(snippet) or util.first_date(title),
                    "source_id": source["id"],
                    "snippet": snippet[:400],
                })
                hit += 1
                if hit >= 6:     # 每查询最多 6 条，控制后续正文抓取量
                    break
    cache_path = ROOT / "data" / "discovery-cache.json"
    cache_path.write_text(json.dumps(cache, ensure_ascii=False)[:200000] if False else json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def enrich_details(recs: list[dict]) -> None:
    """社保公积金发现条目：抓详情页正文做数字提取（带总量上限，防爆时长）。"""
    n = 0
    for r in recs:
        if r.get("category") != "社保公积金" or n >= DETAIL_FETCH_CAP:
            continue
        # 短超时：详情提取不能拖垮整期（试点教训：20s×45 最坏 16 分钟）
        html = util.http_get(r["url"], timeout=10)
        time.sleep(random.uniform(0.5, 1.2))
        if html is None:
            continue
        text = util.text_of(html)
        from src import normalize as N
        r["extracted"] = N.extract_fields(r["title"], text)
        n += 1
