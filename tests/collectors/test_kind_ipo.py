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

PROGRAM_TABLE_HTML = """
<table class="list type-00">
  <thead>
    <tr>
      <th title="회사명">회사명</th>
      <th title="신고서제출일">신고서제출일</th>
      <th title="수요예측일정">수요예측일정</th>
      <th title="청약일정">청약일정</th>
      <th title="납입일">납입일</th>
      <th title="확정공모가">확정공모가</th>
      <th title="공모금액(백만원)">공모금액(백만원)</th>
      <th title="상장예정일">상장예정일</th>
      <th title="상장주선인/지정자문인">상장주선인/지정자문인</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td class="first" title="씨아이에스케미칼"><img alt="코스닥"/>씨아이에스케미칼</td>
      <td>2026-10-19</td>
      <td>2026-11-30<br/> ~ 2026-12-04</td>
      <td>2026-12-10<br/> ~ 2026-12-11</td>
      <td>2026-12-15</td>
      <td>-</td>
      <td>-</td>
      <td>2026-12-22</td>
      <td>KB증권(주)</td>
    </tr>
  </tbody>
</table>
"""

AJAX_FRAGMENT_HTML = """
<table class="list type-00">
  <tbody>
    <tr>
      <td class="first" title="씨아이에스케미칼"><img alt="코스닥"/>씨아이에스케미칼</td>
      <td>2026-10-19</td>
      <td>2026-11-30<br/> ~ 2026-12-04</td>
      <td>2026-12-10<br/> ~ 2026-12-11</td>
      <td>2026-12-15</td>
      <td>-</td>
      <td>-</td>
      <td>2026-12-22</td>
      <td>KB증권(주)</td>
    </tr>
    <tr>
      <td class="first" title="동원파츠"><img alt="코스닥"/>동원파츠</td>
      <td>2026-10-01</td>
      <td>2026-10-22<br/> ~ 2026-10-28</td>
      <td>2026-11-02<br/> ~ 2026-11-03</td>
      <td>2026-11-05</td>
      <td>26,500</td>
      <td>53,795</td>
      <td>2026-11-10</td>
      <td>삼성증권(주)</td>
    </tr>
  </tbody>
</table>
"""


class FakeKindResponse:
    def __init__(self, text, status_code=200):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


class KindAjaxSession:
    def __init__(self):
        self.headers = {}
        self.get_calls = []
        self.post_calls = []

    def get(self, url, timeout=None):
        self.get_calls.append(url)
        return FakeKindResponse("<html><form id='searchForm'></form></html>")

    def post(self, url, data=None, timeout=None, headers=None):
        self.post_calls.append({"url": url, "data": data or {}, "headers": headers or {}})
        return FakeKindResponse(AJAX_FRAGMENT_HTML)


def test_kind_ipo_emits_listing_only():
    events = KindIpoCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].event_type == "IPO_LISTING"
    assert events[0].event_date == date(2026, 12, 1)
    assert events[0].primary_company == "에이비씨"
    assert events[0].primary_ticker == "^KQ11"


def test_kind_ipo_uses_kospi_proxy_for_listing():
    events = KindIpoCollector(mock_html=SAMPLE_HTML.replace("코스닥", "코스피")).collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].primary_ticker == "^KS11"


def test_kind_ipo_skips_company_after_listing_date():
    events = KindIpoCollector(mock_html=SAMPLE_HTML).collect(since=datetime(2026, 12, 2))
    assert events == []


def test_kind_calendar_emits_only_listing_entries():
    events = KindIpoCollector(mock_html=CALENDAR_HTML).collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].primary_company == "영광"
    assert events[0].event_type == "IPO_LISTING"
    assert events[0].event_date == date(2026, 11, 2)
    assert events[0].primary_ticker == "^KQ11"


def test_kind_program_table_reads_market_from_company_icon_for_listing():
    events = KindIpoCollector(mock_html=PROGRAM_TABLE_HTML).collect(since=datetime(2026, 11, 1))
    assert len(events) == 1
    assert events[0].primary_company == "씨아이에스케미칼"
    assert events[0].primary_ticker == "^KQ11"
    assert events[0].event_type == "IPO_LISTING"
    assert events[0].event_date == date(2026, 12, 22)


def test_kind_headerless_ajax_fragment_emits_one_listing_per_company():
    events = KindIpoCollector(mock_html=AJAX_FRAGMENT_HTML).collect(since=datetime(2026, 11, 3))
    assert [(e.primary_company, e.event_type, e.event_date) for e in events] == [
        ("동원파츠", "IPO_LISTING", date(2026, 11, 10)),
        ("씨아이에스케미칼", "IPO_LISTING", date(2026, 12, 22)),
    ]
    assert all(e.primary_ticker == "^KQ11" for e in events)


def test_live_kind_collection_gets_session_then_posts_ajax_search_and_returns_listings():
    collector = KindIpoCollector()
    collector.session = KindAjaxSession()
    events = collector.collect(since=datetime(2026, 11, 3))

    assert len(events) == 2
    assert all(e.event_type == "IPO_LISTING" for e in events)
    assert collector.session.get_calls
    assert collector.session.post_calls
    call = collector.session.post_calls[0]
    assert call["url"].endswith("/listinvstg/pubofrprogcom.do")
    assert call["data"]["method"] == "searchPubofrProgComSub"
    assert call["data"]["forward"] == "pubofrprogcom_sub"
    assert call["data"]["currentPageSize"] == "100"
    assert call["data"]["pageIndex"] == "1"
    assert call["data"]["orderMode"] == "1"
    assert call["data"]["orderStat"] == "D"
