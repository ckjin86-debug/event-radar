"""Pilot tests for the Scrapling-based games collector.

Skipped entirely when the optional ``scrapling`` package is not installed,
so the production test suite is unaffected by this pilot.
"""

from datetime import datetime

import pytest

pytest.importorskip("scrapling")

from event_radar.collectors.games import GamesCollector
from event_radar.collectors.games_scrapling import GamesScraplingCollector

SINCE = datetime(2026, 11, 1)

ORIGINAL_HTML = """
<html><body><div class="calendar">
  <div class="calendar__item">
    <a href="/webzine/calendar/game/10697"><span class="calendar__title">스텔라 블레이드</span></a>
    <span class="calendar__date">11/05(목)</span>
  </div>
  <div class="calendar__item">
    <a href="/webzine/calendar/game/20001"><span class="calendar__title">붉은사막 출시</span></a>
    <span class="calendar__date">11/20(금)</span>
  </div>
  <div class="calendar__item">
    <a href="/webzine/calendar/game/30001"><span class="calendar__title">무명 인디 게임 쇼케이스</span></a>
    <span class="calendar__date">11/09(월)</span>
  </div>
</div></body></html>
"""

# Same page after a hypothetical Inven markup change: every class the
# legacy selectors rely on has been renamed.
MUTATED_HTML = (
    ORIGINAL_HTML.replace("calendar__item", "cal-card")
    .replace("calendar__title", "cal-headline")
    .replace("calendar__date", "cal-when")
    .replace('class="calendar"', 'class="schedule-board"')
)


def _brief(events):
    return sorted(
        (str(e.event_date), e.primary_ticker, e.primary_company, e.event_name)
        for e in events
    )


def test_scrapling_matches_bs4_on_current_markup(tmp_path):
    baseline = GamesCollector(mock_html=ORIGINAL_HTML).collect(SINCE)
    pilot = GamesScraplingCollector(
        mock_html=ORIGINAL_HTML, storage_file=str(tmp_path / "fp.db")
    ).collect(SINCE)
    assert len(baseline) == 2  # the unmapped third item is filtered out
    assert _brief(pilot) == _brief(baseline)


def test_bs4_collector_breaks_on_renamed_classes(tmp_path):
    assert GamesCollector(mock_html=MUTATED_HTML).collect(SINCE) == []


def test_scrapling_relocates_after_class_rename(tmp_path):
    store = str(tmp_path / "fp.db")
    # Learn element fingerprints from the current markup first.
    learned = GamesScraplingCollector(
        mock_html=ORIGINAL_HTML, storage_file=store
    ).collect(SINCE)
    assert len(learned) == 2

    # After the markup change, adaptive relocation must recover the events.
    recovered = GamesScraplingCollector(
        mock_html=MUTATED_HTML, storage_file=store
    ).collect(SINCE)
    assert _brief(recovered) == _brief(learned)


def test_scrapling_without_fingerprints_cannot_relocate(tmp_path):
    # No prior learning -> nothing to relocate from -> no events.
    cold = GamesScraplingCollector(
        mock_html=MUTATED_HTML, storage_file=str(tmp_path / "cold.db")
    ).collect(SINCE)
    assert cold == []
