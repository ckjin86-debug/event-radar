from datetime import date, datetime

from event_radar.collectors.fomc import FomcCollector


SAMPLE_HTML = """
<div class="panel panel-default">
  <div class="panel-heading"><h4>2026 FOMC Meetings</h4></div>
  <div class="panel-body">
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month">October</div>
      <div class="fomc-meeting__date">27-28</div>
    </div>
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month">December</div>
      <div class="fomc-meeting__date">8-9*</div>
    </div>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h4>2027 FOMC Meetings</h4></div>
  <div class="panel-body">
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month">January</div>
      <div class="fomc-meeting__date">26-27</div>
    </div>
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month">June</div>
      <div class="fomc-meeting__date">15</div>
    </div>
  </div>
</div>
"""


def test_fomc_uses_final_day_of_two_day_meeting():
    events = FomcCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 11, 1))
    december = [e for e in events if e.event_date.year == 2026][0]

    assert december.event_type == "FOMC_DECISION"
    assert december.event_date == date(2026, 12, 9)
    assert december.primary_ticker == "^GSPC"
    assert december.primary_company == "Federal Reserve"
    assert december.status == "CONFIRMED"
    assert december.source_name == "FED_FOMC"


def test_fomc_one_day_meeting_uses_same_day():
    events = FomcCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2027, 6, 1))
    assert len(events) == 1
    assert events[0].event_date == date(2027, 6, 15)


def test_fomc_skips_decisions_before_since():
    events = FomcCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 11, 1))
    dates = [e.event_date for e in events]
    assert date(2026, 10, 28) not in dates
    assert date(2026, 12, 9) in dates
    assert date(2027, 1, 27) in dates
def test_cross_month_decision_date_uses_final_month():
    from event_radar.collectors.fomc import _decision_date
    from datetime import date
    assert _decision_date(2024, 'Apr/May', '30-1') == date(2024, 5, 1)
    assert _decision_date(2023, 'Jan/Feb', '31-1') == date(2023, 2, 1)


def test_notation_vote_is_not_a_policy_decision():
    from event_radar.collectors.fomc import _decision_date
    assert _decision_date(2025, 'August', '22 (notation vote)') is None
