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
