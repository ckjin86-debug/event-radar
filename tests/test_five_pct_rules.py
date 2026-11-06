"""Tests for the ported DART 5% Super Radar rules (five_pct_rules).

The golden cases are the original system's own verified backtest
exports (5pct_super_radar_backtest.csv + ai_report.md) from the user's
integrated investment package: all 24 KR rows must reproduce the exact
S1~S7 factor scores and total alpha score the original rules.js
produced. The CSV carries the reporter's average acquisition price and
the current price, so the price half of S6 is exercised here too; in
production collection (no price data) S6's margin component is recorded
as "미산출(가격 데이터 필요)" instead — see
test_evaluate_without_price_data_marks_s6_not_computed.
"""

import csv
import re
from pathlib import Path

import pytest

from event_radar.five_pct_rules import (
    analyze_report_reason,
    classify_investor,
    compute_ownership_freshness,
    deduplicate_filing_amendments,
    evaluate_signal_score,
    normalize_purpose,
    process_majorstock_history,
)

EXPORTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "original-package"
    / "extracted"
    / "BB_통합투자시스템_집컴퓨터_이사패키지_20261102"
    / "dart-5pct-super-radar"
    / "exports"
)

FACTOR_KEYS = [
    "s1_investor",
    "s2_accumulation",
    "s3_purpose",
    "s4_new_entry",
    "s5_milestone_10pct",
    "s6_price_margin",
    "s7_exit_risk",
]
CSV_FACTOR_COLUMNS = [
    "S1_주체가중치",
    "S2_연속매집",
    "S3_목적변경",
    "S4_신규5%",
    "S5_10%돌파",
    "S6_단가안전마진",
    "S7_이탈감점",
]


def _num(value) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _load_golden_cases() -> list[dict]:
    csv_path = EXPORTS_DIR / "5pct_super_radar_backtest.csv"
    report_path = EXPORTS_DIR / "5pct_super_radar_ai_report.md"
    if not csv_path.exists() or not report_path.exists():
        return []

    # The CSV has no share-count-delta column; the AI report's matrix
    # carries it inside the 지분율 cell ("+0.03%p, +1,442주, 23회").
    cnt_var_by_key: dict[tuple[str, str], str | None] = {}
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| **"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name_match = re.match(r"(.+?) \((\d+)\)", cells[1])
        if not name_match:
            continue  # US rows: SEC path is out of scope for this port.
        reporter = cells[2].split(" (")[0]
        delta_match = re.search(
            r"\(([+-]?[\d.]+)%p, ([+-]?[\d,]+)주, (\d+)회\)", cells[4]
        )
        cnt_var_by_key[(name_match.group(1), reporter)] = (
            delta_match.group(2) if delta_match else None
        )

    cases = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["마켓"] != "KR":
                continue
            key = (row["종목명"], row["보고자"])
            item = {
                "rpror_nm": row["보고자"],
                "hold_stock_rt": _num(row["보유비율(%)"]),
                "stk_rt_var": _num(row["변동폭(%p)"]),
                "stk_cnt_var": cnt_var_by_key.get(key),
                "accum_count": int(_num(row["연속매집횟수"])),
                "curr_purpose": row["현재목적"],
                "prev_purpose": None if row["직전목적"] == "-" else row["직전목적"],
                "report_nm": "주식등의대량보유상황보고서",
                "report_resn": row["보고사유"],
                "is_new_entry": row["직전목적"] == "-",
                "est_avg_price": _num(row["세력매집단가"]) or None,
                "current_price": _num(row["현재가"]) or None,
                "price_source": row["단가산출근거"],
                "rcept_dt": row["①신규접수일"],
                "ownership_freshness": "CURRENT",
            }
            cases.append({
                "id": f"{row['종목명']}-{row['보고자']}",
                "item": item,
                "expected_factors": [int(_num(row[c])) for c in CSV_FACTOR_COLUMNS],
                "expected_total": int(_num(row["총알파스코어"])),
                "expected_investor_label": row["주체분류"],
            })
    return cases


GOLDEN_CASES = _load_golden_cases()


@pytest.mark.skipif(not GOLDEN_CASES, reason="original package exports not present")
@pytest.mark.parametrize(
    "case", GOLDEN_CASES, ids=[c["id"] for c in GOLDEN_CASES]
)
def test_golden_backtest_rows_reproduce_original_scores(case):
    result = evaluate_signal_score(case["item"])

    assert [result["factor_scores"][k] for k in FACTOR_KEYS] == case["expected_factors"]
    assert result["score"] == case["expected_total"]
    assert result["investor"]["label"] == case["expected_investor_label"]


@pytest.mark.skipif(not GOLDEN_CASES, reason="original package exports not present")
def test_golden_case_count_is_complete():
    # 24 KR rows in the original verified dataset (5 US rows excluded:
    # the SEC ingestion path was not ported).
    assert len(GOLDEN_CASES) == 24


# ----------------------------------------------------------------------
# Unit tests for the individual ported rules
# ----------------------------------------------------------------------

def test_normalize_purpose_levels():
    assert normalize_purpose("경영권 영향") == {"label": "경영권 영향 (13D)", "level": 3}
    assert normalize_purpose("일반투자")["level"] == 2
    assert normalize_purpose("단순투자")["level"] == 1
    assert normalize_purpose("", "주식등의대량보유상황보고서(일반)")["level"] == 2
    assert normalize_purpose("", "주식등의대량보유상황보고서(약식)")["level"] == 1


def test_classify_investor_dictionary_and_individual():
    assert classify_investor("국민연금공단")["type"] == "PASSIVE"
    assert classify_investor("얼라인파트너스자산운용 주식회사")["base_score"] == 4
    assert classify_investor("베어링자산운용주식회사")["label"] == "가치투자/구루"
    assert classify_investor("동국홀딩스")["label"] == "PEF/투자조합"
    assert classify_investor("석창규") == {
        "type": "SUPER_ANT",
        "label": "슈퍼개미/개인",
        "base_score": 2,
        "badge_class": "tag-ant",
    }
    assert classify_investor("미래에셋자산운용")["type"] == "GENERAL"
    # 사전의 '홀딩스' 키워드가 개인 판정보다 먼저 적용된다 (원본 순서).
    assert classify_investor("김홀딩스")["type"] == "PEF_SI"


def test_analyze_report_reason_variants():
    cb = analyze_report_reason("제27회차 전환사채 인수계약에 따른 신규보고", 939_849, 11.1)
    assert cb["is_mezzanine_or_cb"] is True
    assert cb["score_delta"] == -2

    buy = analyze_report_reason("장내매수로 인한 보유주식수 증가", 10_000, 0.5)
    assert buy["is_open_market_buy"] is True
    assert buy["score_delta"] == 2

    zero = analyze_report_reason("주식담보대출 계약의 변경", 0, 0.0)
    assert zero["is_internal_or_contract_only"] is True
    assert zero["score_delta"] == 0

    block = analyze_report_reason("주식양수도 계약체결에 따른 신규보고", 1_700_000, 15.09)
    assert block["is_block_deal_or_otc"] is True
    assert block["score_delta"] == 1


def test_freshness_boundaries():
    ref = "2026-11-02"
    assert compute_ownership_freshness("2026-11-02", ref) == "CURRENT"
    assert compute_ownership_freshness("2026-10-03", ref) == "CURRENT"  # 30일
    assert compute_ownership_freshness("2026-10-02", ref) == "RECENT"  # 31일
    assert compute_ownership_freshness("2026-08-04", ref) == "RECENT"  # 90일
    assert compute_ownership_freshness("2026-08-03", ref) == "AGING"  # 91일
    assert compute_ownership_freshness("2026-05-06", ref) == "AGING"  # 180일
    assert compute_ownership_freshness("2026-05-05", ref) == "STALE"  # 181일


def test_evaluate_without_price_data_marks_s6_not_computed():
    item = {
        "rpror_nm": "홍길동",
        "hold_stock_rt": 6.0,
        "stk_rt_var": 1.2,
        "stk_cnt_var": "+120,000",
        "accum_count": 1,
        "curr_purpose": "단순투자",
        "prev_purpose": "단순투자",
        "report_nm": "주식등의대량보유상황보고서",
        "report_resn": "장내매수에 따른 보유주식수 증가",
        "is_new_entry": False,
        "rcept_dt": "2026-11-02",
    }
    result = evaluate_signal_score(item, reference_date="2026-11-02")

    # S6는 사유 기반 장내매수 +2만 반영되고, 평단 안전마진은 미산출로 명시.
    assert result["factor_scores"]["s6_price_margin"] == 2
    assert result["price_gap"] is None
    assert any(
        entry["reason"] == "미산출(가격 데이터 필요)" and entry["points"] == 0
        for entry in result["breakdown"]
    )


def test_evaluate_below_five_pct_exit_takes_priority():
    # 원본 검증 행 (로보스타/미래에셋자산운용): 5% 미만 이탈 -7점.
    item = {
        "rpror_nm": "미래에셋자산운용",
        "hold_stock_rt": 4.76,
        "stk_rt_var": -1.5,
        "stk_cnt_var": "-146,140",
        "accum_count": 0,
        "curr_purpose": "단순투자",
        "prev_purpose": "단순투자",
        "report_nm": "주식등의대량보유상황보고서",
        "report_resn": "지분율 변동",
        "is_new_entry": False,
        "rcept_dt": "2026-11-02",
    }
    result = evaluate_signal_score(item, reference_date="2026-11-02")

    assert result["score"] == -7
    assert result["factor_scores"]["s7_exit_risk"] == -7
    assert result["category"] == "EXIT"


def test_deduplicate_filing_amendments_merges_same_day_correction():
    rows = [
        {"rcept_no": "1", "rcept_dt": "20261102", "stkqy": "600,000", "stkrt": "6.00",
         "report_nm": "주식등의대량보유상황보고서(일반)"},
        {"rcept_no": "2", "rcept_dt": "20261102", "stkqy": "600,000", "stkrt": "6.00",
         "report_nm": "[기재정정]주식등의대량보유상황보고서(일반)"},
        {"rcept_no": "3", "rcept_dt": "20261120", "stkqy": "650,000", "stkrt": "6.50",
         "report_nm": "주식등의대량보유상황보고서(일반)"},
    ]
    merged = deduplicate_filing_amendments(rows)

    assert len(merged) == 2
    assert merged[0]["rcept_no"] == "2"
    assert merged[0]["original_rcept_no"] == "1"
    assert merged[1]["rcept_no"] == "3"


def test_process_majorstock_history_streak_reset_and_first_entry():
    rows = [
        {"rcept_no": "1", "rcept_dt": "20260105", "corp_code": "00000001",
         "corp_name": "테스트", "repror": "홍길동",
         "stkqy": "500,000", "stkqy_irds": "500,000", "stkrt": "5.00",
         "stkrt_irds": "5.00", "report_resn": "장내매수 신규보고"},
        {"rcept_no": "2", "rcept_dt": "20260205", "corp_code": "00000001",
         "corp_name": "테스트", "repror": "홍길동",
         "stkqy": "600,000", "stkqy_irds": "100,000", "stkrt": "6.00",
         "stkrt_irds": "1.00", "report_resn": "장내매수"},
        {"rcept_no": "3", "rcept_dt": "20260305", "corp_code": "00000001",
         "corp_name": "테스트", "repror": "홍길동",
         "stkqy": "550,000", "stkqy_irds": "-50,000", "stkrt": "5.50",
         "stkrt_irds": "-0.50", "report_resn": "장내매도"},
        {"rcept_no": "4", "rcept_dt": "20260405", "corp_code": "00000001",
         "corp_name": "테스트", "repror": "홍길동",
         "stkqy": "700,000", "stkqy_irds": "150,000", "stkrt": "7.00",
         "stkrt_irds": "1.50", "report_resn": "장내매수"},
    ]
    processed = process_majorstock_history(rows, reference_date="2026-04-10")

    assert len(processed) == 1
    latest = processed[0]
    # 매도(3번)에서 스트릭이 초기화되어 최신 연속매집은 1회.
    assert latest["accum_count"] == 1
    assert latest["first_entry_dt"] == "2026-01-05"
    assert latest["prev_purpose"] == "단순투자"
    assert latest["rcept_no"] == "4"
    assert len(latest["history"]) == 4
    assert latest["eval"]["investor"]["type"] == "SUPER_ANT"
