"""规范化：分类、地区、生效日期、社保公积金的数字提取。"""
import re

from src import util

CATEGORIES = [
    ("社保公积金", r"社保|社会保险|缴费基数|社保基数|公积金|住房公积金"),
    ("个税", r"个税|个人所得税|专项附加"),
    ("工资与劳动合同", r"最低工资|工资支付|薪酬|劳动合同|年终奖"),
    ("工作许可与人才引进", r"工作许可|外国人|来华|人才引进|引进人才|积分落户|落户"),
    ("补贴与保险待遇", r"补贴|稳岗|失业保险|工伤保险|生育保险|养老金|退休|津贴|残疾人就业|残保金"),
    ("HR 服务情报", r"灵活用工|灵活就业|招聘|人力|裁员|员工福利|薪酬"),
]


def classify(title: str, source_adapter: str = "") -> str:
    if source_adapter == "vendor_news":
        return "HR 服务情报"
    for cat, pat in CATEGORIES:
        if re.search(pat, title or ""):
            return cat
    return "其他"

POLICY_SUBTYPES = [
    ("公积金-缴存比例", r"缴存比例|缴费比例|比例.{0,10}自主|比例.{0,10}选择"),
    ("公积金-基数", r"公积金.{0,8}基数|缴存基数"),
    ("公积金", r"公积金"),
    ("社保-养老", r"养老|退休"),
    ("社保-医疗", r"医疗|医保"),
    ("社保-失业", r"失业"),
    ("社保-工伤", r"工伤"),
    ("社保-生育", r"生育"),
    ("社保-综合基数", r"缴费基数|社保基数|缴费工资基数|工资基数|基数上下限|社保缴费"),
    ("最低工资", r"最低工资"),
    ("个税", r"个税|个人所得税"),
    ("工作许可", r"工作许可|外国人"),
    ("人才引进", r"人才引进|落户|引进人才"),
    ("就业补贴", r"就业补贴|稳岗|岗位补贴|创业补贴"),
]


def policy_type(title: str) -> str:
    for sub, pat in POLICY_SUBTYPES:
        if re.search(pat, title or ""):
            return sub
    return "—"


def _num(s: str) -> int | None:
    try:
        return int(re.sub(r"[,，]", "", s))
    except ValueError:
        return None


def _ratio(s: str) -> float | None:
    try:
        return float(s.rstrip("%"))
    except ValueError:
        return None


def extract_fields(title: str, page_text: str = "") -> dict:
    """社保公积金类条目的关键数字提取（自动提取，读原文复核）。"""
    text = f"{title} 。 {page_text[:8000]}"
    out = {}

    m = re.search(r"由\s*([\d,，]{3,})\s*元?\s*(?:调整为|调至|调整为|提高到|上调为|上调至|调整为)\s*([\d,，]{3,})\s*元", text)
    if m:
        out["base_old"], out["base_new"] = _num(m.group(1)), _num(m.group(2))

    if "base_new" not in out:
        m = re.search(r"(?:缴费基数|缴存基数|社保缴费基数)\D{0,10}([\d,，]{4,})\s*元", text)
        if m:
            out["base_new"] = _num(m.group(1))

    m = re.search(r"(?:上限|封顶|最高)\D{0,8}([\d,，]{4,})\s*元", text)
    if m:
        out["cap_new"] = _num(m.group(1))
    m = re.search(r"(?:下限|保底|最低)\D{0,8}([\d,，]{4,})\s*元", text)
    if m:
        out["floor_new"] = _num(m.group(1))

    m = re.search(r"(?:缴费比例|缴存比例)\s*(?:由)?\s*([\d.]+)\s*%(?:\s*(?:调整为|调至|为|提高到)\s*([\d.]+)\s*%)?", text)
    if m:
        out["ratio_old"] = _ratio(m.group(1)) or None
        out["ratio_new"] = _ratio(m.group(2)) if m.group(2) else None

    # 拆分比例（单位/公司 vs 个人/职工）——社保公积金公司/个人部分分离
    # 1) 明确「单位(缴存/缴费)比例 X%」/「个人(缴存/缴费)比例 Y%」
    m = re.search(r"(?:单位|公司|用人单位)\s*(?:缴存|缴费)?\s*比例\s*[:：为]?\s*([\d.]+)\s*%", text)
    if m:
        out["ratio_company"] = _ratio(m.group(1))
    m = re.search(r"(?:个人|职工|员工)\s*(?:缴存|缴费)?\s*比例\s*[:：为]?\s*([\d.]+)\s*%", text)
    if m:
        out["ratio_individual"] = _ratio(m.group(1))
    # 2) 连写「缴存比例为单位X%个人Y%」/「单位X%、个人Y%」
    m = re.search(r"缴存比例\s*(?:为)?\s*单位\s*([\d.]+)\s*%\D{0,6}个人\s*([\d.]+)\s*%", text)
    if m:
        out["ratio_company"] = _ratio(m.group(1))
        out["ratio_individual"] = _ratio(m.group(2))
    m = re.search(r"单位\s*([\d.]+)\s*%\s*[、和及与]\s*个人\s*([\d.]+)\s*%", text)
    if m:
        out["ratio_company"] = _ratio(m.group(1))
        out["ratio_individual"] = _ratio(m.group(2))
    # 2.1) 「单位、个人各 X%」/「个人、单位各 X%」（同比例）
    m = re.search(
        r"(?:单位|公司)\s*[、和及与]\s*(?:个人|职工|员工)\s*(?:缴存|缴费)?\s*(?:比例)?\s*各\s*(?:为|执行)?\s*([\d.]+)\s*%", text
    )
    if m:
        out["ratio_company"] = _ratio(m.group(1))
        out["ratio_individual"] = _ratio(m.group(1))
    m = re.search(
        r"(?:个人|职工|员工)\s*[、和及与]\s*(?:单位|公司)\s*(?:缴存|缴费)?\s*(?:比例)?\s*各\s*(?:为|执行)?\s*([\d.]+)\s*%", text
    )
    if m:
        out["ratio_company"] = _ratio(m.group(1))
        out["ratio_individual"] = _ratio(m.group(1))

    # 3) 月缴存额拆分（如「单位月缴存额为102元、个人月缴存额为102元」）
    m = re.search(r"(?:单位|公司|用人单位)\s*(?:月缴存额|缴存额|缴费额)\s*(?:为|是)?\s*([\d,，]+)\s*元", text)
    if m:
        out["monthly_company"] = _num(m.group(1))
    m = re.search(r"(?:个人|职工|员工)\s*(?:月缴存额|缴存额|缴费额)\s*(?:为|是)?\s*([\d,，]+)\s*元", text)
    if m:
        out["monthly_individual"] = _num(m.group(1))
    # 合计/最低月缴存额（如「最低月缴存额为204元（其中单位…个人…）」）
    m = re.search(r"(?:最低月缴存额|月缴存额(?:下限|最低)|\b月缴存额为)\D{0,6}([\d,，]+)\s*元", text)
    if m:
        out["monthly_min"] = _num(m.group(1))

    # 4) 比例未明确但可推导：缴存额 ÷ 缴存基数 = 比例（如 102/2040 = 5%）
    if out.get("ratio_company") is None or out.get("ratio_individual") is None:
        base = out.get("base_new") or out.get("floor_new") or out.get("cap_new")
        if base:
            if out.get("ratio_company") is None and out.get("monthly_company") is not None:
                out["ratio_company"] = round(out["monthly_company"] * 100 / base, 2)
            if out.get("ratio_individual") is None and out.get("monthly_individual") is not None:
                out["ratio_individual"] = round(out["monthly_individual"] * 100 / base, 2)

    # 弹性缴存（东莞模式）：「比例可在 X%–Y% 之间（自行/自主）选择」
    m = re.search(
        r"(?:比例|缴存比例).{0,16}?([\d.]+)\s*%\s*[至到~—–\-]{1,2}\s*([\d.]+)\s*%"
        r".{0,18}?(自行|自主|选择|自愿|灵活)", text
    )
    if m:
        out["ratio_range"] = f"{m.group(1)}%–{m.group(2)}%（可自行选择）"
        out.pop("ratio_new", None)   # 区间语义优先于单值

    # 弹性缴存（区间下限/上限）：「不低于 X% 且不高于 Y%」/「不低于X%、不高于Y%」
    m = re.search(
        r"不低于\s*([\d.]+)\s*%\D{0,10}不高于\s*([\d.]+)\s*%", text
    )
    if m:
        lo, hi = _ratio(m.group(1)), _ratio(m.group(2))
        out["ratio_range"] = f"{lo:g}%–{hi:g}%（不低于/不高于）"
        out.pop("ratio_new", None)

    # 把"由 X 调至 Y"语言同时也匹配上下限
    m = re.search(r"上限\s*(?:由)\s*([\d,，]{4,})\s*元?\s*(?:调整为|调至)\s*([\d,，]{4,})\s*元", text)
    if m:
        out["cap_old"], out["cap_new"] = _num(m.group(1)), _num(m.group(2))
    m = re.search(r"下限\s*(?:由)\s*([\d,，]{4,})\s*元?\s*(?:调整为|调至)\s*([\d,，]{4,})\s*元", text)
    if m:
        out["floor_old"], out["floor_new"] = _num(m.group(1)), _num(m.group(2))

    return out


def build(raw: dict) -> dict:
    """raw(adapter产出) -> canonical record。"""
    title = raw["title"].strip()
    url = raw["url"]
    city = raw.get("region") or util.guess_region(title)
    if city == "—":
        city = util.guess_region(title)
    region, district = util.split_region(title, city)
    pt = policy_type(title)
    rec = {
        "uid": util.sha(url),
        "title": title,
        "url": url,
        "publisher": raw.get("publisher") or "—",
        "publisher_rank": raw.get("publisher_rank") or 3,
        "region": region,                 # 区域显示名（城市 或 城市+园区/新区）
        "region_city": city,              # 城市/基础区域
        "district": district,             # 区级细分（园区/新区/高新区…）
        "category": classify(title, raw.get("source_adapter", "")),
        "policy_type": pt,
        "key": util.sha(f"{region}|{pt}"),   # (区域, 保险类型) 唯一标识
        "publish_date": raw.get("publish_date"),
        "effective_date": util.effective_from_text(title),
        "extracted": None,
        "history": [],                     # 同 key 的历史版本（沿革）
        "is_vendor": bool(raw.get("is_vendor")),
        "source_id": raw.get("source_id"),
        "detail_text": None,
    }
    if rec["region"] == "—" and re.search(
        r"国务院|人社部|人力资源社会保障部|税务总局|财政部|民政部", title
    ):
        rec["region"] = "全国"
        rec["region_city"] = "全国"
    return rec
