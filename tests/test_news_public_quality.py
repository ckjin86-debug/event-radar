import json
from datetime import date, datetime

from event_radar.export import export_site_data
from event_radar.models import Event, EventSecurity


NOW = datetime(2026, 11, 3, 10, 0, 0)


def _news(
    event_id: str,
    *,
    event_type: str = "CONTRACT",
    company: str = "테스트기업",
    event_name: str = "테스트기업 공급계약 예정",
    event_date: date = date(2026, 12, 1),
    precision: str = "MONTH",
    window_start: date | None = None,
    window_end: date | None = None,
) -> Event:
    return Event(
        event_id=event_id,
        country="KR",
        event_type=event_type,
        event_name=event_name,
        primary_ticker="",
        primary_company=company,
        announced_at=NOW,
        event_date=event_date,
        date_precision=precision,
        window_start=window_start or event_date,
        window_end=window_end or event_date,
        event_time_context="DATE_ONLY",
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS_FUTURE",
        source_url=f"https://example.com/{event_id}",
        source_event_uid=event_id,
        evidence_text=event_name,
        ingest_mode="AUTO",
        first_seen_at=NOW,
        last_seen_at=NOW,
        needs_review=False,
    )


def _sec(event_id: str, ticker: str, grade: str = "A", score: int = 100) -> EventSecurity:
    return EventSecurity(
        event_id=event_id,
        ticker=ticker,
        relation_grade=grade,
        relation_score=score,
        relation_type="DIRECT_MENTION" if grade == "A" else "VERIFIED_RELATION",
        evidence_text="검증된 상장사 관계",
    )


def _visible(tmp_path, events, securities):
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
    )
    rows = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    return rows, metadata


def test_vague_current_period_news_is_not_public_even_when_company_is_mapped(tmp_path):
    event = _news(
        "vague-year",
        event_type="M_AND_A",
        company="LG화학",
        event_name="LG화학 연내 M&A 가능성 검토",
        event_date=date(2026, 11, 3),
        precision="YEAR",
        window_start=date(2026, 11, 3),
        window_end=date(2026, 12, 31),
    )

    rows, metadata = _visible(tmp_path, [event], {event.event_id: [_sec(event.event_id, "051910")]})

    assert rows == []
    assert metadata["news_candidates"] == 1
    assert metadata["news_visible"] == 0


def test_genuinely_future_month_news_with_verified_security_is_public(tmp_path):
    event = _news(
        "future-capex",
        event_type="CAPEX",
        company="현대차그룹",
        event_name="현대차그룹 새만금 AI 데이터센터 내년 3월 착공",
        event_date=date(2027, 3, 1),
        precision="MONTH",
        window_start=date(2027, 3, 1),
        window_end=date(2027, 3, 31),
    )

    rows, metadata = _visible(tmp_path, [event], {event.event_id: [_sec(event.event_id, "005380", "A", 90)]})

    assert [row["event_id"] for row in rows] == ["future-capex"]
    assert metadata["news_candidates"] == 1
    assert metadata["news_visible"] == 1


def test_large_event_first_news_can_remain_without_a_stock_mapping(tmp_path):
    event = _news(
        "nuclear-tender",
        event_type="TENDER",
        company="체코 두코바니 원전",
        event_name="체코 두코바니 원전 12월 우선협상자 발표",
        event_date=date(2026, 12, 15),
        precision="EXACT_DATE",
        window_start=date(2026, 12, 15),
        window_end=date(2026, 12, 15),
    )

    rows, _ = _visible(tmp_path, [event], {})

    assert [row["event_id"] for row in rows] == ["nuclear-tender"]


def test_generic_unmapped_news_noise_is_hidden(tmp_path):
    event = _news(
        "generic-tender",
        event_type="TENDER",
        company="CM",
        event_name="CM·감리 대어 쏟아진다…기술용역 큰 장",
        event_date=date(2026, 12, 1),
        precision="MONTH",
        window_start=date(2026, 12, 1),
        window_end=date(2026, 12, 31),
    )

    rows, _ = _visible(tmp_path, [event], {})

    assert rows == []


def test_historical_court_news_is_hidden_even_with_a_plausible_entity(tmp_path):
    event = _news('past-court', event_type='COURT_RULING', company='세무사회',
        event_name='세무사회 2024년 10월 25일 판결 근거로 조례 개정 촉구',
        event_date=date(2027, 10, 25), precision='EXACT_DATE')
    rows, _ = _visible(tmp_path, [event], {})
    assert rows == []


def test_incidental_court_story_does_not_become_a_market_event(tmp_path):
    event = _news('crime', event_type='COURT_RULING', company='피고인 변호사',
        event_name='피고인 변호사 12월 18일 폭행 혐의 선고 예정',
        event_date=date(2026, 12, 18), precision='EXACT_DATE')
    rows, _ = _visible(tmp_path, [event], {})
    assert rows == []


def test_explicit_manual_schedule_survives_old_news_evidence(tmp_path):
    event = _news('manual', event_type='CAPEX', company='LG화학',
        event_name='LG화학 신규 공장 일정 수동 확인', event_date=date(2026, 12, 18), precision='EXACT_DATE')
    event.ingest_mode = 'AUTO+MANUAL'
    rows, _ = _visible(tmp_path, [event], {event.event_id: [_sec(event.event_id, '051910')]})
    assert len(rows) == 1


def test_duplicate_news_for_same_security_event_and_window_collapses_to_one(tmp_path):
    first = _news("dup-1", company="포스코퓨처엠", event_name="포스코퓨처엠 내년 7월 공급계약")
    second = _news("dup-2", company="포스코퓨처엠-현대차그룹", event_name="포스코퓨처엠 현대차그룹 내년 7월 공급계약")
    for event in (first, second):
        event.event_date = date(2027, 7, 1)
        event.window_start = date(2027, 7, 1)
        event.window_end = date(2027, 7, 31)

    securities = {
        first.event_id: [_sec(first.event_id, "003670")],
        second.event_id: [_sec(second.event_id, "003670")],
    }
    rows, metadata = _visible(tmp_path, [first, second], securities)

    assert len(rows) == 1
    assert rows[0]["event_id"] in {"dup-1", "dup-2"}
    assert metadata["news_candidates"] == 2
    assert metadata["news_visible"] == 1


def test_public_news_is_not_cut_by_an_arbitrary_fixed_cap(tmp_path):
    events = []
    securities = {}
    for index in range(35):
        event = _news(
            f"future-{index}",
            company=f"기업{index}",
            event_name=f"기업{index} 12월 {index % 20 + 1}일 공급계약 예정",
            event_date=date(2026, 12, index % 20 + 1),
            precision="EXACT_DATE",
            window_start=date(2026, 12, index % 20 + 1),
            window_end=date(2026, 12, index % 20 + 1),
        )
        events.append(event)
        securities[event.event_id] = [_sec(event.event_id, f"{100000 + index:06d}")]

    rows, metadata = _visible(tmp_path, events, securities)

    assert len(rows) == 35
    assert metadata["news_visible"] == 35
