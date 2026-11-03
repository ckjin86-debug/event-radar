from datetime import date, datetime

from event_radar.models import Event
from event_radar.theme import load_theme_mappings, resolve_theme_securities


def _event(name: str, when: date, ticker: str = "") -> Event:
    now = datetime(2026, 11, 3, 15, 0)
    return Event(
        event_id=f"ev-{when.isoformat()}-{name[:6]}",
        country="KR",
        event_type="TENDER" if "원전" in name else "ELECTION",
        event_name=name,
        primary_ticker=ticker,
        primary_company=name,
        announced_at=now,
        event_date=when,
        status="CONFIRMED",
        source_kind="SECONDARY",
        source_name="TEST",
        first_seen_at=now,
        last_seen_at=now,
    )


def test_official_nuclear_mapping_is_b_grade_and_dedupes_weaker_theme(tmp_path):
    path = tmp_path / "theme_mappings.csv"
    path.write_text(
        "mapping_id,event_pattern,ticker,company,relation_grade,relation_score,relation_type,valid_from,valid_to,evidence_text,source_url\n"
        "n1,체코|Dukovany,034020,두산에너빌리티,B,90,OFFICIAL_CONSORTIUM,2024-01-01,,공식 컨소시엄,https://example.com/official\n"
        "n2,원전|nuclear,034020,두산에너빌리티,THEME,50,MARKET_THEME,2009-01-01,,원전 테마,https://example.com/theme\n",
        encoding="utf-8",
    )
    mappings = load_theme_mappings(path)
    event = _event("체코 Dukovany 원전 우선협상대상자 선정", date(2026, 12, 18))

    rows = resolve_theme_securities(event, mappings)

    assert len(rows) == 1
    assert rows[0].ticker == "034020"
    assert rows[0].relation_grade == "B"
    assert rows[0].relation_score == 90


def test_political_theme_mapping_is_time_bounded_and_never_promoted_to_b(tmp_path):
    path = tmp_path / "theme_mappings.csv"
    path.write_text(
        "mapping_id,event_pattern,ticker,company,relation_grade,relation_score,relation_type,valid_from,valid_to,evidence_text,source_url\n"
        "p1,윤석열,053290,NE능률,THEME,40,POLITICAL_THEME,2021-01-01,2022-03-10,언론에서 정치 테마주로 분류,https://example.com/politics\n",
        encoding="utf-8",
    )
    mappings = load_theme_mappings(path)

    historical = resolve_theme_securities(_event("대통령선거 윤석열 테마주", date(2022, 3, 9)), mappings)
    stale = resolve_theme_securities(_event("윤석열 관련 정치 이벤트", date(2026, 6, 3)), mappings)

    assert len(historical) == 1
    assert historical[0].relation_grade == "THEME"
    assert historical[0].relation_score == 40
    assert stale == []
