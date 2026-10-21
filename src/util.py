"""中国人力资源政策情报库 fetch/parse utilities."""
import hashlib
import re

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
TIMEOUT = 20


def http_get(url: str, timeout: int = TIMEOUT) -> str | bytes | None:
    """Content best-effort; None 当页面不可达（单源失败不炸整期）."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.content
    except Exception:
        return None


def sha(uid_seed: str) -> str:
    import hashlib
    return hashlib.md5(uid_seed.encode("utf-8")).hexdigest()[:12]


def ensure_absolute(href: str, base: str) -> str | None:
    import urllib.parse
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "#", "mailto:")):
        return None
    return urllib.parse.urljoin(base, href)


def text_of(html: bytes) -> str:
    """极简 HTML -> 文本（去 script/style），保留日期/数字可读性。"""
    txt = html.decode("utf-8", "ignore") if isinstance(html, bytes) else html
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt


DATE_PATS = [
    (r"(\d{4})[-/yr.](\d{1,2})[-/y月.](\d{1,2})(?:日)?", r"\1-\2-\3"),
]


def first_date(text: str) -> str | None:
    """页面/标题里的第一个日期 → YYYY-MM-DD。"""
    m = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})[日号]?", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", text)
    return m.group(0) if m else None


def effective_from_text(text: str) -> str | None:
    m = re.search(r"[自从]\s*(20\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日?)?\s*起", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3) or 1)
        return f"{y}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s*起)?", text)
    if m and "自" in text[max(0, m.start() - 6):m.start()]:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def pick_quotes(text: str, limit: int = 3, maxlen: int = 160) -> list[str]:
    """政策原文关键句摘录（条文属法定文件不受著作权限制，逐句挂原文链接）。

    句级切分后按相关性词计分，取最高分前 limit 句；无命中返回 []。
    """
    sentences = [s.strip() for s in re.split(r"[。；！？\n\r]+", text or "") if s.strip()]
    scored = []
    for s in sentences:
        if len(s) < 10:
            continue
        score = 0
        for w, wt in (
            ("基数", 3), ("比例", 3), ("上限", 3), ("下限", 3),
            ("缴费", 2), ("缴存", 2), ("调整为", 3), ("调整为", 0), ("调至", 2),
            ("最低工资", 3), ("补贴", 2), ("标准", 1), ("元/月", 3),
            ("执行", 1), ("适用", 1),
        ):
            if w and w in s:
                score += wt
        if re.search(r"(20\d{2})\s*年\s*\d{1,2}\s*月", s):
            score += 2        # 带生效时间的句子更关键
        if score:
            scored.append((score, s))
    quoted, used = [], set()
    for score, s in sorted(scored, key=lambda x: (-x[0], len(x[1]))):
        key = s[:20]
        if key in used:
            continue
        used.add(key)
        quoted.append(s if len(s) <= maxlen else s[:maxlen - 1] + "…")
        if len(quoted) >= limit:
            break
    return quoted


REGION_WORDS = [
    "全国", "北京", "上海", "广州", "深圳", "天津", "重庆", "成都", "杭州", "苏州", "南京",
    "西安", "武汉", "郑州", "长沙", "合肥", "厦门", "青岛", "济南", "宁波", "无锡", "珠海",
    "广东", "江苏", "浙江", "山东", "四川", "湖北", "湖南", "河南", "河北", "福建", "安徽",
    "辽宁", "吉林", "黑龙江", "陕西", "山西", "广西", "云南", "贵州", "甘肃", "新疆",
    "内蒙古", "海南", "江西", "青海", "宁夏", "西藏", "大湾区",
]


def guess_region(text: str) -> str:
    for w in REGION_WORDS:
        if w in text:
            return "全国" if w == "全国" else w
    return "—"
