"""Evidence-backed related-stock enrichment for Korean IPO listing events."""

from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

import requests

from event_radar.entity_resolver import ListedCompanyRegistry
from event_radar.models import Event, EventSecurity


NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

RELATION_RULES: tuple[tuple[str, str, int], ...] = (
    ("IPO_MAJOR_SHAREHOLDER", r"최대\s*주주|대주주", 88),
    ("IPO_PARENT", r"모회사|자회사", 90),
    ("IPO_INVESTOR", r"투자|지분|출자|주주", 76),
    ("IPO_AFFILIATE", r"계열사|관계사", 68),
    ("IPO_BUSINESS_RELATION", r"공급|납품|고객|협력|파트너|계약", 64),
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _parse_pubdate(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except Exception:
        return None


def _relation_for_clause(clause: str) -> tuple[str, int] | None:
    for relation_type, pattern, score in RELATION_RULES:
        if re.search(pattern, clause, re.IGNORECASE):
            return relation_type, score
    return None


class IpoRelationEnricher:
    """Search recent news once per IPO and map only explicit listed relationships."""

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        api_key: Optional[str] = None,
        mock_payloads: Optional[list[dict]] = None,
        timeout: int = 10,
        max_workers: int = 6,
    ) -> None:
        self.api_key_id = api_key_id or os.getenv("NAVER_API_HUB_KEY_ID", "")
        self.api_key = api_key or os.getenv("NAVER_API_HUB_KEY", "")
        self.mock_payloads = mock_payloads
        self.timeout = timeout
        self.max_workers = max(1, min(10, int(max_workers)))
        self._payload_cache: dict[str, list[dict]] = {}

    def _fetch_company(self, company: str) -> list[dict]:
        if self.mock_payloads is not None:
            return self.mock_payloads
        if not self.api_key_id or not self.api_key:
            return []
        try:
            response = requests.get(
                NAVER_NEWS_URL,
                headers={
                    "X-NCP-APIGW-API-KEY-ID": self.api_key_id,
                    "X-NCP-APIGW-API-KEY": self.api_key,
                },
                params={"query": company, "display": 100, "sort": "date"},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return []
            return [response.json()]
        except Exception:
            return []

    def prefetch(self, companies: Iterable[str]) -> None:
        """Fetch unique IPO-company searches concurrently and cache the payloads."""
        unique = []
        seen = set()
        for raw in companies:
            company = (raw or "").strip()
            if not company or company in seen or company in self._payload_cache:
                continue
            seen.add(company)
            unique.append(company)
        if not unique:
            return

        workers = min(self.max_workers, len(unique))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(self._fetch_company, company): company for company in unique
            }
            for future in as_completed(future_map):
                company = future_map[future]
                try:
                    self._payload_cache[company] = future.result()
                except Exception:
                    self._payload_cache[company] = []

    def _fetch_payloads(self, company: str) -> list[dict]:
        company = (company or "").strip()
        if not company:
            return []
        if company not in self._payload_cache:
            self._payload_cache[company] = self._fetch_company(company)
        return self._payload_cache[company]

    def enrich(
        self,
        event: Event,
        registry: ListedCompanyRegistry,
        as_of: datetime | None = None,
    ) -> list[EventSecurity]:
        if event.country != "KR" or event.event_type != "IPO_LISTING" or not registry:
            return []
        if self.mock_payloads is None and (not self.api_key_id or not self.api_key):
            return []

        cutoff = as_of or datetime.now()
        ipo_company = (event.primary_company or "").strip()
        if not ipo_company:
            return []

        by_ticker: dict[str, EventSecurity] = {}
        for payload in self._fetch_payloads(ipo_company):
            for item in payload.get("items", []):
                published = _parse_pubdate(item.get("pubDate", ""))
                if published is not None and published > cutoff:
                    continue
                title = _clean_text(item.get("title", ""))
                description = _clean_text(item.get("description", ""))
                combined = f"{title}. {description}".strip()
                source_url = item.get("originallink") or item.get("link") or ""

                clauses = [
                    clause.strip()
                    for clause in re.split(r"[.!?。！？…]+", combined)
                    if clause.strip()
                ]
                for clause in clauses:
                    # Korean case particles can immediately follow the IPO name, so the
                    # target issuer uses an exact substring. Related listed companies
                    # still use the registry's stricter token-boundary matching.
                    if ipo_company not in clause:
                        continue
                    relation = _relation_for_clause(clause)
                    if relation is None:
                        continue
                    relation_type, score = relation

                    for related_company, ticker in registry.mentioned_companies(clause):
                        if related_company == ipo_company:
                            continue
                        candidate = EventSecurity(
                            event_id=event.event_id,
                            ticker=ticker,
                            relation_grade="B",
                            relation_score=score,
                            relation_type=relation_type,
                            evidence_text=(
                                f"{related_company}: {clause}"
                                + (f" | {source_url}" if source_url else "")
                            ),
                        )
                        current = by_ticker.get(ticker)
                        if current is None or candidate.relation_score > current.relation_score:
                            by_ticker[ticker] = candidate

        return sorted(by_ticker.values(), key=lambda row: row.relation_score, reverse=True)
