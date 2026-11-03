from datetime import date, datetime

from event_radar.collectors.kind_ipo import KindIpoCollector


SAMPLE_HTML = """
<table>
  <thead>
    <tr>
      <th>회사명</th><th>시장</th><th>수요예측일</th><th>청약일</th><th>납입일</th><th>상장예정일</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><a href="/listinvstg/detail.do?corp=ABC">에이비씨</a></td>
      <td>코스닥</td>
      <td>2026.11.10 ~ 2026.11.11</td>
      <td>2026.11.20 ~ 2026.11.21</td>
      <td>2026.11.25</td>
      <td>2026.12.01</td>
    </tr>
  </tbody>
</table>
"""

CALENDAR_HTML = """
<div id="calBig2">
  <center><font>2026년 11월</font></center>
  <table><tbody><tr>
    <td>2
      <ul>
        <li><strong>청약</strong></li>
        <li><img alt="코스닥"/>동원파츠</li>
        <li><strong>상장</strong></li>
        <li><img alt="코스닥"/>영광</li>
        <li><strong>IR</strong></li>
        <li><img alt="코스닥"/>무시할회사</li>
      </ul>
    </td>
    <td>3
      <ul>
        <li><strong>청약</strong></li>
        <li><img alt="코스닥"/>동원파츠</li>
        <li><strong>수요예측</strong></li>
        <li><img alt="유가증권"/>테스트홀딩스</li>
      </ul>
    </td>
    <td>4
      <ul>
        <li><strong>수요예측</strong></li>
        <li><img alt="유가증권"/>테스트홀딩스</li>
      </ul>
    </td>
    <td>5
      <ul>
        <li><strong>납입</strong></li>
        <li><img alt="코스닥"/>동원파츠</li>
      </ul>
    </td>
  </tr></tbody></table>
</div>
"""


def test_kind_ipo_emits_all_schedule_milestones():
    events = KindIpoCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 11, 1))

    assert [e.event_type for e in events] == [
        "IPO_BOOKBUILDING_START",
        "IPO_BOOKBUILDING_END",
        "IPO_SUBSCRIPTION_START",
        "IPO_SUBSCRIPTION_END",
        "IPO_PAYMENT",
        "IPO_LISTING",
    ]
    assert [e.event_date for e in events] == [
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 20),
        date(2026, 11, 21),
        date(2026, 11, 25),
        date(2026, 12, 1),
    ]
    assert all(e.primary_company == "에이비씨" for e in events)
    assert all(e.primary_ticker == "^KQ11" for e in events)
    assert all(e.source_name == "KIND_IPO" for e in events)
    assert all(e.status == "CONFIRMED" for e in events)


def test_kind_ipo_uses_kospi_proxy_for_kospi_rows():
    html = SAMPLE_HTML.replace("코스닥", "코스피")
    events = KindIpoCollector(mock_html=html).collect(since=datetime(2026, 11, 1))
    assert events
    assert all(e.primary_ticker == "^KS11" for e in events)


def test_kind_ipo_skips_milestones_before_since_but_keeps_future_ones():
    events = KindIpoCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 11, 22))
    assert [e.event_type for e in events] == ["IPO_PAYMENT", "IPO_LISTING"]


def test_kind_calendar_markup_groups_multi_day_periods_and_ignores_ir():
    events = KindIpoCollector(mock_html=CALENDAR_HTML).collect(since=datetime(2026, 11, 1))
    by_key = {(e.primary_company, e.event_type): e for e in events}

    assert by_key[("동원파츠", "IPO_SUBSCRIPTION_START")].event_date == date(2026, 11, 2)
    assert by_key[("동원파츠", "IPO_SUBSCRIPTION_END")].event_date == date(2026, 11, 3)
    assert by_key[("동원파츠", "IPO_PAYMENT")].event_date == date(2026, 11, 5)
    assert by_key[("영광", "IPO_LISTING")].event_date == date(2026, 11, 2)
    assert by_key[("테스트홀딩스", "IPO_BOOKBUILDING_START")].event_date == date(2026, 11, 3)
    assert by_key[("테스트홀딩스", "IPO_BOOKBUILDING_END")].event_date == date(2026, 11, 4)
    assert by_key[("테스트홀딩스", "IPO_BOOKBUILDING_START")].primary_ticker == "^KS11"
    assert all(e.primary_company != "무시할회사" for e in events)


def test_kind_calendar_uses_kosdaq_proxy_from_official_market_alt_text():
    events = KindIpoCollector(mock_html=CALENDAR_HTML).collect(since=datetime(2026, 11, 1))
    dongwon = [e for e in events if e.primary_company == "동원파츠"]
    assert dongwon
    assert all(e.primary_ticker == "^KQ11" for e in dongwon)
