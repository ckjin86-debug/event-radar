"""News data-quality guards: dedupe, primary anchoring, classification, dates.

Covers the 2026-11-07 quality pass over NEWS_FUTURE output:
- duplicate stories about one schedule collapse into a single event;
- the primary stock is anchored from the strongest A-grade relation;
- evaluation/award/promo headlines and contract-period dates no longer
  become scheduled catalysts (the Samsung Bio ESG regressions);
- imprecise far-future windows are flagged in the export instead of
  looking like exact imminent dates.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from event_radar.collectors.news_future import (
    extract_future_catalyst,
    is_news_digest,
    is_non_event_headline,
)
from event_radar.export import export_site_data
from event_radar.models import Event, EventSecurity
from event_radar.news_dedupe import merge_duplicate_news_events
from event_radar.pipeline import promote_primary_from_relations


NOW = datetime(2026, 11, 7, 9, 0, 0)
REF = date(2026, 11, 6)


def _news(
    event_id: str,
    *,
    event_type: str = "CAPEX",
    company: str = "테스트기업",
    event_name: str = "테스트기업 신규 공장 착공 예정",
    event_date: date = date(2027, 3, 1),
    precision: str = "MONTH",
    window_start: date | None = None,
    window_end: date | None = None,
    ticker: str = "",
    evidence: str | None = None,
    ingest_mode: str = "AUTO",
    needs_review: bool = False,
) -> Event:
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=event_name,
        primary_ticker=ticker,
        primary_company=company,
        announced_at=NOW,
        event_date=event_date,
        date_precision=precision,
        window_start=window_start if window_start is not None else event_date,
        window_end=window_end if window_end is not None else event_date,
        event_time_context="DATE_ONLY",
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS_FUTURE",
        source_url=f"https://example.com/{event_id}",
        source_event_uid=event_id,
        evidence_text=evidence if evidence is not None else event_name,
        ingest_mode=ingest_mode,
        first_seen_at=NOW,
        last_seen_at=NOW,
        needs_review=needs_review,
    )


# ---------------------------------------------------------------------------
# Duplicate merging
# ---------------------------------------------------------------------------


def test_duplicate_stories_about_one_schedule_merge():
    vague = _news(
        "EV_VAGUE",
        event_name="두산, 中 창수시에 5500억원 투자 …CCL 생산라인 2028년 가동",
        event_date=date(2028, 1, 1),
        precision="YEAR",
        window_start=date(2028, 1, 1),
        window_end=date(2028, 12, 31),
        company="두산",
        evidence="짧은 근거",
    )
    precise = _news(
        "EV_PRECISE",
        event_name="두산, 중국에 5500억 투자…2028년 하반기 CCL 생산라인 가동",
        event_date=date(2028, 7, 1),
        precision="HALF_YEAR",
        window_start=date(2028, 7, 1),
        window_end=date(2028, 12, 31),
        company="두산",
        evidence="두산이 중국 창수시에 5500억원을 투자해 CCL 생산라인을 2028년 하반기 가동한다는 구체적인 근거 문장이다",
        ticker="000150",
    )
    result = merge_duplicate_news_events([vague, precise], now=NOW)

    assert result.clusters_merged == 1
    assert result.events_absorbed == 1
    assert [ev.event_id for ev in result.events] == ["EV_PRECISE"]
    # The survivor is the more precise/informative copy and keeps its ticker.
    assert result.events[0].primary_ticker == "000150"
    # Provenance of the absorbed copy is kept as a revision, not dropped.
    assert len(result.revisions) == 1
    revision = result.revisions[0]
    assert revision.event_id == "EV_PRECISE"
    assert revision.field_name == "duplicate_merged"
    assert revision.old_value == "EV_VAGUE"
    assert revision.new_value == vague.source_url


def test_merge_inherits_ticker_from_absorbed_copy():
    precise = _news(
        "EV_PRECISE",
        event_name="플래스크, LG전자 협력사 동명기계 100% 인수",
        event_type="M_AND_A",
        event_date=date(2027, 2, 19),
        precision="EXACT_DATE",
        company="플래스크",
        evidence="플래스크가 동명기계를 인수한다는 아주 구체적이고 긴 근거 문장이다 " * 3,
    )
    monthly = _news(
        "EV_MONTHLY",
        event_name="플래스크, LG전자 협력사 동명기계 100% 인수",
        event_type="M_AND_A",
        event_date=date(2027, 2, 1),
        precision="MONTH",
        window_start=date(2027, 2, 1),
        window_end=date(2027, 2, 28),
        company="플래스크",
        ticker="041590",
        evidence="짧은 근거",
    )
    result = merge_duplicate_news_events([precise, monthly], now=NOW)
    assert [ev.event_id for ev in result.events] == ["EV_PRECISE"]
    assert result.events[0].primary_ticker == "041590"


def test_different_projects_of_same_company_are_not_merged():
    pyeongtaek = _news(
        "EV_PT",
        event_name="삼성전자, 내년 평택 반도체 공장 착공",
        company="삼성전자",
        event_date=date(2027, 3, 1),
        window_start=date(2027, 3, 1),
        window_end=date(2027, 3, 31),
    )
    hwaseong = _news(
        "EV_HS",
        event_name="삼성전자, 내년 화성 반도체 공장 착공",
        company="삼성전자",
        event_date=date(2027, 3, 1),
        window_start=date(2027, 3, 1),
        window_end=date(2027, 3, 31),
    )
    result = merge_duplicate_news_events([pyeongtaek, hwaseong], now=NOW)
    assert result.clusters_merged == 0
    assert len(result.events) == 2


def test_different_event_types_are_not_merged():
    capex = _news("EV_CAPEX", event_name="두산, 창수시 CCL 생산라인 2028년 가동", company="두산")
    merger = _news(
        "EV_MA",
        event_name="두산, 창수시 CCL 생산라인 2028년 가동",
        event_type="M_AND_A",
        company="두산",
    )
    result = merge_duplicate_news_events([capex, merger], now=NOW)
    assert result.clusters_merged == 0
    assert len(result.events) == 2


def test_far_apart_windows_are_not_merged():
    near = _news(
        "EV_2027",
        event_name="JTBC, 매각 공고…4주간 인수 의향서 접수",
        event_type="M_AND_A",
        company="JTBC",
        event_date=date(2026, 11, 9),
        precision="EXACT_DATE",
    )
    far = _news(
        "EV_2029",
        event_name="JTBC, 매각 공고…4주간 인수 의향서 접수",
        event_type="M_AND_A",
        company="JTBC",
        event_date=date(2029, 5, 9),
        precision="EXACT_DATE",
    )
    result = merge_duplicate_news_events([near, far], now=NOW)
    assert result.clusters_merged == 0
    assert len(result.events) == 2


def test_manual_and_review_events_are_never_absorbed():
    auto = _news("EV_AUTO", event_name="카카오, 인적분할 한 달 연기…임시주총 내년 1월로", event_type="M_AND_A", company="카카오")
    manual = _news(
        "EV_MANUAL",
        event_name="카카오, 인적분할·자회사 합병 한 달 연기…내년 2월로",
        event_type="M_AND_A",
        company="카카오",
        event_date=date(2027, 2, 1),
        window_start=date(2027, 2, 1),
        window_end=date(2027, 2, 28),
        ingest_mode="MANUAL",
    )
    review = _news(
        "EV_REVIEW",
        event_name="카카오, 인적분할 한 달 연기…임시주총 내년 1월로",
        event_type="M_AND_A",
        company="카카오",
        needs_review=True,
    )
    result = merge_duplicate_news_events([auto, manual, review], now=NOW)
    assert result.clusters_merged == 0
    assert len(result.events) == 3


def test_merge_revision_is_not_recorded_twice():
    a = _news("EV_A", event_name="두산, 중국에 5500억 투자…2028년 하반기 CCL 생산라인 가동", company="두산",
              event_date=date(2028, 7, 1), precision="HALF_YEAR",
              window_start=date(2028, 7, 1), window_end=date(2028, 12, 31),
              evidence="긴 근거 문장이다 " * 5)
    b = _news("EV_B", event_name="두산, 中 창수시에 5500억원 투자 …CCL 생산라인 2028년 가동", company="두산",
              event_date=date(2028, 1, 1), precision="YEAR",
              window_start=date(2028, 1, 1), window_end=date(2028, 12, 31), evidence="짧음")
    first = merge_duplicate_news_events([a, b], now=NOW)
    assert len(first.revisions) == 1
    second = merge_duplicate_news_events([a, b], existing_revisions=first.revisions, now=NOW)
    assert second.events_absorbed == 1
    assert second.revisions == []


# ---------------------------------------------------------------------------
# Primary anchoring
# ---------------------------------------------------------------------------


def _sec(event_id: str, ticker: str, grade: str, score: int, company: str = "") -> EventSecurity:
    return EventSecurity(
        event_id=event_id,
        ticker=ticker,
        relation_grade=grade,
        relation_score=score,
        relation_type="DIRECT_MENTION" if grade == "A" else "THEME_MATCH",
        evidence_text="근거",
        company_name=company,
    )


def test_anchor_promotes_highest_scored_a_row():
    ev = _news("EV1")
    rows = [
        _sec("EV1", "111111", "A", 70, "낮은종목"),
        _sec("EV1", "222222", "A", 95, "높은종목"),
        _sec("EV1", "333333", "THEME", 100, "테마종목"),
    ]
    anchored, status = promote_primary_from_relations(ev, rows)
    assert status == "anchored_from_relation"
    assert anchored.primary_ticker == "222222"
    assert anchored.primary_company == "높은종목"
    assert ev.primary_ticker == ""  # original untouched (copy semantics)


def test_anchor_keeps_existing_primary():
    ev = _news("EV1", ticker="999999")
    anchored, status = promote_primary_from_relations(ev, [_sec("EV1", "222222", "A", 95)])
    assert status == "primary"
    assert anchored.primary_ticker == "999999"


def test_anchor_never_promotes_theme_proxy_or_b():
    ev = _news("EV1")
    _, status = promote_primary_from_relations(
        ev, [_sec("EV1", "111111", "THEME", 90), _sec("EV1", "222222", "PROXY", 80)]
    )
    assert status == "theme_proxy_only"
    _, status = promote_primary_from_relations(ev, [_sec("EV1", "111111", "B", 90)])
    assert status == "b_only"
    _, status = promote_primary_from_relations(ev, [_sec("EV1", "", "UNMAPPED", 0)])
    assert status == "unmapped_only"
    _, status = promote_primary_from_relations(ev, [])
    assert status == "no_rows"


def test_anchor_skips_market_proxy_tickers():
    ev = _news("EV1")
    anchored, status = promote_primary_from_relations(
        ev, [_sec("EV1", "^KS11", "A", 100), _sec("EV1", "005930", "A", 60, "삼성전자")]
    )
    assert status == "anchored_from_relation"
    assert anchored.primary_ticker == "005930"


# ---------------------------------------------------------------------------
# Classification guards (user-reported regressions)
# ---------------------------------------------------------------------------

SAMSUNG_BIO_ESG_DIGEST = (
    "[바이오스냅] 삼성바이오로직스, ESG 평가서 최상위 등급. "
    "HK이노엔은 음료 사업 분야를 기존 숙취해소제, 건강음료에서 에너지 음료로 확장할 예정이다. "
    "베리스모는 이달 8일까지 미국 애리조나주에서 열리는 미국면역항암학회에서 전 임상 결과를 발표한다."
)

SAMSUNG_BIO_ESG_CONTRACT = (
    "삼성바이오로직스, 글로벌 ESG 평가서 최상위 등급 획득. "
    "달러) 규모의 바이오의약품 위탁생산(CMO) 계약을 신규 체결했다고 공시했다. "
    "계약 기간은 2031년 12월 31일까지이며, 이번 계약으로 회사 창립 이후 누적 수주액은 약 29조8000억원으로 늘었다."
)


def test_esg_digest_story_is_not_a_clinical_result():
    # Regression: a multi-company digest whose headline is an ESG rating
    # story must not borrow another company's clinical clause.
    assert extract_future_catalyst(SAMSUNG_BIO_ESG_DIGEST, REF) is None
    assert is_non_event_headline(SAMSUNG_BIO_ESG_DIGEST)
    assert is_news_digest("[바이오스냅] 삼성바이오로직스, ESG 평가서 최상위 등급")


def test_esg_contract_period_end_is_not_a_contract_date():
    # Regression: the 2031-12-31 contract *period end* became a CONTRACT
    # event date. The ESG headline vetoes the item outright…
    assert extract_future_catalyst(SAMSUNG_BIO_ESG_CONTRACT, REF) is None
    # …and the period-end guard works on its own, without the ESG headline.
    period_only = (
        "삼성바이오로직스, 바이오의약품 위탁생산 계약 기간은 2031년 12월 31일까지이며 "
        "누적 수주액은 약 29조8000억원이다."
    )
    assert extract_future_catalyst(period_only, REF) is None


def test_genuine_scheduled_contract_still_parses():
    scheduled = "삼성바이오로직스, 2031년 12월 31일 대규모 공급 계약 수주 예정이다."
    result = extract_future_catalyst(scheduled, REF)
    assert result is not None
    _, event_type = result
    assert event_type == "CONTRACT"


def test_promo_and_roundup_headlines_are_rejected():
    casting = (
        "애경산업 시그닉, 키키 지유 전속 모델 발탁…국내외 뷰티시장 공략. "
        "내년 1월 신제품 출시 예정이다."
    )
    assert extract_future_catalyst(casting, REF) is None
    roundup = "아리바이오홀딩스·대명에너지 등 5개 종목 29%대 급등. 아리바이오는 내년 임상 결과를 발표한다."
    assert extract_future_catalyst(roundup, REF) is None


def test_genuine_catalysts_still_parse_after_guards():
    capex = extract_future_catalyst("삼성전자, 내년 3월 평택 반도체 공장 착공 예정이다.", REF)
    assert capex is not None and capex[1] == "CAPEX"
    clinical = extract_future_catalyst("셀트리온, 내년 2월 미국에서 임상 3상 결과를 발표할 예정이다.", REF)
    assert clinical is not None and clinical[1] == "CLINICAL_RESULT"


# ---------------------------------------------------------------------------
# Export: anchor status + date-precision honesty
# ---------------------------------------------------------------------------


def _export(tmp_path, events, securities, anchor_status=None):
    export_site_data(
        events=events,
        revisions=[],
        event_securities=securities,
        event_scores={},
        event_returns_df=None,
        strategy_results={},
        backtest_summaries={},
        output_dir=tmp_path,
        collector_status={},
        now=NOW,
        anchor_status=anchor_status,
    )
    return json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))


def test_export_reports_anchor_status_and_far_future_flag(tmp_path):
    far = _news(
        "EV_FAR",
        event_name="테스트기업, 2028년 신규 공장 착공",
        event_date=date(2028, 1, 1),
        precision="YEAR",
        window_start=date(2028, 1, 1),
        window_end=date(2028, 12, 31),
    )
    rows = _export(
        tmp_path,
        [far],
        {"EV_FAR": [_sec("EV_FAR", "123456", "A", 90, "테스트기업")]},
        anchor_status={"EV_FAR": "anchored_from_relation"},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["anchor_status"] == "anchored_from_relation"
    assert row["date_precision"] == "YEAR"
    assert row["window_start"] == "2028-01-01"
    assert row["window_end"] == "2028-12-31"
    assert row["d_day"] > 365
    assert row["d_day_far_future"] is True


def test_export_derives_theme_only_anchor_status(tmp_path):
    ev = _news(
        "EV_THEME",
        event_name="테스트기업, 내년 3월 신규 공장 착공",
        event_date=date(2027, 3, 1),
        precision="MONTH",
        window_start=date(2027, 3, 1),
        window_end=date(2027, 3, 31),
    )
    rows = _export(tmp_path, [ev], {"EV_THEME": [_sec("EV_THEME", "123456", "THEME", 50)]})
    assert len(rows) == 1
    assert rows[0]["primary_ticker"] == ""
    assert rows[0]["anchor_status"] == "theme_proxy_only"
    assert rows[0]["d_day_far_future"] is False
