"""Resolve event text into listed securities without guessing from broad themes."""

from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Mapping, Optional
import xml.etree.ElementTree as ET

import requests

from event_radar.models import Event, EventSecurity


DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
MARKET_PROXY_TICKERS = {"^KS11", "^KQ11", "^GSPC", "XBI"}
KOREAN_PARTICLES = (
    "으로", "에서", "까지", "부터", "에게", "보다", "이랑", "라고", "라며",
    "은", "는", "이", "가", "을", "를", "과", "와", "의", "에", "로", "도", "만", "랑",
)


def is_market_proxy(ticker: str) -> bool:
    return (ticker or "").strip().upper() in MARKET_PROXY_TICKERS


def _clean_company_name(value: str) -> str:
    name = (value or "").strip()
    name = re.sub(r"^(?:주식회사|\(주\)|㈜)\s*", "", name)
    name = re.sub(r"\s*(?:주식회사|\(주\)|㈜)$", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _safe_alias(value: str) -> str:
    alias = _clean_company_name(value)
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", alias)
    return alias if len(compact) >= 3 else ""


def parse_dart_corp_code_zip(payload: bytes) -> dict[str, str]:
    """Parse OpenDART corpCode.xml ZIP bytes into listed company -> stock code."""
    if not payload:
        return {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            return {}
        root = ET.fromstring(archive.read(xml_names[0]))

    mapping: dict[str, str] = {}
    for row in root.findall(".//list"):
        company = _clean_company_name(row.findtext("corp_name", default=""))
        ticker = (row.findtext("stock_code", default="") or "").strip().upper()
        if company and re.fullmatch(r"\d{6}", ticker):
            mapping.setdefault(company, ticker)
    return mapping


class ListedCompanyRegistry:
    """Small in-memory name registry backed by OpenDART's listed-company map."""

    def __init__(self, mapping: Mapping[str, str] | None = None) -> None:
        cleaned: dict[str, str] = {}
        for company, ticker in (mapping or {}).items():
            alias = _safe_alias(company)
            code = (ticker or "").strip().upper()
            if alias and re.fullmatch(r"\d{6}", code):
                cleaned[alias] = code
        self._mapping = cleaned
        self._aliases = sorted(
            cleaned,
            key=lambda name: len(re.sub(r"\s+", "", name)),
            reverse=True,
        )
        self._alias_lookup = {alias.casefold(): alias for alias in self._aliases}
        if self._aliases:
            # One compiled alternation is dramatically cheaper than compiling and
            # searching one regex for every listed company for every news event.
            alternatives = "|".join(re.escape(alias) for alias in self._aliases)
            particles = "|".join(re.escape(particle) for particle in KOREAN_PARTICLES)
            right_boundary = (
                rf"(?=$|[^0-9A-Za-z가-힣]|(?:{particles})(?=$|[^0-9A-Za-z가-힣]))"
            )
            self._mention_pattern = re.compile(
                rf"(?<![0-9A-Za-z가-힣])(?:{alternatives}){right_boundary}",
                re.IGNORECASE,
            )
        else:
            self._mention_pattern = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> "ListedCompanyRegistry":
        return cls(mapping)

    @classmethod
    def load_korean(
        cls,
        api_key: Optional[str] = None,
        cache_path: Path | str | None = None,
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ) -> "ListedCompanyRegistry":
        """Load listed Korean companies from cache/OpenDART, failing closed to an empty registry."""
        key = api_key or os.getenv("DART_API_KEY", "")
        path = Path(cache_path) if cache_path else None

        cached = cls._load_cache(path) if path else {}
        if not key:
            return cls(cached)

        http = session or requests.Session()
        try:
            response = http.get(
                DART_CORP_CODE_URL,
                params={"crtfc_key": key},
                timeout=timeout,
            )
            if response.status_code != 200:
                raise ConnectionError(f"OpenDART corpCode HTTP {response.status_code}")
            mapping = parse_dart_corp_code_zip(response.content)
            if mapping:
                if path:
                    cls._save_cache(path, mapping)
                return cls(mapping)
        except Exception:
            pass
        return cls(cached)

    @staticmethod
    def _load_cache(path: Path | None) -> dict[str, str]:
        if path is None or not path.exists():
            return {}
        rows: dict[str, str] = {}
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    company = (row.get("company") or "").strip()
                    ticker = (row.get("ticker") or "").strip()
                    if company and ticker:
                        rows[company] = ticker
        except Exception:
            return {}
        return rows

    @staticmethod
    def _save_cache(path: Path, mapping: Mapping[str, str]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["company", "ticker"])
                writer.writeheader()
                for company, ticker in sorted(mapping.items()):
                    writer.writerow({"company": company, "ticker": ticker})
        except Exception:
            return

    def __bool__(self) -> bool:
        return bool(self._mapping)

    def ticker_for_company(self, company: str) -> str:
        alias = _safe_alias(company)
        return self._mapping.get(alias, "") if alias else ""

    def mentioned_companies(self, text: str) -> list[tuple[str, str]]:
        """Return exact company-name mentions with Korean/Latin token boundaries."""
        if self._mention_pattern is None:
            return []

        haystack = text or ""
        rows: list[tuple[str, str]] = []
        seen_tickers: set[str] = set()
        for match in self._mention_pattern.finditer(haystack):
            company = self._alias_lookup.get(match.group(0).casefold())
            if company is None:
                continue
            ticker = self._mapping[company]
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            rows.append((company, ticker))
        return rows

    def resolve_mentions(self, event: Event) -> list[EventSecurity]:
        if event.country != "KR" or not self._mapping:
            return []
        text = " ".join(
            part for part in (event.primary_company, event.event_name, event.evidence_text) if part
        )
        return [
            EventSecurity(
                event_id=event.event_id,
                ticker=ticker,
                relation_grade="A",
                relation_score=100,
                relation_type="DIRECT_MENTION",
                evidence_text=f"이벤트 원문에 상장사명 명시: {company}",
            )
            for company, ticker in self.mentioned_companies(text)
        ]
