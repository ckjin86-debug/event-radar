"""Pure scoring rules for DART 5% large-shareholding filings.

Faithful Python port of the KR (OpenDART) path of the original
"DART 5% Super Radar v2.3" `rules.js` from the user's integrated
investment system package:

- ``normalize_purpose`` — 보유목적 정규화 (경영권/일반/단순, level 3/2/1)
- ``analyze_report_reason`` — 보고사유 분석 (장내매수/CB·메자닌/기계적
  변동/내부이체 구분과 S6 취득원천 점수)
- ``is_genuine_share_accumulation`` — 실제 보유주식수 증가 + 진성 취득 판정
- ``classify_investor`` — 보고자 분류 사전 (행동주의/가치/PEF·SI/패시브 +
  개인·슈퍼개미 판정)
- ``deduplicate_filing_amendments`` — 정정공시 중복 제거 (최신 정정본 우선)
- ``process_majorstock_history`` — majorstock.json 시계열 처리
  (연속매집횟수·직전 목적·최초 5% 공시일 산출)
- ``evaluate_signal_score`` — 7대 전략 스코어링 (S1~S7 분해 + 근거 문장)
- ``compute_ownership_freshness`` — 공시 신선도 (CURRENT/RECENT/AGING/STALE)

Scores, ordering and conditions follow the original exactly. The only
deliberate deviation: the price-dependent half of S6 (세력 평단 대비
현재가 괴리) is only computed when both an average acquisition price and
a current price are supplied in the item; without price data the
breakdown records "미산출(가격 데이터 필요)" with 0 points instead of
pulling a price provider into the rules engine. The SEC (13D/13G filing
ingestion) path of the original is not ported; the scoring core itself
is market-agnostic, exactly as in the original.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from zoneinfo import ZoneInfo


# ----------------------------------------------------------------------
# 보고자 분류 사전 (원본 DEFAULT_DICTIONARY 그대로)
# ----------------------------------------------------------------------
DEFAULT_DICTIONARY: dict[str, list[str]] = {
    "activist": [
        '얼라인파트너스', '얼라인', 'KCGI', '차파트너스', '플래쉬라이트', 'FCP',
        '안다자산운용', '트러스톤자산운용', '트러스톤', '팰리서', '시티오브런던',
        '화이트박스', '라이프자산운용', '클린테크', '더제이자산운용', '스트라이드',
        'Elliott', '엘리엇', 'Pershing Square', 'Bill Ackman', 'Third Point', 'Dan Loeb',
        'Icahn', 'Carl Icahn', 'Starboard Value', 'Starboard', 'ValueAct', 'Trian',
        'Nelson Peltz', 'Saba Capital', 'Engine No. 1', 'Mantle Ridge', 'Jana Partners', 'JANA Partners',
        'Ancora', 'Politan', 'Engaged Capital', 'Corvex', 'Fund 1 Investments', 'Voss Capital',
    ],
    "value": [
        'VIP자산운용', '브이아이피자산운용', '신영자산운용', '한국투자밸류자산운용',
        '한국투자밸류', '머스트자산운용', '베어링자산운용', '쿼드자산운용',
        '타임폴리오자산운용', '타임폴리오', '피델리티', 'Fidelity', '케이비자산운용', 'KB자산운용',
        '마이다스에셋', '에이치디씨자산운용', '디에스자산운용', 'DS자산운용', '바바리안',
        '티로우프라이스', 'T. Rowe Price', '타이거자산운용', '르네상스자산운용',
        'Berkshire Hathaway', 'Warren Buffett', 'Baupost', 'Seth Klarman',
        'Appaloosa', 'David Tepper', 'Scion Asset', 'Michael Burry',
        'Duquesne', 'Druckenmiller', 'Greenlight', 'David Einhorn', 'DME Capital', 'Tiger Global',
        'Coatue', 'Viking Global', 'Lone Pine', 'Himalaya Capital', 'Miri Capital', 'MiriCapital',
    ],
    "pef_si": [
        '사모투자', 'PEF', '경영참여형', '투자조합', '신기사조합', '파트너스', '인베스트먼트',
        '홀딩스', '모건스탠리', '골드만삭스', '어피니티', '한앤컴퍼니', '한앤코', 'MBK', 'IMM',
        'KKR', 'Blackstone', 'Carlyle', 'Apollo', 'Brookfield', 'Silver Lake', 'Thoma Bravo',
        'Capital Partners', 'LP', 'LLC',
    ],
    "passive": [
        '국민연금공단', '국민연금', '블랙록', 'BlackRock', 'Vanguard', '뱅가드',
        'State Street', '스테이트스트리트', '노르웨이은행', '노르웨이중앙은행', 'Norges',
        'GIC', '싱가포르투자청', '한국산업은행', '예금보험공사', '중소기업은행',
        '공무원연금', '사학연금', '우정사업본부', 'Geode Capital', 'Dimensional Fund',
    ],
}


# ----------------------------------------------------------------------
# 숫자 파싱 (원본 parseNumericShareCount / parseFloat 의미론)
# ----------------------------------------------------------------------
def parse_numeric_share_count(val: Any) -> Optional[float]:
    """Parse a share count ('+1,234,000주' 등). Returns None when absent.

    Mirrors the original: null/'-'/'' → None; commas, '주', spaces and a
    leading '+' are stripped before conversion.
    """
    if val is None or val == "-" or val == "":
        return None
    if isinstance(val, (int, float)):
        return None if val != val else float(val)  # NaN guard
    cleaned = re.sub(r"[,주\s+]", "", str(val))
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_float(val: Any, default: float = 0.0) -> float:
    """JS parseFloat equivalent for the fields the original feeds it."""
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return default


def _fmt_num(value: float) -> str:
    """JS Number#toLocaleString() approximation (en-US grouping)."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _fmt_signed_count(cnt_var: Any) -> str:
    num = parse_numeric_share_count(cnt_var)
    if num is None:
        return str(cnt_var or "-")
    sign = "+" if num > 0 else ""
    return f"{sign}{_fmt_num(num)}"


# ----------------------------------------------------------------------
# 날짜 헬퍼 (원본 formatDateStr / getDaysAgo / getKstTodayDateStr)
# ----------------------------------------------------------------------
def format_date_str(dt: Any = "") -> str:
    clean = re.sub(r"[^0-9]", "", str(dt or ""))
    if len(clean) == 8:
        return f"{clean[0:4]}-{clean[4:6]}-{clean[6:8]}"
    return str(dt or "-")


def _kst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", format_date_str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def get_days_ago(rcept_dt: Any = "", reference_date: Any = None) -> int:
    target = _to_date(rcept_dt)
    if target is None:
        return 0
    ref = _to_date(reference_date) if reference_date is not None else _kst_today()
    if ref is None:
        return 0
    return max(0, (ref - target).days)


def compute_ownership_freshness(
    rcept_dt_or_days: Any,
    reference_date: Any = None,
) -> str:
    """Ownership Freshness: 0~30 CURRENT, 31~90 RECENT, 91~180 AGING, 181+ STALE."""
    if isinstance(rcept_dt_or_days, (int, float)):
        days = max(0, int(rcept_dt_or_days))
    else:
        days = get_days_ago(rcept_dt_or_days, reference_date)
    if days <= 30:
        return "CURRENT"
    if days <= 90:
        return "RECENT"
    if days <= 180:
        return "AGING"
    return "STALE"


# ----------------------------------------------------------------------
# 보유목적 정규화 (원본 normalizePurpose)
# ----------------------------------------------------------------------
def normalize_purpose(raw_purpose: Any = "", report_title: Any = "") -> dict:
    text = f"{raw_purpose or ''} {report_title or ''}".strip()
    if (
        "경영권" in text
        or "경영참여" in text
        or "13D (경영권" in text
        or "Board" in text
        or "Take-Private" in text
        or "Control" in text
    ):
        return {"label": "경영권 영향 (13D)", "level": 3}
    if (
        "일반투자" in text
        or "(일반)" in text
        or "SC 13D" in text
        or "SCHEDULE 13D" in text
        or "13D" in text
    ):
        return {"label": "일반투자 (적극주주)", "level": 2}
    if (
        "단순투자" in text
        or "(약식)" in text
        or "SC 13G" in text
        or "SCHEDULE 13G" in text
        or "13G" in text
    ):
        return {"label": "단순투자 (13G/약식)", "level": 1}
    return {"label": str(raw_purpose or "단순투자"), "level": 1}


# ----------------------------------------------------------------------
# 보고사유 분석 (원본 analyzeReportReason)
# ----------------------------------------------------------------------
_MECHANICAL_RE = re.compile(
    r"이익소각|자사주\s*소각|주식소각|감자|합병|분할|액면병합|무상증자|"
    r"shares\s*of\s*Common\s*Stock\s*outstanding|change\s*in\s*the\s*number\s*of\s*shares|"
    r"no\s*change\s*in\s*the\s*number\s*of\s*shares",
    re.IGNORECASE,
)
_INTERNAL_RE = re.compile(
    r"내부이체|시간외대량매매|특별관계|공동보유|담보|합의|약정|No\s*transactions\s*in\s*the\s*Shares",
    re.IGNORECASE,
)
_MEZZANINE_RE = re.compile(
    r"전환사채|신주인수권|교환사채|CB인수|CB|BW|EB|전환권행사|전환청구|Convertible|Warrant|메자닌",
    re.IGNORECASE,
)
_OPEN_BUY_RE = re.compile(
    r"장내매수|장내\s*취득|장내매입|장내매매로\s*인한\s*5%\s*신규|Open\s*Market\s*Purchase|"
    r"장내\s*공격매수|단순\s*주식\s*취득",
    re.IGNORECASE,
)
_OPEN_SELL_RE = re.compile(
    r"장내매도|장내\s*처분|Open\s*Market\s*Sale|reduced\s*its\s*ownership|단순추가취득/처분",
    re.IGNORECASE,
)
_BLOCK_RE = re.compile(
    r"장외매수|장외취득|시간외대량매매|블록딜|주식양수도|유상신주취득|제3자배정|"
    r"Block\s*Deal|Private\s*Placement",
    re.IGNORECASE,
)
_PURPOSE_CHANGE_RE = re.compile(
    r"보유목적\s*변경|목적변경|목적의\s*변경|목적으로\s*보유목적\s*변경|13G\s*→\s*13D|13G\s*to\s*13D",
    re.IGNORECASE,
)


def analyze_report_reason(
    resn: Any = "",
    stk_cnt_var: Any = None,
    stk_rt_var: Any = None,
) -> dict:
    """보고사유 정밀 분석 (원본 analyzeReportReason와 동일 판정 순서)."""
    text = str(resn or "")
    cnt_delta = parse_numeric_share_count(stk_cnt_var)
    rt_delta = _parse_float(stk_rt_var, 0.0)

    result = {
        "is_open_market_buy": False,
        "is_open_market_sell": False,
        "is_mezzanine_or_cb": False,
        "is_block_deal_or_otc": False,
        "is_mechanical_or_share_count_change_only": False,
        "is_internal_or_contract_only": False,
        "is_purpose_change_mentioned": False,
        "summary_tag": None,
        "score_delta": 0,
    }

    # 1) 기계적 변동 / 발행주식총수 감소 / 내부이체·담보변경 판별
    if _MECHANICAL_RE.search(text):
        if cnt_delta is not None and cnt_delta <= 0:
            result["is_mechanical_or_share_count_change_only"] = True
            result["summary_tag"] = "발행주식수변동(매집아님)"
            result["score_delta"] = 0

    if cnt_delta == 0 and not result["is_mechanical_or_share_count_change_only"]:
        result["is_internal_or_contract_only"] = True
        if _INTERNAL_RE.search(text):
            result["summary_tag"] = "내부이체/계약변경(0주)"
        elif rt_delta > 0:
            result["is_mechanical_or_share_count_change_only"] = True
            result["summary_tag"] = "발행주식수감소(0주)"

    # 2) CB / BW / EB / 전환권 / 신주인수권 / 메자닌 판별
    if _MEZZANINE_RE.search(text) and not re.search(r"보통주\s*장내매수", text):
        result["is_mezzanine_or_cb"] = True
        result["summary_tag"] = "CB/메자닌(오버행주의)"
        result["score_delta"] = -2

    # 3) 실제 장내매수 / 장내매도 / 장외매수(블록딜) 판별
    if not result["is_mezzanine_or_cb"] and not result["is_mechanical_or_share_count_change_only"]:
        if _OPEN_BUY_RE.search(text) and (cnt_delta is None or cnt_delta > 0):
            result["is_open_market_buy"] = True
            result["summary_tag"] = "실탄 장내매수"
            result["score_delta"] += 2
        elif _OPEN_SELL_RE.search(text) and (
            (cnt_delta is not None and cnt_delta < 0) or rt_delta < 0
        ):
            result["is_open_market_sell"] = True
            result["summary_tag"] = "장내매도 처분"
            result["score_delta"] -= 1
        elif _BLOCK_RE.search(text) and (cnt_delta is not None and cnt_delta > 0):
            result["is_block_deal_or_otc"] = True
            result["summary_tag"] = "장외/블록딜 인수"
            result["score_delta"] += 1

    if _PURPOSE_CHANGE_RE.search(text):
        result["is_purpose_change_mentioned"] = True

    return result


# ----------------------------------------------------------------------
# 진성 매집 판정 (원본 isGenuineShareAccumulation)
# ----------------------------------------------------------------------
_NON_GENUINE_RE = re.compile(
    r"특별관계자의?\s*추가|특수관계자\s*추가|합병|분할|무상증자|전환권\s*행사|신주인수권\s*행사|교환청구"
)


def _row_ratio(row: dict) -> float:
    """stkrt ?? hold_stock_rt (JS nullish 의미론) 를 float로."""
    val = row.get("stkrt")
    if val is None:
        val = row.get("hold_stock_rt")
    return _parse_float(val, 0.0)


def _row_count(row: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if row.get(key) is not None:
            return parse_numeric_share_count(row.get(key))
    return None


def is_genuine_share_accumulation(curr_row: dict, prev_row: Optional[dict] = None) -> bool:
    """실제 보유주식수 증가 + 진성 취득 여부 판정 (원본과 동일)."""
    curr_cnt = _row_count(curr_row, "stkqy", "hold_stock_cnt")
    prev_cnt = _row_count(prev_row, "stkqy", "hold_stock_cnt") if prev_row else None
    cnt_var = _row_count(curr_row, "stkqy_irds", "stk_cnt_var")

    if cnt_var is None and curr_cnt is not None and prev_cnt is not None:
        cnt_var = curr_cnt - prev_cnt

    rt_var = _parse_float(
        curr_row.get("stkrt_irds", curr_row.get("stk_rt_var", 0)), 0.0
    )
    resn = str(curr_row.get("report_resn") or "")

    # 보유주식수 감소 또는 변동 없음(0주) -> 절대 매집 아님
    if cnt_var is not None and cnt_var <= 0:
        return False
    if curr_cnt is not None and prev_cnt is not None and curr_cnt <= prev_cnt:
        return False

    reason = analyze_report_reason(resn, cnt_var, rt_var)
    if (
        reason["is_mezzanine_or_cb"]
        or reason["is_mechanical_or_share_count_change_only"]
        or reason["is_internal_or_contract_only"]
    ):
        return False

    # 특별관계자 추가/편입만으로 주식수가 합산된 경우 배제
    if _NON_GENUINE_RE.search(resn) and not re.search(r"장내매수|장외매수", resn):
        return False

    if cnt_var is not None and cnt_var > 0:
        return True

    return rt_var > 0 and (reason["is_open_market_buy"] or reason["is_block_deal_or_otc"])


# ----------------------------------------------------------------------
# 세력매집단가 (원본 normalizePriceSourcePrefix / computePriceGap)
# ----------------------------------------------------------------------
def normalize_price_source_prefix(source: Any = "") -> str:
    s = str(source or "").strip()
    if not s:
        return ""
    if re.match(r"^(DISCLOSED|DERIVED|VWAP_ESTIMATE):", s, re.IGNORECASE):
        return s
    if re.search(r"원문|세부변동내역|단가표|Schedule\s*A|Exhibit\s*1|Form\s*4", s, re.IGNORECASE):
        return f"DISCLOSED: {s}"
    if re.search(r"Item\s*3|총취득|총매수|합계|자금조성", s, re.IGNORECASE):
        return f"DERIVED: {s}"
    return f"VWAP_ESTIMATE: {s}"


def compute_price_gap(
    est_avg_price: Any,
    current_price: Any,
    price_source: Any = "",
) -> Optional[dict]:
    """현재가 대비 세력 평단 괴리율. 가격 데이터가 없으면 None (원본과 동일)."""
    avg = _parse_float(est_avg_price, 0.0)
    curr = _parse_float(current_price, 0.0)
    if not avg or not curr or avg <= 0:
        return None
    gap_pct = float(
        (Decimal(str((curr / avg - 1) * 100)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        ))
    )
    normalized_src = normalize_price_source_prefix(price_source)
    return {
        "avg": avg,
        "curr": curr,
        "gap_pct": gap_pct,
        "is_safety_margin": gap_pct <= -5.0,
        "is_deep_safety": gap_pct <= -10.0,
        "is_vwap_estimate": normalized_src.startswith("VWAP_ESTIMATE:"),
        "price_source": normalized_src,
    }


# ----------------------------------------------------------------------
# 보고자 분류 (원본 classifyInvestor: 사전 + 개인/슈퍼개미 판정)
# ----------------------------------------------------------------------
_INDIVIDUAL_RE = re.compile(r"^[가-힣]{2,4}(\s*외\s*\d+인)?$")
_INDIVIDUAL_EXCLUDE_RE = re.compile(
    r"운용|투자|파트너|홀딩스|기업|은행|증권|보험|금고|재단|공단|조합|에셋|캐피탈"
)


def classify_investor(
    repror_name: Any = "",
    custom_dict: Optional[dict] = None,
) -> dict:
    """보고자 분류 (원본 판정 순서: 패시브 → 행동주의 → 가치 → PEF/SI → 개인)."""
    dictionary = custom_dict or DEFAULT_DICTIONARY
    name = str(repror_name or "").strip()
    lowered = name.lower()

    def _hit(key: str) -> bool:
        return any(kw.lower() in lowered for kw in dictionary.get(key, []))

    if _hit("passive"):
        return {"type": "PASSIVE", "label": "패시브/연기금", "base_score": 0, "badge_class": "tag-passive"}
    if _hit("activist"):
        return {"type": "ACTIVIST", "label": "행동주의", "base_score": 4, "badge_class": "tag-activist"}
    if _hit("value"):
        return {"type": "VALUE", "label": "가치투자/구루", "base_score": 3, "badge_class": "tag-value"}
    if _hit("pef_si"):
        return {"type": "PEF_SI", "label": "PEF/투자조합", "base_score": 2, "badge_class": "tag-pef"}
    if _INDIVIDUAL_RE.match(name) and not _INDIVIDUAL_EXCLUDE_RE.search(name):
        return {"type": "SUPER_ANT", "label": "슈퍼개미/개인", "base_score": 2, "badge_class": "tag-ant"}
    return {"type": "GENERAL", "label": "일반법인/기타", "base_score": 0, "badge_class": "tag-general"}


# ----------------------------------------------------------------------
# 7대 전략 스코어링 (원본 evaluateSignalScore, 순서·조건 그대로)
# ----------------------------------------------------------------------
def evaluate_signal_score(
    item: dict,
    custom_dict: Optional[dict] = None,
    reference_date: Any = None,
) -> dict:
    """7대 전략 통합 스코어링.

    item keys (원본과 동일): rpror_nm/repror, hold_stock_rt, stk_rt_var,
    stk_cnt_var, accum_count, curr_purpose, prev_purpose, report_nm,
    report_resn, is_new_entry, est_avg_price, current_price, price_source,
    rcept_dt, ownership_freshness.
    """
    tags: list[dict] = []
    breakdown: list[dict] = []
    primary_category = "ALL"

    factor_scores = {
        "s1_investor": 0,
        "s2_accumulation": 0,
        "s3_purpose": 0,
        "s4_new_entry": 0,
        "s5_milestone_10pct": 0,
        "s6_price_margin": 0,
        "s7_exit_risk": 0,
    }

    repror = item.get("rpror_nm") or item.get("repror") or ""
    investor = classify_investor(repror, custom_dict)
    diff = _parse_float(item.get("stk_rt_var"), 0.0)
    total_rt = _parse_float(item.get("hold_stock_rt"), 0.0)
    cnt_delta = parse_numeric_share_count(item.get("stk_cnt_var"))
    try:
        accum_count = int(item.get("accum_count") or 0)
    except (TypeError, ValueError):
        accum_count = 0

    freshness = item.get("ownership_freshness") or compute_ownership_freshness(
        item.get("rcept_dt"), reference_date
    )
    price_gap = compute_price_gap(
        item.get("est_avg_price"), item.get("current_price"), item.get("price_source")
    )

    # 패시브 노이즈 즉시 필터링 (단, 5% 이탈 시 이탈 태그 기록)
    if investor["type"] == "PASSIVE":
        is_below5_exit = (
            total_rt > 0 and total_rt < 5.0
            and (diff < 0 or (cnt_delta is not None and cnt_delta < 0))
        )
        passive_tags = [{"text": "패시브/연기금 노이즈", "cls": "tag-passive"}]
        if is_below5_exit:
            passive_tags.append({"text": "5% 미만 이탈(패시브)", "cls": "tag-exit"})
        return {
            "score": 0,
            "factor_scores": factor_scores,
            "tags": passive_tags,
            "breakdown": [{
                "strategy": "전략 1 (노이즈 필터)",
                "reason": f"{repror} 패시브/연기금 인덱스 리밸런싱 자동 제외",
                "points": 0,
            }],
            "category": "NOISE",
            "categories": ["NOISE"],
            "investor": investor,
            "curr_purpose_normalized": normalize_purpose(
                item.get("curr_purpose"), item.get("report_nm")
            )["label"],
            "price_gap": price_gap,
            "ownership_freshness": freshness,
            "recent_accumulation_signal_active": False,
        }

    # [S1] 주체 가중치
    if investor["base_score"] > 0:
        factor_scores["s1_investor"] += investor["base_score"]
        tags.append({"text": investor["label"], "cls": investor["badge_class"]})
        breakdown.append({
            "strategy": "전략 1 (주체 가중치)",
            "reason": f"{investor['label']} 핵심 주체 ({repror})",
            "points": investor["base_score"],
        })

    curr_p = normalize_purpose(item.get("curr_purpose"), item.get("report_nm"))
    prev_raw = item.get("prev_purpose")
    prev_p = (
        normalize_purpose(prev_raw)
        if prev_raw and prev_raw != "-"
        else None
    )
    reason_info = analyze_report_reason(
        item.get("report_resn"), item.get("stk_cnt_var"), item.get("stk_rt_var")
    )
    categories: set[str] = set()

    # [#7] 최신 보유비율 5.0% 미만 이탈 최우선 판정
    is_below5_exit = total_rt > 0 and total_rt < 5.0
    if is_below5_exit:
        sell_pts = -3 if (diff <= -2.0 or (cnt_delta is not None and cnt_delta < 0)) else -2
        factor_scores["s7_exit_risk"] += sell_pts - 4
        tags.append({"text": f"{diff:.2f}%p 축소", "cls": "tag-exit"})
        tags.append({"text": "▼5% 미만 이탈(공시의무소멸)", "cls": "tag-exit-critical"})
        breakdown.append({
            "strategy": "전략 7 (지분 축소)",
            "reason": f"직전 대비 {diff:.2f}%p ({item.get('stk_cnt_var') or ''}주) 지분 매도/감소",
            "points": sell_pts,
        })
        breakdown.append({
            "strategy": "전략 7 (5% 이탈 최우선 경보)",
            "reason": f"최신 보유비율 {total_rt:.2f}%로 5% 미만 진입 (공시의무 소멸 및 오버행 주의)",
            "points": -4,
        })

        if prev_p and curr_p["level"] < prev_p["level"]:
            factor_scores["s7_exit_risk"] -= 3
            tags.append({"text": "목적하향(이탈주의)", "cls": "tag-exit"})
            breakdown.append({
                "strategy": "전략 7 (목적 하향)",
                "reason": f"{prev_p['label']} → {curr_p['label']} 목적 하향",
                "points": -3,
            })

        if reason_info["is_open_market_sell"]:
            factor_scores["s6_price_margin"] -= 1
            tags.append({"text": "장내매도 처분", "cls": "tag-mezzanine"})
            breakdown.append({
                "strategy": "전략 6 (처분원천 확인)",
                "reason": f"보고사유: {item.get('report_resn')}",
                "points": -1,
            })

        categories.add("EXIT")
        return {
            "score": sum(factor_scores.values()),
            "factor_scores": factor_scores,
            "tags": tags,
            "breakdown": breakdown,
            "category": "EXIT",
            "categories": sorted(categories),
            "investor": investor,
            "curr_purpose_normalized": curr_p["label"],
            "price_gap": price_gap,
            "ownership_freshness": freshness,
            "recent_accumulation_signal_active": False,
        }

    # [#6] 보유목적 변화 판정
    purpose_upgraded = (
        (prev_p is not None and curr_p["level"] > prev_p["level"])
        or (
            prev_p is None
            and reason_info["is_purpose_change_mentioned"]
            and curr_p["level"] >= 2
        )
    )
    purpose_downgraded = prev_p is not None and curr_p["level"] < prev_p["level"]

    if purpose_upgraded:
        if curr_p["level"] == 3:
            factor_scores["s3_purpose"] += 5
            tags.append({"text": "★목적상향(경영권/13D)", "cls": "tag-purpose-critical"})
            breakdown.append({
                "strategy": "전략 3 (목적 변경)",
                "reason": f"{prev_p['label'] if prev_p else '기존'} → 경영권 영향(13D) 공식 상향",
                "points": 5,
            })
        else:
            factor_scores["s3_purpose"] += 3
            tags.append({"text": "★목적상향(일반/13D)", "cls": "tag-purpose"})
            breakdown.append({
                "strategy": "전략 3 (목적 변경)",
                "reason": f"{prev_p['label'] if prev_p else '단순투자'} → 일반투자(적극주주) 공식 상향",
                "points": 3,
            })
        categories.add("PURPOSE")
        primary_category = "PURPOSE"
    elif curr_p["level"] == 3:
        pts = 4 if item.get("is_new_entry") else 3
        factor_scores["s3_purpose"] += pts
        tags.append({
            "text": "경영권영향(13D) 진입" if item.get("is_new_entry") else "경영권영향(13D) 유지",
            "cls": "tag-purpose-critical",
        })
        breakdown.append({
            "strategy": "전략 3 (경영권 영향)",
            "reason": (
                "최초 진입부터 경영권 영향(Schedule 13D) 명시"
                if item.get("is_new_entry")
                else "경영권 영향(Schedule 13D) 목적 하 주주권 행사/보유 유지"
            ),
            "points": pts,
        })
        categories.add("PURPOSE")
        if primary_category == "ALL":
            primary_category = "PURPOSE"
    elif curr_p["level"] == 2 and not purpose_downgraded:
        factor_scores["s3_purpose"] += 2
        tags.append({"text": "일반투자(적극주주)", "cls": "tag-purpose"})
        breakdown.append({
            "strategy": "전략 3 (적극적 주주활동)",
            "reason": "단순투자가 아닌 일반투자/적극주주 목적 공시",
            "points": 2,
        })
    elif purpose_downgraded:
        factor_scores["s7_exit_risk"] -= 3
        tags.append({"text": "목적하향(이탈주의)", "cls": "tag-exit"})
        breakdown.append({
            "strategy": "전략 7 (목적 하향)",
            "reason": f"{prev_p['label']} → {curr_p['label']} 보유목적 하향",
            "points": -3,
        })
        categories.add("EXIT")

    # 실제 보유주식수 증가 및 진성 취득 여부 확인
    genuine_buy = is_genuine_share_accumulation(item)

    # [S4] 신규 5% 진입 (CB/메자닌 신규 진입 시 가점 차단)
    if item.get("is_new_entry"):
        if reason_info["is_mezzanine_or_cb"]:
            tags.append({"text": "신규5%(CB잠재주권)", "cls": "tag-mezzanine"})
            breakdown.append({
                "strategy": "전략 4 (신규 5% 예외)",
                "reason": f"전환사채(CB)/메자닌 인수에 따른 잠재주권 신규 보고로 매집 가점 제외 ({total_rt:.2f}%)",
                "points": 0,
            })
        elif genuine_buy:
            factor_scores["s4_new_entry"] += 2
            tags.append({"text": "신규 5% 진입", "cls": "tag-new"})
            breakdown.append({
                "strategy": "전략 4 (신규 5% 돌파)",
                "reason": f"실제 주식 취득을 통한 최초 5% 이상 대량보유 진입 ({total_rt:.2f}%)",
                "points": 2,
            })
            categories.add("NEW")
            if primary_category == "ALL":
                primary_category = "NEW"

    # [S2] 지분 확대 및 연속 매집 (genuineBuy 필수)
    if genuine_buy and (diff > 0 or (cnt_delta is not None and cnt_delta > 0)):
        diff_pts = 3 if diff >= 3.0 else (2 if diff >= 1.0 else 1)
        factor_scores["s2_accumulation"] += diff_pts
        tags.append({"text": f"+{diff:.2f}%p 실매집", "cls": "tag-accum"})
        breakdown.append({
            "strategy": "전략 2 (실제 주식수 확대)",
            "reason": f"실제 보유주식수 증가({item.get('stk_cnt_var') or '+'}) 및 지분율 +{diff:.2f}%p 확대",
            "points": diff_pts,
        })

        if accum_count >= 2 and not item.get("is_new_entry"):
            streak_pts = 4 if accum_count >= 3 else 3
            factor_scores["s2_accumulation"] += streak_pts
            tags.append({"text": f"★{accum_count}연속 매집", "cls": "tag-streak"})
            breakdown.append({
                "strategy": "전략 2 (연속 매집)",
                "reason": f"공식 이력 기준 {accum_count}회 연속 실제 보유주식수 증가 확인",
                "points": streak_pts,
            })
            categories.add("ACCUM")
            if primary_category == "ALL":
                primary_category = "ACCUM"
        elif diff >= 1.0 and not item.get("is_new_entry"):
            categories.add("ACCUM")
            if primary_category == "ALL":
                primary_category = "ACCUM"
    elif diff > 0 and not genuine_buy:
        if reason_info["is_mechanical_or_share_count_change_only"]:
            tags.append({"text": "자사주소각/발행수감소(0주)", "cls": "tag-passive"})
            breakdown.append({
                "strategy": "전략 2 (기계적 비율상승 제외)",
                "reason": f"보유비율은 +{diff:.2f}%p 상승했으나 보유주식수 증가 없음(발행주식총수 감소 등) → 매집 점수 0점",
                "points": 0,
            })

    # [S5] 10% 주요주주 돌파 (실제 주식 취득으로 돌파한 경우에만)
    if genuine_buy and total_rt >= 10.0 and (total_rt - diff) < 10.0 and diff > 0:
        factor_scores["s5_milestone_10pct"] += 2
        tags.append({"text": "10% 주요주주 돌파", "cls": "tag-milestone"})
        breakdown.append({
            "strategy": "전략 5 (임계 구간 돌파)",
            "reason": "실제 주식 매집으로 지분율 10% 돌파 (단기매매차익 반환 의무 감수)",
            "points": 2,
        })

    # [S6] 취득원천 검증 (사유 기반) — 원본과 동일
    if reason_info["summary_tag"] and reason_info["score_delta"] != 0:
        factor_scores["s6_price_margin"] += reason_info["score_delta"]
        tags.append({
            "text": reason_info["summary_tag"],
            "cls": "tag-openmarket" if reason_info["score_delta"] > 0 else "tag-mezzanine",
        })
        breakdown.append({
            "strategy": "전략 6 (취득원천 검증)",
            "reason": f"보고사유: {item.get('report_resn')}",
            "points": reason_info["score_delta"],
        })
    elif reason_info["summary_tag"] and reason_info["score_delta"] == 0:
        tags.append({"text": reason_info["summary_tag"], "cls": "tag-passive"})

    # [S6] 세력 평단 안전마진 — 가격 데이터가 있을 때만 원본 로직 적용.
    # 가격 모듈을 끌어오지 않으므로, 데이터가 없으면 미산출로 명시한다.
    if price_gap is not None:
        if (
            not reason_info["is_mezzanine_or_cb"]
            and (genuine_buy or curr_p["level"] >= 2)
            and (cnt_delta is None or cnt_delta >= 0)
        ):
            src_tag = " (VWAP추정)" if price_gap["is_vwap_estimate"] else ""
            if price_gap["is_deep_safety"]:
                factor_scores["s6_price_margin"] += 2
                tags.append({"text": f"★안전마진 {price_gap['gap_pct']}%{src_tag}", "cls": "tag-openmarket"})
                breakdown.append({
                    "strategy": "전략 6 (세력 평단 안전마진)",
                    "reason": (
                        f"세력 매집단가({_fmt_num(price_gap['avg'])}) 대비 "
                        f"현재가({_fmt_num(price_gap['curr'])})가 {price_gap['gap_pct']}% "
                        f"할인 구간 [{price_gap['price_source']}]"
                    ),
                    "points": 2,
                })
            elif price_gap["is_safety_margin"]:
                factor_scores["s6_price_margin"] += 1
                tags.append({"text": f"평단하회 {price_gap['gap_pct']}%{src_tag}", "cls": "tag-openmarket"})
                breakdown.append({
                    "strategy": "전략 6 (세력 평단 하회)",
                    "reason": f"세력 매집단가 대비 현재가 {price_gap['gap_pct']}% 할인 구간 [{price_gap['price_source']}]",
                    "points": 1,
                })
    elif item.get("est_avg_price") is None and item.get("current_price") is None:
        breakdown.append({
            "strategy": "전략 6 (세력 평단 안전마진)",
            "reason": "미산출(가격 데이터 필요)",
            "points": 0,
        })

    # [S7] 지분 축소 감점 (5% 이상 유지 중 축소)
    if diff <= -0.3 or (cnt_delta is not None and cnt_delta < 0):
        sell_pts = -3 if diff <= -2.0 else (-2 if diff <= -0.5 else -1)
        factor_scores["s7_exit_risk"] += sell_pts
        tags.append({"text": f"{diff:.2f}%p 축소", "cls": "tag-exit"})
        breakdown.append({
            "strategy": "전략 7 (지분 축소)",
            "reason": f"직전 보고 대비 보유주식수({item.get('stk_cnt_var') or ''}주) 및 지분율({diff:.2f}%p) 감소",
            "points": sell_pts,
        })
        if diff <= -1.0:
            categories.add("EXIT")
            if primary_category == "ALL":
                primary_category = "EXIT"

    score = sum(factor_scores.values())
    recent_accum_signal_active = (
        freshness != "STALE"
        and score > 0
        and (genuine_buy or purpose_upgraded or curr_p["level"] >= 2)
    )

    return {
        "score": score,
        "factor_scores": factor_scores,
        "tags": tags,
        "breakdown": breakdown,
        "category": primary_category,
        "categories": sorted(categories),
        "investor": investor,
        "curr_purpose_normalized": curr_p["label"],
        "price_gap": price_gap,
        "ownership_freshness": freshness,
        "recent_accumulation_signal_active": recent_accum_signal_active,
    }


# ----------------------------------------------------------------------
# 정정공시 중복 제거 (원본 deduplicateFilingAmendments)
# ----------------------------------------------------------------------
def deduplicate_filing_amendments(sorted_rows: list[dict]) -> list[dict]:
    """동일 이벤트의 원본+[기재정정] 보고서를 최신 정정본 하나로 병합."""
    if not sorted_rows or len(sorted_rows) <= 1:
        return list(sorted_rows or [])
    result: list[dict] = []

    for row in sorted_rows:
        is_amend = bool(
            re.search(r"기재정정|정정", str(row.get("report_nm") or ""))
            or row.get("is_amendment")
        )
        curr_cnt = _row_count(row, "stkqy", "hold_stock_cnt")
        curr_rt = _row_ratio(row)
        curr_event_dt = row.get("event_dt") or row.get("oblig_dt") or ""

        if result:
            prev = result[-1]
            prev_cnt = _row_count(prev, "stkqy", "hold_stock_cnt")
            prev_rt = _row_ratio(prev)
            prev_event_dt = prev.get("event_dt") or prev.get("oblig_dt") or ""

            same_event_date = bool(
                curr_event_dt and prev_event_dt and curr_event_dt == prev_event_dt
            )
            same_holdings_amendment = bool(
                is_amend
                and prev_cnt is not None
                and curr_cnt is not None
                and prev_cnt == curr_cnt
                and abs(prev_rt - curr_rt) < 0.05
            )
            same_day_correction = bool(
                is_amend
                and format_date_str(prev.get("rcept_dt")) == format_date_str(row.get("rcept_dt"))
                and prev_cnt is not None
                and curr_cnt is not None
                and prev_cnt == curr_cnt
            )

            if same_event_date or same_holdings_amendment or same_day_correction:
                merged = dict(prev)
                merged.update(row)
                merged["original_rcept_dt"] = prev.get("original_rcept_dt") or prev.get("rcept_dt")
                merged["original_rcept_no"] = prev.get("original_rcept_no") or prev.get("rcept_no")
                result[-1] = merged
                continue
        result.append(row)

    return result


# ----------------------------------------------------------------------
# majorstock 시계열 처리 (원본 processMajorstockHistory)
# ----------------------------------------------------------------------
def extract_purpose_from_reason(report_resn: Any = "", report_nm: Any = "") -> str:
    combined = f"{report_resn or ''} {report_nm or ''}"
    if "경영권" in combined or "경영참여" in combined or "임원" in combined:
        return "경영권 영향"
    if "일반투자" in combined or "(일반)" in combined:
        return "일반투자"
    return "단순투자"


def process_majorstock_history(
    raw_rows: list[dict],
    custom_dict: Optional[dict] = None,
    min_rcept_date: Optional[str] = None,
    reference_date: Any = None,
) -> list[dict]:
    """majorstock.json 행들을 (종목, 보고자)별로 처리해 최신 공시만 반환.

    각 반환 항목은 원본 normalizedItem과 같은 필드를 가지며, 최신 항목에는
    전체 이력(`history`)과 평가 결과(`eval`)가 붙는다.
    """
    groups: dict[str, list[dict]] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        key = f"{row.get('corp_code') or row.get('corp_name')}__{str(row.get('repror') or row.get('rpror_nm') or '').strip()}"
        groups.setdefault(key, []).append(row)

    enriched_latest: list[dict] = []
    clean_min_date = (
        re.sub(r"[^0-9]", "", str(min_rcept_date)) if min_rcept_date else None
    )

    for raw_group_rows in groups.values():
        def _sort_key(r: dict) -> tuple[str, str]:
            return (
                re.sub(r"[^0-9]", "", str(r.get("rcept_dt") or "")),
                str(r.get("rcept_no") or ""),
            )

        sorted_rows = sorted(raw_group_rows, key=_sort_key)
        rows = deduplicate_filing_amendments(sorted_rows)
        if not rows:
            continue

        latest_row = rows[-1]
        latest_dt_clean = re.sub(r"[^0-9]", "", str(latest_row.get("rcept_dt") or ""))
        if clean_min_date and latest_dt_clean and latest_dt_clean < clean_min_date:
            continue

        accum_streak = 0
        history_timeline: list[dict] = []
        first5_row = next(
            (
                r for r in rows
                if _row_ratio(r) >= 5.0
            ),
            rows[0],
        )
        first_entry_dt = format_date_str(
            first5_row.get("original_rcept_dt") or first5_row.get("rcept_dt")
        )

        for i, curr in enumerate(rows):
            prev = rows[i - 1] if i > 0 else None

            curr_rt = _row_ratio(curr)
            prev_rt = _row_ratio(prev) if prev else None

            raw_rt_var = curr.get("stkrt_irds")
            if raw_rt_var not in (None, "", "-"):
                rt_var = _parse_float(raw_rt_var, 0.0)
            elif prev_rt is not None:
                rt_var = round(curr_rt - prev_rt, 2)
            else:
                rt_var = curr_rt

            curr_cnt = _row_count(curr, "stkqy", "hold_stock_cnt")
            prev_cnt = _row_count(prev, "stkqy", "hold_stock_cnt") if prev else None
            cnt_var = _row_count(curr, "stkqy_irds", "stk_cnt_var")
            if cnt_var is None and curr_cnt is not None and prev_cnt is not None:
                cnt_var = curr_cnt - prev_cnt

            if curr.get("is_new_entry") is not None:
                is_new_entry = bool(curr.get("is_new_entry"))
            else:
                is_new_entry = (prev is None and curr_rt >= 5.0) or (
                    prev_rt is not None and prev_rt < 5.0 and curr_rt >= 5.0
                )

            genuine_accum = is_genuine_share_accumulation(
                {
                    **curr,
                    "stkqy": curr_cnt,
                    "stkqy_irds": cnt_var,
                    "stkrt_irds": rt_var,
                },
                {**prev, "stkqy": prev_cnt} if prev else None,
            )

            if genuine_accum:
                accum_streak += 1
            elif (cnt_var is not None and cnt_var < 0) or rt_var < 0 or curr_rt < 5.0:
                accum_streak = 0

            effective_accum_count = accum_streak if genuine_accum else 0

            curr_purpose = curr.get("curr_purpose") or extract_purpose_from_reason(
                curr.get("report_resn"), curr.get("report_nm")
            )
            if curr.get("prev_purpose") is not None:
                prev_purpose = curr.get("prev_purpose")
            elif prev:
                prev_purpose = prev.get("curr_purpose") or extract_purpose_from_reason(
                    prev.get("report_resn"), prev.get("report_nm")
                )
            else:
                prev_purpose = None

            formatted_cnt = (
                _fmt_num(curr_cnt)
                if curr_cnt is not None
                else str(curr.get("stkqy") or curr.get("hold_stock_cnt") or "-")
            )
            formatted_cnt_var = (
                _fmt_signed_count(cnt_var)
                if cnt_var is not None
                else str(curr.get("stkqy_irds") or curr.get("stk_cnt_var") or "-")
            )

            normalized_item = {
                "market": curr.get("market") or "KR",
                "rcept_no": curr.get("rcept_no"),
                "rcept_dt": format_date_str(curr.get("rcept_dt")),
                "prev_rcept_dt": format_date_str(prev.get("rcept_dt")) if prev else None,
                "first_entry_dt": curr.get("first_entry_dt") or first_entry_dt,
                "corp_code": curr.get("corp_code") or "",
                "corp_name": curr.get("corp_name") or "",
                "stock_code": curr.get("stock_code") or "",
                "rpror_nm": str(curr.get("repror") or curr.get("rpror_nm") or "").strip(),
                "hold_stock_cnt": formatted_cnt,
                "stk_cnt_var": formatted_cnt_var,
                "hold_stock_rt": curr_rt,
                "stk_rt_var": rt_var,
                "curr_purpose": curr_purpose,
                "prev_purpose": prev_purpose,
                "report_resn": curr.get("report_resn") or "",
                "report_nm": curr.get("report_nm") or "주식등의대량보유상황보고서",
                "is_new_entry": is_new_entry,
                "accum_count": (
                    curr.get("accum_count")
                    if curr.get("accum_count") is not None
                    else effective_accum_count
                ),
                "est_avg_price": curr.get("est_avg_price"),
                "price_source": (
                    normalize_price_source_prefix(curr.get("price_source"))
                    if curr.get("price_source")
                    else None
                ),
                "current_price": curr.get("current_price"),
                "ownership_freshness": curr.get("ownership_freshness")
                or compute_ownership_freshness(curr.get("rcept_dt"), reference_date),
            }

            history_timeline.append({
                "rcept_dt": normalized_item["rcept_dt"],
                "rcept_no": normalized_item["rcept_no"],
                "hold_stock_cnt": normalized_item["hold_stock_cnt"],
                "stk_cnt_var": normalized_item["stk_cnt_var"],
                "hold_stock_rt": normalized_item["hold_stock_rt"],
                "stk_rt_var": normalized_item["stk_rt_var"],
                "curr_purpose": normalized_item["curr_purpose"],
                "report_resn": normalized_item["report_resn"],
            })

            if i == len(rows) - 1:
                normalized_item["history"] = list(reversed(history_timeline))
                normalized_item["eval"] = evaluate_signal_score(
                    normalized_item, custom_dict, reference_date
                )
                enriched_latest.append(normalized_item)

    return enriched_latest
