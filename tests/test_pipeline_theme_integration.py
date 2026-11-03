from datetime import date, datetime

from event_radar.models import Event
from event_radar.theme import load_theme_mappings, merge_event_securities, resolve_theme_securities
from event_radar.relations import resolve_related_securities


def test_unmapped_event_is_replaced_by_theme_candidate(tmp_path):
    mapping = tmp_path / "theme_mappings.csv"
    mapping.write_text(
        "mapping_id,event_pattern,ticker,company,relation_grade,relation_score,relation_type,valid_from,valid_to,evidence_text,source_url\n"
        "x1,원전,034020,두산에너빌리티,THEME,55,NUCLEAR_MARKET_THEME,2024-01-01,,원전 테마 후보,https://example.com\n",
        encoding="utf-8",
    )
    now = datetime(2026, 11, 3, 15, 0)
    event = Event(
        event_id="nuclear-1",
        country="KR",
        event_type="TENDER",
        event_name="원전 입찰 일정",
        primary_ticker="",
        primary_company="원전 프로젝트",
        announced_at=now,
        event_date=date(2026, 12, 18),
        status="EXPECTED",
        source_kind="SECONDARY",
        source_name="NEWS_FUTURE",
        first_seen_at=now,
        last_seen_at=now,
    )

    direct = resolve_related_securities(event, [])
    theme = resolve_theme_securities(event, load_theme_mappings(mapping))
    merged = merge_event_securities(direct, theme)

    assert len(merged) == 1
    assert merged[0].ticker == "034020"
    assert merged[0].relation_grade == "THEME"
