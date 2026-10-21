"""中国人力资源政策情报库 fetch/parse utilities."""
import hashlib
import re
import urllib.parse

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
TIMEOUT = 20

# 人力资源相关政策标题必须命中的关键词（用于过滤门户首页/无关部门噪声）
HR_TITLE_RE = re.compile(
    r"社保|社会保险|公积金|住房公积金|缴存|缴费基数|缴费比例|缴存基数|缴存比例|"
    r"最低工资|工资|养老金|养老|失业|工伤|生育|医保|医疗保险|医疗|就业|人才|落户|"
    r"劳动|劳动合同|补贴|稳岗|残保金|福利|薪酬|基数|比例|社保卡|人力资源|劳动保障|"
    r"职称|职业资格|职业技能|就业见习|创业补贴|工伤认定|劳动仲裁|调解仲裁|集体合同"
)
# 与人力资源政策无关的部门/领域（仅当标题命中这些且无 HR 词时排除）
UNRELATED_BUREAU_RE = re.compile(
    r"文旅|旅游|统计局|公安|交通|住建|生态环境|市场监管|应急管理|农业农村|"
    r"地震|气象|海关|民宗|档案|商务局|水务|林业"
)


def is_hr_relevant(title: str, url: str) -> bool:
    """过滤：标题须含人力资源相关政策词；排除门户首页 URL 与无关部门。"""
    if not HR_TITLE_RE.search(title or ""):
        return False
    try:
        path = urllib.parse.urlparse(url or "").path.rstrip("/")
    except Exception:
        path = ""
    if path in ("", "/") or re.match(
        r"^(index|default)(_\d+)?\.(html?|shtml|aspx)?$", path, re.I
    ):
        return False  # 门户首页（无具体政策页面）
    if UNRELATED_BUREAU_RE.search(title or ""):
        return False
    return True


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

# 有独立社保/公积金政策的区/园区/新区（区级差异：如苏州工业园区）
STANDALONE_DISTRICTS = [
    "雄安新区", "前海深港现代服务业合作区", "前海合作区", "横琴粤澳深度合作区",
    "海南自由贸易港", "上海自贸区临港新片区", "苏州工业园区",
    "中新苏州工业园区", "天津滨海新区", "浦东新区", "上海浦东新区",
]
DISTRICT_SUFFIXES = [
    "工业园区", "经济技术开发区", "经济开发区", "高新区", "高新技术产业开发区",
    "保税区", "自贸试验区", "临港新片区", "新区",
]


def split_region(text: str, city: str = "") -> tuple[str, str | None]:
    """从标题/正文识别区级政策域，返回 (区域显示名, 区级 or None)。

    - 标题含独立政策区（雄安/前海/横琴/苏州工业园区…）→ 直接用该区名；
    - 含「工业园区/高新区/新区」等后缀 → 拼成 {city}+{区}（如 苏州工业园区）；
    - 否则返回 city 原样。
    """
    if not text:
        return city, None
    for sa in STANDALONE_DISTRICTS:
        if sa in text:
            return sa, sa
    for suf in DISTRICT_SUFFIXES:
        if suf in text:
            base = city or ""
            # 标题里已带区名（如「苏州工业园区」）则直接用它
            if city and city in text:
                m = re.search(rf"([\u4e00-\u9fa5]{{2,6}}{re.escape(suf)})", text)
                if m:
                    return m.group(1), m.group(1)
            return f"{base}{suf}" if base else suf, suf
    return city, None


def guess_region(text: str) -> str:
    for w in REGION_WORDS:
        if w in text:
            return "全国" if w == "全国" else w
    return "—"
