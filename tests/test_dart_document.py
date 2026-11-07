"""Unit tests for the DART document parser (DISCLOSED 세력평단).

The HTML fixtures mirror the original extension's parsing targets:
dsaf001/main.do viewDoc(...) parameters, the report summary table
(직전/이번/증감), the holding-purpose row, and the 10-column
'2. 세부변동내역' table [성명, 생년월일, 변동일, 취득/처분방법, 주식종류,
변동전, 증감, 변동후, 취득/처분단가, 비고].
"""

from event_radar.dart_document import (
    parse_dart_document_html,
    parse_dart_report_detail,
)


MAIN_HTML = """
<html><head><script>
function openDoc() {
  viewDoc('20261105000111', '10000001', '1', '0', '5000', 'dart4.xsd');
  viewDoc('20261105000111', '10000002', '2', '0', '5000', 'dart4.xsd');
}
</script></head><body>공시 원문</body></html>
"""

# 요약표 + 보유목적 (첫 번째 뷰어 문서)
SUMMARY_HTML = """
<table>
  <tr><td>보유목적</td><td>상세</td><td>경영권 영향</td></tr>
  <tr><td>변동사유</td><td>장내매수에 따른 보유주식수 증가</td></tr>
  <tr>
    <td>직전보고서</td><td>2026.10.01</td><td>446,889,456</td><td>7.39</td><td>2026.10.05</td>
  </tr>
  <tr>
    <td>이번보고서</td><td>2026.11.05</td><td>448,123,456</td><td>7.51</td><td>2026.11.05</td>
  </tr>
  <tr>
    <td>증감</td><td>-</td><td>1,234,000</td><td>0.12</td><td>-</td>
  </tr>
</table>
"""

# 세부변동내역 (두 번째 뷰어 문서): 유효 매수 2건 + 제외 대상 다수
DETAIL_HTML = """
<table>
  <tr>
    <td>성명</td><td>생년월일</td><td>변동일</td><td>취득/처분방법</td><td>주식의 종류</td>
    <td>변동전</td><td>증감</td><td>변동후</td><td>취득/처분단가</td><td>비고</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.03</td><td>장내매수</td><td>보통주</td>
    <td>100,000</td><td>1,000</td><td>101,000</td><td>5,000</td><td>-</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장외매수</td><td>보통주</td>
    <td>101,000</td><td>3,000</td><td>104,000</td><td>6,000</td><td>-</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장내매도</td><td>보통주</td>
    <td>104,000</td><td>500</td><td>103,500</td><td>7,000</td><td>-</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>취득/처분</td><td>보통주</td>
    <td>103,500</td><td>900</td><td>104,400</td><td>8,000</td><td>-</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장내매수</td><td>보통주</td>
    <td>104,400</td><td>(2,000)</td><td>102,400</td><td>5,000</td><td>음수 수량</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장내매수</td><td>보통주</td>
    <td>102,400</td><td>100</td><td>102,500</td><td>50</td><td>단가 하한 가드</td>
  </tr>
  <tr>
    <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장내매수</td><td>보통주</td>
    <td>102,500</td><td>100</td><td>102,600</td><td>20,000,000</td><td>단가 상한 가드</td>
  </tr>
</table>
"""


def _fetch_from(pages):
    """fetch_text serving MAIN_HTML for main.do and pages in order."""
    state = {"idx": 0}

    def fetch(url):
        if "dsaf001/main.do" in url:
            return MAIN_HTML
        idx = state["idx"]
        state["idx"] += 1
        return pages[idx] if idx < len(pages) else None

    return fetch


def test_parse_report_detail_computes_disclosed_weighted_average():
    result = parse_dart_report_detail(
        "20261105000111", fetch_text=_fetch_from([SUMMARY_HTML, DETAIL_HTML])
    )

    assert result["ok"] is True
    # (1,000 × 5,000 + 3,000 × 6,000) / 4,000 = 5,750 — 매도/처분/음수/
    # 단가 가드 행은 전부 제외된다.
    assert result["total_shares"] == 4000
    assert result["total_cost"] == 23_000_000
    assert result["weighted_avg_price"] == 5750
    assert (
        result["price_source"]
        == "DISCLOSED: 원문 제3부 세부변동내역 가중평균(4,000주)"
    )
    assert result["unit_prices"] == [
        "5,750원 (수량가중평균)",
        "5,000원",
        "6,000원",
    ]
    assert result["viewer_url"] == (
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261105000111"
    )


def test_parse_report_detail_extracts_summary_and_purpose():
    result = parse_dart_report_detail(
        "20261105000111", fetch_text=_fetch_from([SUMMARY_HTML, DETAIL_HTML])
    )

    assert result["curr_purpose"] == "경영권 영향"
    assert result["prev_purpose"] is None  # 원본에서도 설정되지 않는다
    assert result["report_resn"] == "장내매수에 따른 보유주식수 증가"
    assert result["hold_stock_cnt"] == "448,123,456"
    assert result["hold_stock_rt"] == 7.51
    assert result["stk_rt_var"] == 0.12
    assert result["stk_cnt_var"] == "1,234,000"


def test_parse_merges_multiple_viewer_documents():
    # 매수 행이 두 문서에 나뉘어 있어도 합산된다.
    doc_a = """
    <table><tr>
      <td>홍길동</td><td>1970.01.01</td><td>2026-11-03</td><td>장내매수</td>
      <td>보통주</td><td>0</td><td>1,000</td><td>1,000</td><td>5,000원</td><td>-</td>
    </tr></table>
    """
    doc_b = """
    <table><tr>
      <td>홍길동</td><td>1970.01.01</td><td>2026/11/04</td><td>시간외매수</td>
      <td>보통주</td><td>1,000</td><td>3,000</td><td>4,000</td><td>6,000</td><td>-</td>
    </tr></table>
    """
    result = parse_dart_report_detail(
        "20261105000111", fetch_text=_fetch_from([doc_a, doc_b])
    )

    assert result["ok"] is True
    assert result["total_shares"] == 4000
    assert result["weighted_avg_price"] == 5750


def test_parse_caps_viewer_documents_at_six():
    main_html = "<script>" + "".join(
        f"viewDoc('20261105000111', '2000000{i}', '{i}', '0', '100', 'dart4.xsd');"
        for i in range(8)
    ) + "</script>"
    fetched = []

    def fetch(url):
        fetched.append(url)
        if "dsaf001/main.do" in url:
            return main_html
        return "<table></table>"

    result = parse_dart_report_detail("20261105000111", fetch_text=fetch)

    assert result["ok"] is True
    viewer_calls = [u for u in fetched if "report/viewer.do" in u]
    assert len(viewer_calls) == 6  # 원본 slice(0, 6)


def test_parse_purpose_variants():
    def purpose_of(cell_text):
        html = (
            "<table><tr><td>보유목적</td>"
            f"<td>{cell_text}</td></tr></table>"
        )
        return parse_dart_document_html(html)["curr_purpose"]

    assert purpose_of("경영참여 목적") == "경영권 영향"
    assert purpose_of("일반투자") == "일반투자"
    assert purpose_of("단순투자") == "단순투자"
    assert purpose_of("기타") is None


def test_parse_without_buy_rows_has_no_price():
    sell_only = """
    <table><tr>
      <td>홍길동</td><td>1970.01.01</td><td>2026.11.04</td><td>장내매도</td>
      <td>보통주</td><td>104,000</td><td>500</td><td>103,500</td><td>7,000</td><td>-</td>
    </tr></table>
    """
    result = parse_dart_document_html(sell_only)

    assert result["weighted_avg_price"] is None
    assert result["price_source"] is None
    assert result["unit_prices"] == []
    assert result["total_shares"] == 0


def test_parse_main_fetch_failure_is_graceful():
    def fetch_none(url):
        return None

    def fetch_raise(url):
        raise ConnectionError("unreachable")

    for fetch in (fetch_none, fetch_raise):
        result = parse_dart_report_detail("20261105000111", fetch_text=fetch)
        assert result["ok"] is False
        assert result["weighted_avg_price"] is None
        assert result["unit_prices"] == []


def test_parse_single_viewer_failure_is_skipped():
    def fetch(url):
        if "dsaf001/main.do" in url:
            return MAIN_HTML
        if "10000001" in url:
            raise TimeoutError("slow document")
        return DETAIL_HTML

    result = parse_dart_report_detail("20261105000111", fetch_text=fetch)

    # 첫 번째 문서(요약)가 실패해도 두 번째 문서의 단가는 살아남는다.
    assert result["ok"] is True
    assert result["weighted_avg_price"] == 5750
    assert result["curr_purpose"] is None


def test_parse_empty_rcept_no_is_graceful():
    result = parse_dart_report_detail("", fetch_text=lambda url: MAIN_HTML)
    assert result["ok"] is False


# 현행 main.do 목차 형식: nodeN['rcpNo'] = "..." JS 할당
NODE_MAIN_HTML = """
<script>
function makeToc() {
  var node1 = {};
  node1['text'] = "주식등의 대량보유상황보고서";
  node1['id'] = "1";
  node1['rcpNo'] = "20261105000111";
  node1['dcmNo'] = "11645659";
  node1['eleId'] = "1";
  node1['offset'] = "809";
  node1['length'] = "9225";
  node1['dtd'] = "dart4.xsd";
  node1['tocNo'] = "1";
  var node2 = {};
  node2['text'] = "제3부 직전보고일 이후 대량변동 내역";
  node2['id'] = "20";
  node2['rcpNo'] = "20261105000111";
  node2['dcmNo'] = "11645659";
  node2['eleId'] = "20";
  node2['offset'] = "75932";
  node2['length'] = "18590";
  node2['dtd'] = "dart4.xsd";
  node2['tocNo'] = "12";
}
</script>
"""


def test_parse_supports_current_node_toc_format():
    fetched = []

    def fetch(url):
        fetched.append(url)
        if "dsaf001/main.do" in url:
            return NODE_MAIN_HTML
        if "eleId=20" in url:
            return DETAIL_HTML
        return SUMMARY_HTML

    result = parse_dart_report_detail("20261105000111", fetch_text=fetch)

    assert result["ok"] is True
    viewer_calls = [u for u in fetched if "report/viewer.do" in u]
    assert len(viewer_calls) == 2
    assert "dcmNo=11645659" in viewer_calls[0]
    assert result["weighted_avg_price"] == 5750
    assert result["curr_purpose"] == "경영권 영향"


def test_parse_korean_date_format_detail_rows():
    # 현행 원문의 "2026년 07월 07일" 변동일 표기도 세부변동 행으로 인정한다.
    html = """
    <table><tr>
      <td>FIDELITY FUNDS</td><td>1582</td><td>2026년 07월 07일</td><td>장내매수(+)</td>
      <td>의결권있는 주식</td><td>523,220</td><td>5,558</td><td>528,778</td>
      <td>45,735</td><td>(원)</td><td>-</td>
    </tr></table>
    """
    result = parse_dart_document_html(html)

    assert result["total_shares"] == 5558
    assert result["weighted_avg_price"] == 45735


def test_node_toc_skips_documents_contained_in_parent():
    # 장(章) 문서 범위에 포함되는 하위 절 문서는 중복 결합하지 않는다.
    main_html = """
    <script>
      var node1 = {};
      node1['rcpNo'] = "20261105000111";
      node1['dcmNo'] = "11645659";
      node1['eleId'] = "2";
      node1['offset'] = "1000";
      node1['length'] = "9000";
      node1['dtd'] = "dart4.xsd";
      var node2 = {};
      node2['rcpNo'] = "20261105000111";
      node2['dcmNo'] = "11645659";
      node2['eleId'] = "3";
      node2['offset'] = "2000";
      node2['length'] = "1000";
      node2['dtd'] = "dart4.xsd";
      var node3 = {};
      node3['rcpNo'] = "20261105000111";
      node3['dcmNo'] = "11645659";
      node3['eleId'] = "11";
      node3['offset'] = "20000";
      node3['length'] = "5000";
      node3['dtd'] = "dart4.xsd";
    </script>
    """
    fetched = []

    def fetch(url):
        fetched.append(url)
        if "dsaf001/main.do" in url:
            return main_html
        return "<table></table>"

    result = parse_dart_report_detail("20261105000111", fetch_text=fetch)

    assert result["ok"] is True
    viewer_calls = [u for u in fetched if "report/viewer.do" in u]
    assert len(viewer_calls) == 2  # eleId=3은 eleId=2 범위에 포함되어 제외
    assert any("eleId=2" in u for u in viewer_calls)
    assert any("eleId=11" in u for u in viewer_calls)
