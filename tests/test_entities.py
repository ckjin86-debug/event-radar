from __future__ import annotations

import io
import zipfile

from event_radar.entities import (
    EntityUniverse,
    SecurityMention,
    load_entity_universe,
    parse_dart_corp_code_zip,
    parse_sec_company_tickers,
)


def _dart_zip(rows: list[tuple[str, str]]) -> bytes:
    xml_rows = "".join(
        f"<list><corp_name>{name}</corp_name><stock_code>{ticker}</stock_code></list>"
        for name, ticker in rows
    )
    xml = f"<?xml version='1.0' encoding='UTF-8'?><result>{xml_rows}</result>".encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


def test_parse_dart_corp_code_zip_keeps_only_listed_companies():
    records = parse_dart_corp_code_zip(
        _dart_zip([
            ("삼성전자", "005930"),
            ("한화시스템", "272210"),
            ("비상장회사", ""),
        ])
    )

    assert {(r.company_name, r.ticker, r.country) for r in records} == {
        ("삼성전자", "005930", "KR"),
        ("한화시스템", "272210", "KR"),
    }


def test_parse_sec_company_tickers_reads_titles_and_tickers():
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }

    records = parse_sec_company_tickers(payload)

    assert {(r.company_name, r.ticker, r.country) for r in records} == {
        ("Apple Inc.", "AAPL", "US"),
        ("MICROSOFT CORP", "MSFT", "US"),
    }


def test_entity_universe_resolves_multiple_direct_korean_company_mentions():
    universe = EntityUniverse(
        [
            SecurityMention(company_name="삼성전자", ticker="005930", country="KR"),
            SecurityMention(company_name="SK하이닉스", ticker="000660", country="KR"),
        ]
    )

    matches = universe.resolve_mentions(
        "삼성전자·SK하이닉스 내년 HBM 투자 확대",
        country="KR",
    )

    assert {(m.company_name, m.ticker) for m in matches} == {
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
    }


def test_entity_universe_normalizes_common_corporate_suffixes_without_substring_noise():
    universe = EntityUniverse(
        [
            SecurityMention(company_name="주식회사 카카오", ticker="035720", country="KR"),
            SecurityMention(company_name="Apple Inc.", ticker="AAPL", country="US"),
        ]
    )

    kr = universe.resolve_mentions("카카오, 내년 데이터센터 가동", country="KR")
    us = universe.resolve_mentions("Apple plans product launch next month", country="US")
    noise = universe.resolve_mentions("사과 농가 지원 정책 발표", country="KR")

    assert [m.ticker for m in kr] == ["035720"]
    assert [m.ticker for m in us] == ["AAPL"]
    assert noise == []


def test_entity_universe_recognizes_hyundai_motor_news_alias():
    universe = EntityUniverse(
        [SecurityMention(company_name="현대자동차", ticker="005380", country="KR")]
    )

    matches = universe.resolve_mentions(
        "현대차그룹, 9조 새만금 AI 밸리 내년 3월 착공",
        country="KR",
    )

    assert [m.ticker for m in matches] == ["005380"]


def test_short_korean_issuer_names_do_not_match_inside_longer_words_or_company_names():
    universe = EntityUniverse(
        [
            SecurityMention(company_name="한화", ticker="000880", country="KR"),
            SecurityMention(company_name="한화시스템", ticker="272210", country="KR"),
            SecurityMention(company_name="흥국", ticker="010240", country="KR"),
            SecurityMention(company_name="타이드", ticker="346010", country="KR"),
            SecurityMention(company_name="레이", ticker="228670", country="KR"),
            SecurityMention(company_name="샘표", ticker="007540", country="KR"),
            SecurityMention(company_name="샘표식품", ticker="248170", country="KR"),
        ]
    )

    court = universe.resolve_mentions("흥국생명·한화시스템 321억 맞소송", "KR")
    peptide = universe.resolve_mentions("삼성바이오로직스, 폴리펩타이드 공개매수 성료", "KR")
    game = universe.resolve_mentions("엘리멘타 신작 실버팰리스 글로벌 정식 출시", "KR")
    merger = universe.resolve_mentions("샘표식품, 지주사 샘표 흡수 합병", "KR")

    assert [(m.company_name, m.ticker) for m in court] == [("한화시스템", "272210")]
    assert peptide == []
    assert game == []
    assert {(m.company_name, m.ticker) for m in merger} == {
        ("샘표", "007540"),
        ("샘표식품", "248170"),
    }


class _Response:
    def __init__(self, *, status_code=200, content=b"", payload=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.responses:
            raise RuntimeError("unexpected request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_load_entity_universe_gracefully_uses_whichever_official_source_is_available():
    session = _Session(
        [
            RuntimeError("dart unavailable"),
            _Response(payload={"0": {"ticker": "AAPL", "title": "Apple Inc."}}),
        ]
    )

    universe = load_entity_universe(dart_api_key="test-key", session=session)

    assert [m.ticker for m in universe.resolve_mentions("Apple acquisition closes next month", "US")] == ["AAPL"]


def test_load_entity_universe_gives_slow_dart_master_a_longer_timeout_than_sec():
    session = _Session(
        [
            _Response(content=_dart_zip([("삼성바이오로직스", "207940")])),
            _Response(payload={"0": {"ticker": "AAPL", "title": "Apple Inc."}}),
        ]
    )

    universe = load_entity_universe(dart_api_key="test-key", session=session)

    dart_timeout = session.calls[0][1]["timeout"]
    sec_timeout = session.calls[1][1]["timeout"]
    assert dart_timeout >= 30
    assert sec_timeout <= dart_timeout
    assert [m.ticker for m in universe.resolve_mentions("삼성바이오로직스 인수 마무리", "KR")] == ["207940"]
