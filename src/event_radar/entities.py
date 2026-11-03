"""Official listed-company universe used for evidence-first event/security mapping."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Iterable
from xml.etree import ElementTree

import requests


DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass(frozen=True)
class SecurityMention:
    company_name: str
    ticker: str
    country: str


def _normalize_company_name(value: str, country: str) -> str:
    text = (value or "").strip().lower()
    if country == "KR":
        text = re.sub(r"(?:주식회사|㈜|\(주\))", "", text)
    else:
        text = re.sub(
            r"\b(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc)\b\.?,?",
            "",
            text,
        )
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def _company_aliases(company_name: str, country: str) -> set[str]:
    """Return conservative aliases commonly used in headlines."""
    normalized = _normalize_company_name(company_name, country)
    aliases = {normalized} if normalized else set()
    if country == "KR" and normalized.endswith("자동차") and len(normalized) > len("자동차"):
        # 현대자동차 -> 현대차. This also lets '현대차그룹' resolve to the listed issuer.
        aliases.add(f"{normalized[:-len('자동차')]}차")
    return {alias for alias in aliases if len(alias) >= 2}


def parse_dart_corp_code_zip(content: bytes) -> list[SecurityMention]:
    """Parse OpenDART corpCode.xml ZIP and keep listed issuers only."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
        root = ElementTree.fromstring(archive.read(xml_name))

    records: list[SecurityMention] = []
    for row in root.findall(".//list"):
        company = (row.findtext("corp_name") or "").strip()
        ticker = (row.findtext("stock_code") or "").strip()
        if not company or not re.fullmatch(r"\d{6}", ticker):
            continue
        records.append(SecurityMention(company_name=company, ticker=ticker, country="KR"))
    return records


def parse_sec_company_tickers(payload: dict) -> list[SecurityMention]:
    """Parse SEC company_tickers.json into listed issuer records."""
    records: list[SecurityMention] = []
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        company = str(row.get("title", "")).strip()
        ticker = str(row.get("ticker", "")).strip().upper()
        if not company or not ticker:
            continue
        records.append(SecurityMention(company_name=company, ticker=ticker, country="US"))
    return records


class EntityUniverse:
    """Resolve explicit listed-company mentions without theme inference."""

    def __init__(self, records: Iterable[SecurityMention] = ()) -> None:
        self.records = list(records)
        self._indexed: dict[str, list[tuple[str, SecurityMention]]] = {"KR": [], "US": []}
        for record in self.records:
            country = record.country.upper()
            for alias in _company_aliases(record.company_name, country):
                self._indexed.setdefault(country, []).append((alias, record))

    def resolve_mentions(self, text: str, country: str) -> list[SecurityMention]:
        country = country.upper()
        normalized_text = _normalize_company_name(text, country)
        by_ticker: dict[str, SecurityMention] = {}
        for normalized_company, record in self._indexed.get(country, []):
            if normalized_company in normalized_text:
                by_ticker[record.ticker] = record
        return sorted(by_ticker.values(), key=lambda item: item.company_name)


def load_entity_universe(
    dart_api_key: str = "",
    session=None,
    timeout: int = 15,
) -> EntityUniverse:
    """Load KR/US official issuer universes; one source failure must not break the other."""
    http = session or requests.Session()
    records: list[SecurityMention] = []

    if dart_api_key:
        try:
            # corpCode.xml is a multi-megabyte ZIP and is materially slower than SEC's JSON.
            # Give it an independent floor so a healthy but slow DART response is not discarded.
            response = http.get(
                DART_CORP_CODE_URL,
                params={"crtfc_key": dart_api_key},
                timeout=max(timeout, 45),
            )
            if response.status_code == 200:
                records.extend(parse_dart_corp_code_zip(response.content))
        except Exception:
            pass

    try:
        response = http.get(
            SEC_COMPANY_TICKERS_URL,
            headers={"User-Agent": "EventRadar/1.0 admin@eventradar.org"},
            timeout=timeout,
        )
        if response.status_code == 200:
            records.extend(parse_sec_company_tickers(response.json()))
    except Exception:
        pass

    return EntityUniverse(records)
