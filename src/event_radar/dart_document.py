"""DART 공시 원문 파서 — DISCLOSED 세력평단 (Priority 1).

Port of the original "DART 5% Super Radar" extension's
``parseDartReportDetail(rceptNo, 'KR')`` (background.js):

1. ``dsaf001/main.do`` 페이지에서 ``viewDoc(...)`` 파라미터를 최대 6개까지
   뽑아 ``report/viewer.do`` 문서들을 순서대로 가져와 하나의 HTML로 합친다.
2. 합쳐진 HTML의 모든 ``<tr>``/``<td>`` 셀을 순회하며
   - 요약표에서 보유목적·보유주식수·보유비율·변동사유를 추출하고,
   - '2. 세부변동내역' 표에서 매수 행의 (증감 주식수 × 취득/처분단가)를
     모아 수량가중평균 단가(DISCLOSED)를 산출한다.

원본의 셀 인덱스 규칙(세부변동내역 10열 구조, 매수 방법 정규식, 단가
범위 가드 100~10,000,000원)을 그대로 따른다. 네트워크는 주입 가능한
``fetch_text`` 콜백 뒤에 숨겨 두어 오프라인/픽스처 테스트가 가능하고,
실패는 예외가 아니라 ``ok=False`` 결과로 graceful 하게 처리한다
(개별 뷰어 문서의 실패는 원본과 동일하게 건너뛴다).

사이트 개편 대응: 현재 main.do는 리터럴 viewDoc('...') 호출 대신
목차를 ``nodeN['rcpNo'] = "..."`` 형태의 JS 할당으로 심어 둔다. 절차
(main.do → 파라미터 추출 → viewer.do 결합 → 행 파싱)는 원본과 같고,
파라미터 추출만 두 형식을 모두 지원한다. 단, 현행 목차는 장(章) 단위로
잘게 나뉘어 세부변동내역이 6번째보다 뒤에 오는 경우가 실측으로
확인되어, node 형식에서는 앞 6개 제한을 두지 않는다(상한 30).
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional

import requests

from event_radar.five_pct_rules import parse_numeric_share_count


DART_MAIN_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
DART_VIEWER_URL = (
    "https://dart.fss.or.kr/report/viewer.do?rcpNo={rcp}&dcmNo={dcm}"
    "&eleId={ele}&offset={offset}&length={length}&dtd={dtd}"
)
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EventRadar/1.0"

# 원본: matches.slice(0, 6) — main.do의 viewDoc 문서 중 앞 6개만 결합한다.
MAX_VIEWER_DOCUMENTS = 6
# 현행 node 형식 목차의 안전 상한 (대량보유 보고서는 통상 15개 안팎).
MAX_NODE_DOCUMENTS = 30

_VIEWDOC_RE = re.compile(
    r"viewDoc\s*\(\s*['\"](\d+)['\"]\s*,\s*['\"](\d+)['\"]\s*,"
    r"\s*['\"](\d+)['\"]\s*,\s*['\"](\d+)['\"]\s*,\s*['\"](\d+)['\"]\s*,"
    r"\s*['\"]([^'\"]+)['\"]\s*\)"
)
# 현행 main.do 목차: nodeN['rcpNo'] = "..."; nodeN['dcmNo'] = "..."; ...
# 같은 node 변수의 연속 할당을 하나의 문서 파라미터로 묶는다.
_NODE_RE = re.compile(
    r"(node\d+)\['rcpNo'\]\s*=\s*\"(\d+)\";\s*"
    r"\1\['dcmNo'\]\s*=\s*\"(\d+)\";\s*"
    r"\1\['eleId'\]\s*=\s*\"(\d+)\";\s*"
    r"\1\['offset'\]\s*=\s*\"(\d+)\";\s*"
    r"\1\['length'\]\s*=\s*\"(\d+)\";\s*"
    r"\1\['dtd'\]\s*=\s*\"([^\"]+)\""
)
_TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
_TD_RE = re.compile(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# 세부변동내역 행 판별: 변동일 셀이 날짜인가.
# 원본 정규식은 YYYY.MM.DD / YYYY-MM-DD / YYYY/MM/DD만 허용했지만, 현행
# 공시 원문은 "2026년 07월 07일" 표기도 혼재해 실측에서 매수 행이 통째로
# 누락됨이 확인되어 같은 날짜의 한글 표기를 함께 허용한다.
_DATE_CELL_RE = re.compile(
    r"^\d{4}(?:[.\-/]\d{2}[.\-/]\d{2}|년\s*\d{1,2}월\s*\d{1,2}일)"
)
# 원본 매수 방법 정규식. '처분'/'매도' 포함 시 별도로 제외한다.
_BUY_METHOD_RE = re.compile(r"(?:장내매수|장외매수|시간외매수|유상증자|신주인수권|취득|매수)")
_FLOAT_PREFIX_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)")

UNIT_PRICE_MIN = 100
UNIT_PRICE_MAX = 10_000_000

FetchText = Callable[[str], Optional[str]]


def _cell_text(raw_html: str) -> str:
    """원본 셀 텍스트 정규화: 태그→공백, &nbsp;→공백, 공백 축소, trim."""
    text = _TAG_RE.sub(" ", raw_html)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _js_parse_float(text: Any) -> Optional[float]:
    """JS parseFloat 근사: 선행 숫자 접두사만 읽고, 없으면 None(NaN)."""
    if text is None:
        return None
    match = _FLOAT_PREFIX_RE.match(str(text).strip())
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _js_int_from_digits(text: Any, strip_parens: bool = False) -> Optional[int]:
    """원본의 '숫자만 남기고 parseInt' 근사. 숫자가 없으면 None(NaN)."""
    cleaned = str(text or "")
    if strip_parens:
        cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    digits = re.sub(r"[^0-9]", "", cleaned)
    if not digits:
        return None
    return int(digits)


def _js_round(value: float) -> int:
    """JS Math.round (양수 기준 half-up)."""
    return int(math.floor(value + 0.5))


def _fmt_locale_number(value: Any) -> str:
    """JS Number.toLocaleString() 근사: 천 단위 콤마, 소수 최대 3자리."""
    num = float(value)
    if num == int(num) and abs(num) < 1e15:
        return f"{int(num):,}"
    return f"{num:,.3f}".rstrip("0").rstrip(".")


def parse_dart_document_html(combined_html: str) -> dict:
    """결합된 뷰어 HTML에서 요약 정보와 DISCLOSED 가중평균 단가를 추출한다.

    원본 parseDartReportDetail의 행 순회 규칙을 그대로 재현한다
    (prev_purpose는 원본에서도 끝내 설정되지 않아 항상 None이다).
    """
    curr_purpose: Optional[str] = None
    report_resn: Optional[str] = None
    hold_stock_rt: Optional[float] = None
    stk_rt_var: Optional[float] = None
    hold_stock_cnt: Optional[str] = None
    stk_cnt_var: Optional[str] = None

    total_cost = 0
    total_shares = 0
    extracted_prices: list[str] = []

    for tr_match in _TR_RE.finditer(combined_html or ""):
        cells = [_cell_text(m) for m in _TD_RE.findall(tr_match.group(1))]
        if not cells:
            continue
        first = cells[0]

        # A) 보유목적 및 변동사유 행 추출
        if "보유목적" in first and len(cells) >= 2:
            p_txt = cells[-1]
            if "경영권" in p_txt or "경영참여" in p_txt:
                curr_purpose = "경영권 영향"
            elif "일반투자" in p_txt:
                curr_purpose = "일반투자"
            elif "단순투자" in p_txt:
                curr_purpose = "단순투자"
        if (
            "변동사유" in first or "변경사유" in first or "보고사유" in first
        ) and len(cells) >= 2:
            report_resn = cells[-1]

        # B) 직전/이번/증감 요약 행 추출 ([구분, 보고사유발생일, 주식수, 비율, ...])
        compact_first = re.sub(r"\s+", "", first)
        if compact_first == "이번보고서" and len(cells) >= 4:
            cnt_val = parse_numeric_share_count(cells[2])
            rt_val = _js_parse_float(cells[3])
            if cnt_val is not None:
                hold_stock_cnt = _fmt_locale_number(cnt_val)
            if rt_val is not None:
                hold_stock_rt = rt_val
        if compact_first == "직전보고서" and len(cells) >= 4:
            prev_rt = _js_parse_float(cells[3])
            if prev_rt is not None and hold_stock_rt is not None:
                stk_rt_var = round(hold_stock_rt - prev_rt, 2)
        if compact_first == "증감" and len(cells) >= 4:
            diff_cnt = parse_numeric_share_count(cells[2])
            diff_rt = _js_parse_float(cells[3])
            if diff_cnt is not None:
                stk_cnt_var = _fmt_locale_number(diff_cnt)
            if diff_rt is not None:
                stk_rt_var = diff_rt

        # C) Priority 1 (DISCLOSED): '2. 세부변동내역' 표 행 추출
        # 표준 컬럼 구조 (10열): [0:성명, 1:생년월일, 2:변동일, 3:취득/처분방법,
        # 4:주식종류, 5:변동전, 6:증감, 7:변동후, 8:취득/처분단가, 9:비고]
        if len(cells) >= 9 and _DATE_CELL_RE.match(cells[2]):
            method = cells[3] or ""
            is_buy_method = (
                bool(_BUY_METHOD_RE.search(method))
                and "처분" not in method
                and "매도" not in method
            )
            qty_raw = cells[6] or ""
            price_raw = cells[8] or ""

            is_negative_qty = "-" in qty_raw or "(" in qty_raw
            qty_num = _js_int_from_digits(qty_raw)
            unit_price = _js_int_from_digits(price_raw, strip_parens=True)

            if (
                is_buy_method
                and not is_negative_qty
                and qty_num is not None
                and qty_num > 0
                and unit_price is not None
                and UNIT_PRICE_MIN <= unit_price <= UNIT_PRICE_MAX
            ):
                total_cost += qty_num * unit_price
                total_shares += qty_num
                formatted_price = f"{unit_price:,}원"
                if formatted_price not in extracted_prices:
                    extracted_prices.append(formatted_price)

    weighted_avg_price: Optional[int] = None
    price_source: Optional[str] = None
    if total_shares > 0 and total_cost > 0:
        weighted_avg_price = _js_round(total_cost / total_shares)
        price_source = (
            "DISCLOSED: 원문 제3부 세부변동내역 가중평균"
            f"({_fmt_locale_number(total_shares)}주)"
        )
        extracted_prices.insert(0, f"{weighted_avg_price:,}원 (수량가중평균)")

    return {
        "curr_purpose": curr_purpose,
        "prev_purpose": None,
        "report_resn": report_resn,
        "hold_stock_rt": hold_stock_rt,
        "stk_rt_var": stk_rt_var,
        "hold_stock_cnt": hold_stock_cnt,
        "stk_cnt_var": stk_cnt_var,
        "weighted_avg_price": weighted_avg_price,
        "price_source": price_source,
        "unit_prices": extracted_prices[:6],
        "total_shares": total_shares,
        "total_cost": total_cost,
    }


def _extract_viewer_params(main_html: str) -> list[tuple]:
    """main.do HTML에서 viewer.do 파라미터 (rcp, dcm, ele, offset, length, dtd) 목록.

    원본 형식(리터럴 viewDoc 호출)이 있으면 원본 규칙대로 앞 6개만,
    현행 node 할당 형식이면 목차 전체(상한 30)를 문서 순서대로 반환한다.
    node 형식의 목차는 장(章) 문서가 하위 절 문서를 범위로 포함하는
    중첩 구조라, 이미 선택된 범위에 완전히 포함되는 문서는 건너뛴다
    (같은 표가 두 번 결합되어 가중평균이 왜곡되는 것을 막는다).
    """
    legacy = _VIEWDOC_RE.findall(main_html)
    if legacy:
        return legacy[:MAX_VIEWER_DOCUMENTS]

    params: list[tuple] = []
    selected_ranges: list[tuple[int, int]] = []
    for _node, rcp, dcm, ele, offset, length, dtd in _NODE_RE.findall(main_html):
        try:
            start = int(offset)
            end = start + int(length)
        except ValueError:
            start = end = -1
        if start >= 0 and any(
            sel_start <= start and end <= sel_end
            for sel_start, sel_end in selected_ranges
        ):
            continue
        if start >= 0:
            selected_ranges.append((start, end))
        params.append((rcp, dcm, ele, offset, length, dtd))
        if len(params) >= MAX_NODE_DOCUMENTS:
            break
    return params


def _default_fetch_text(
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> FetchText:
    """requests 기반 기본 fetch_text. 실패 시 None (예외를 던지지 않는다)."""
    if session is not None:
        sess = session
    else:
        sess = requests.Session()
        sess.headers.update({"User-Agent": DEFAULT_USER_AGENT})

    def _fetch(url: str) -> Optional[str]:
        try:
            resp = sess.get(url, timeout=timeout)
            if getattr(resp, "status_code", None) != 200:
                return None
            encoding = getattr(resp, "encoding", None)
            if encoding and str(encoding).upper().replace("-", "") in {
                "ISO88591",
                "ISO8859",
            }:
                # DART 뷰어는 한글 페이지인데 charset이 빠지면 requests가
                # ISO-8859-1로 기본 처리해 한글이 깨진다.
                try:
                    resp.encoding = (
                        getattr(resp, "apparent_encoding", None) or "utf-8"
                    )
                except Exception:
                    pass
            text = resp.text
            return text if isinstance(text, str) else None
        except Exception:
            return None

    return _fetch


def parse_dart_report_detail(
    rcept_no: Any,
    fetch_text: Optional[FetchText] = None,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> dict:
    """공시 원문(main.do → viewer.do)을 파싱해 DISCLOSED 단가 등을 반환한다.

    반환 dict: {ok, weighted_avg_price, price_source, unit_prices,
    total_shares, total_cost, curr_purpose, prev_purpose, report_resn,
    hold_stock_rt, stk_rt_var, hold_stock_cnt, stk_cnt_var, viewer_url}.
    main.do를 가져오지 못하면 ok=False (나머지 필드는 빈 값).
    """
    rcept_no = str(rcept_no or "").strip()
    main_url = DART_MAIN_URL.format(rcept_no=rcept_no)
    result: dict = {
        "ok": False,
        "curr_purpose": None,
        "prev_purpose": None,
        "report_resn": None,
        "hold_stock_rt": None,
        "stk_rt_var": None,
        "hold_stock_cnt": None,
        "stk_cnt_var": None,
        "weighted_avg_price": None,
        "price_source": None,
        "unit_prices": [],
        "total_shares": 0,
        "total_cost": 0,
        "viewer_url": main_url,
    }
    if not rcept_no:
        return result

    if fetch_text is None:
        fetch_text = _default_fetch_text(session=session, timeout=timeout)

    try:
        main_html = fetch_text(main_url)
    except Exception:
        main_html = None
    if not main_html:
        return result

    combined_html = ""
    for rcp, dcm, ele, offset, length, dtd in _extract_viewer_params(main_html):
        viewer_url = DART_VIEWER_URL.format(
            rcp=rcp, dcm=dcm, ele=ele, offset=offset, length=length, dtd=dtd
        )
        try:
            viewer_html = fetch_text(viewer_url)
        except Exception:
            # 원본과 동일: 개별 문서 실패는 건너뛰고 나머지를 결합한다.
            viewer_html = None
        if viewer_html:
            combined_html += "\n" + viewer_html

    result.update(parse_dart_document_html(combined_html))
    result["ok"] = True
    result["viewer_url"] = main_url
    return result
