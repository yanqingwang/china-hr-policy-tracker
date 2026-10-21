"""70 大中城市搜索发现式采集（多搜索引擎后端，结果仅收 *.gov.cn）。

设计与隐私：
- 每城三条定向查询：社保缴费基数 / 公积金缴存基数 / 公积金缴存比例自选；
- 结果域名过滤到 *.gov.cn —— 原发布单位优先由域名硬约束保证；
- 后端池：DuckDuckGo(HTML) → cn.bing → Mojeek；启动探测选可用后端，
  中途断连自动切换下一后端（GitHub Actions 常拦 DDG，本地 DDG 可用）；
- 探测失败（限流/断网）优雅降级为 0 条，并写 data/discovery-cache-*.json；
- 只索引公开政策页，不接触个人信息。
"""
import json
import random
import re
import time
import urllib.parse
from pathlib import Path

import yaml

from src import util

ROOT = Path(__file__).resolve().parent.parent

QUERIES = [
    "{city} 社保 缴费基数 调整",
    "{city} 住房公积金 缴存基数",
    "{city} 住房公积金 缴存比例 自主选择",
]
DELAY = (1.5, 3.0)
DETAIL_FETCH_CAP = 30   # 每次 run 抓正文提取的社保类条目目标（有效条数）
DETAIL_FETCH_MAX = 80   # 单次 run 最多抓取条数硬上限（无效文件会被跳过重抓，防爆时长）

UDM_RE = re.compile(r"uddg=([^&=]+)")
A_SNIPPET = re.compile(r"<a[^>]*class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>", re.S | re.I)


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
    import urllib.parse
    host = urllib.parse.urlparse(url).netloc.lower()
    if "gjj" in host or "rsj" in host or "rs" in host or "renshe" in host:
        return f"{city}官方", 4
    if "hrss" in host:
        return f"{city}人社局", 4
    return f"{city}政府网", 4


def _url_date(url: str) -> str | None:
    """从 URL 路径取发布日期（t20260821_* / 202608/ 目录模式）。"""
    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


# ---------------- 后端解析 ----------------
def _parse_ddg(html: str) -> list[tuple[str, str, str]]:
    out = []
    wins = re.findall(r"<a[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", html, re.S | re.I)
    snips = A_SNIPPET.findall(html)
    for i, (href, label) in enumerate(wins):
        final = _decode_href(href)
        if not final:
            continue
        out.append((final, _strip(label), _strip(snips[i]) if i < len(snips) else ""))
    return out


def _parse_cnbing(html: str) -> list[tuple[str, str, str]]:
    out = []
    for m in re.finditer(r"<h2[^>]*><a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a></h2>", html, re.S | re.I):
        url, title = m.group(1), _strip(m.group(2))
        seg = html[m.end():m.end() + 900]
        snip = re.search(r"<p[^>]*>(.*?)</p>", seg, re.S)
        out.append((url, title, _strip(snip.group(1)) if snip else ""))
    return out


def _parse_mojeek(html: str) -> list[tuple[str, str, str]]:
    out = []
    for m in re.finditer(r"<a[^>]*class=\"[^\"]*title[^\"]*\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", html, re.S | re.I):
        url, title = m.group(1), _strip(m.group(2))
        seg = html[m.end():m.end() + 700]
        snip = re.search(r"<p[^>]*>(.*?)</p>", seg, re.S)
        out.append((url, title, _strip(snip.group(1)) if snip else ""))
    return out


BACKENDS = [
    ("ddg", "https://html.duckduckgo.com/html/?q={q}&kl=cn-zh", _parse_ddg),
    ("cnbing", "https://cn.bing.com/search?q={q}&setlang=zh-CN", _parse_cnbing),
    ("mojeek", "https://www.mojeek.com/search?q={q}", _parse_mojeek),
]


def _probe_backend() -> tuple[str, object]:
    """逐个后端探测可用性（发首个查询，页面可读即可用）。"""
    probe_q = urllib.parse.quote("北京 社保 缴费基数 调整")
    for name, tpl, parser in BACKENDS:
        html = util.http_get(tpl.format(q=probe_q), timeout=12)
        if html is not None:
            return name, parser
    return BACKENDS[0][0], BACKENDS[0][2]   # 全挂则仍用首个（记录失败）


def _scan(cities: list[str], source: dict) -> tuple[list[dict], list[dict]]:
    """对给定城市集合执行定向查询；返回 (原始条目, 查询缓存)。"""
    out, cache = [], []
    active, parser = _probe_backend()
    fails = 0
    for city in cities:
        for tpl in QUERIES:
            q = tpl.format(city=city)
            url = active + ":" + q
            html = util.http_get(BACKENDS[_bi(active)][1].format(q=urllib.parse.quote(q)), timeout=12)
            time.sleep(random.uniform(*DELAY))
            if html is None:
                # 断连 → 切换下一后端重试一次
                nxt = (BACKENDS[_bi(active) + 1] if _bi(active) + 1 < len(BACKENDS) else BACKENDS[0])
                html = util.http_get(nxt[1].format(q=urllib.parse.quote(q)), timeout=12)
                if html is None:
                    fails += 1
                    cache.append({"city": city, "q": q, "backend": active, "ok": False})
                    continue
                active, parser = nxt[0], nxt[2]
                fails = 0
            txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
            results = parser(txt)
            if not results:
                fails += 1
                if fails >= 5:   # 连续空结果 → 换后端
                    active, parser = BACKENDS[(_bi(active) + 1) % len(BACKENDS)][0], BACKENDS[(_bi(active) + 1) % len(BACKENDS)][2]
                    fails = 0
            hit = 0
            for final, title, snippet in results:
                if not _is_gov(final) or len(title) < 8:
                    continue
                region = city
                if "省" in title and city not in title:
                    region = f"{city}(省域)"
                publisher, rank = _resolve_publishers(final, city)
                cache.append({"city": city, "q": q, "backend": active, "ok": True, "n": len(results)})
                out.append({
                    "title": title[:120],
                    "url": final,
                    "publisher": publisher,
                    "publisher_rank": rank,
                    "region": region,
                    "publish_date": util.first_date(snippet) or util.first_date(title) or _url_date(final),
                    "source_id": source["id"],
                    "snippet": snippet[:400],
                })
                hit += 1
                if hit >= 6:     # 每查询最多 6 条，控制后续正文抓取量
                    break
    cache.insert(0, {"backend_active": active, "cities": len(cities), "queries": len(cities) * len(QUERIES)})
    return out, cache


def _bi(name: str) -> int:
    for i, b in enumerate(BACKENDS):
        if b[0] == name:
            return i
    return 0


def fetch(source: dict) -> list[dict]:
    cities = (source.get("cities") or "").split(",") if isinstance(source.get("cities"), str) else source.get("cities")
    if not cities:
        cfg = yaml.safe_load((ROOT / "data" / "cities.yml").read_text(encoding="utf-8"))
        cities = cfg.get("cities") or []
    limit_cities = int(source.get("limit_cities") or 0)
    if limit_cities:
        cities = cities[:limit_cities]

    out, cache = _scan(cities, source)
    _write_cache(source.get("shard_tag") or "all", cache)
    return out


def _write_cache(tag: str, cache: list[dict]) -> None:
    path = ROOT / "data" / f"discovery-cache-{tag}.json"
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def enrich_details(recs: list[dict]) -> None:
    """社保公积金发现条目：抓详情页正文做数字提取 + 内容有效性校验（带总量上限，防爆时长）。

    抓到的文件若无实质政策内容（has_policy_content=False）视为无效文件剔除，
    并继续抓取后续候选（尝试获取其他文件），直到凑够 DETAIL_FETCH_CAP 条有效记录。
    按标题含数字关键词与否排序，让最可能出数字的条目优先。
    """
    import re as _re
    keyed = []
    for i, r in enumerate(recs):
        if r.get("category") != "社保公积金":
            continue
        keyed.append((0 if _re.search(r"基数|比例|上限|下限|调整|最低工资|补贴", r.get("title") or "") else 1, i, r))
    keyed.sort()
    n_fetched = 0
    n_valid = 0
    for _, i, r in keyed:
        # 凑够有效条数即停；硬上限 DETAIL_FETCH_MAX 防爆时长
        if n_valid >= DETAIL_FETCH_CAP or n_fetched >= DETAIL_FETCH_MAX:
            break
        # 短超时：详情提取不能拖垮整期（试点教训：20s×45 最坏 16 分钟）
        html = util.http_get(r["url"], timeout=10)
        time.sleep(random.uniform(0.5, 1.2))
        if html is None:
            continue
        n_fetched += 1
        text = util.text_of(html)
        from src import normalize as N
        if not N.has_policy_content(text):
            # 无实质政策内容 → 无效文件，剔除，继续尝试其他文件
            r["_invalid"] = True
            continue
        r["extracted"] = N.extract_fields(r["title"], text)
        if not r.get("quotes"):
            r["quotes"] = util.pick_quotes(text)
        n_valid += 1
    # 剔除无效条目（原地过滤，保留其余类别）
    recs[:] = [r for r in recs if not r.get("_invalid")]
