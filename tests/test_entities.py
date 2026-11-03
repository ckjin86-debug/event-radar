from __future__ import annotations

import io
import json
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
            SecurityMention(company_name="흥국생명", ticker="000540", country="KR"),
            SecurityMention(company_name="한화시스템", ticker="272210", country="KR"),
            SecurityMention(company_name="삼성전자", ticker="005930", country="KR"),
        ]
    )

    matches = universe.resolve_mentions(
        "흥국생명·한화시스템 321억 맞소송, 내달 6일 선고",
        country="KR",
    )

    assert [(m.company_name, m.ticker) for m in matches] == [
        ("한화시스템", "272210"),
        ("흥국생명", "000540"),
    ]


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

    def get(self, *args, **kwargs):
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
