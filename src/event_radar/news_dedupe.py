"""Semantic duplicate merging for NEWS_FUTURE events.

The news collector clusters articles by (extracted company, type, window),
so the same real-world schedule still lands as several canonical events
whenever outlets phrase the headline differently or the company extraction
differs between articles. This module merges those duplicates at pipeline
stage — conservatively, so two genuinely different schedules of the same
company are never collapsed:

- candidates are AUTO NEWS_FUTURE events only (manual rows are never
  absorbed, review-flagged rows are left alone);
- two events merge only when they share the event type, their windows
  overlap or start within 45 days, and their headline token sets are
  similar *and* share a distinctive (non-generic, non-catalyst) token —
  or are near-identical (similarity >= 0.6) on their own;
- the representative is the most informative survivor (highest date
  precision, then longest evidence); absorbed events keep their provenance
  as ``duplicate_merged`` revisions on the representative instead of
  disappearing silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from event_radar.models import Event, EventRevision


# Tokens that say nothing about *which* schedule a headline describes:
# function words, reporting filler, and the catalyst vocabulary itself
# (착공/가동/인수/출시 appear in every headline of that event type).
GENERIC_TOKENS = {
    "예정", "발표", "관련", "소식", "뉴스", "단독", "종합", "인터뷰", "기사",
    "기자", "추진", "계획", "검토", "밝혀", "따르면", "위해", "대한", "이번",
    "내년", "올해", "금년", "연내", "이달", "다음달", "내달", "상반기",
    "하반기", "분기", "가동", "착공", "공장", "생산", "라인", "인수", "합병",
    "계약", "수주", "공급", "출시", "공개", "신제품", "신작", "임상", "결과",
    "승인", "허가", "시설투자", "설비투자", "증설", "투자", "규모", "사업",
    "진행", "완료", "시작", "확대", "확정", "일정", "에서", "으로", "까지",
    "부터", "이다", "한다", "된다", "있다", "것으로", "것이다",
}

WINDOW_PROXIMITY_DAYS = 45
SIMILARITY_THRESHOLD = 0.34
WINDOW_BUCKET_SIMILARITY = 0.40
NEAR_IDENTICAL_SIMILARITY = 0.60

_PRECISION_RANK = {
    "EXACT_DATE": 5,
    "WEEK": 4,
    "MONTH": 3,
    "QUARTER": 2,
    "HALF_YEAR": 1,
    "YEAR": 0,
}


@dataclass
class NewsDedupeResult:
    events: list[Event]
    revisions: list[EventRevision] = field(default_factory=list)
    clusters_merged: int = 0
    events_absorbed: int = 0


def normalize_title_tokens(name: str) -> set[str]:
    """Tokenize a headline for similarity checks (bracket tags dropped)."""
    text = re.sub(r"\[[^\]]+\]", " ", name or "")
    text = re.sub(r"[^0-9A-Za-z가-힣 ]", " ", text)
    return {token for token in text.split() if len(token) >= 2}


def company_key(company: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", company or "").lower()


def title_similarity(a: str, b: str) -> float:
    tokens_a, tokens_b = normalize_title_tokens(a), normalize_title_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _distinctive_shared(a: Event, b: Event) -> set[str]:
    """Shared headline tokens that identify the specific schedule."""
    shared = normalize_title_tokens(a.event_name) & normalize_title_tokens(b.event_name)
    keys = {company_key(a.primary_company), company_key(b.primary_company)}
    return {
        token
        for token in shared
        if token not in GENERIC_TOKENS and token.lower() not in keys
    }


def _distinctive_only(tokens: set[str], other: set[str], keys: set[str]) -> set[str]:
    """Distinctive tokens present on one side only and unexplained by the other.

    A token is explained when the other headline carries it as a substring
    variant (의향서 vs 인수의향서) — outlets split compound words differently.
    Date-like tokens (11월, 9일, 4주간) never identify a schedule.
    """
    result = set()
    for token in tokens:
        if token in GENERIC_TOKENS or token.lower() in keys:
            continue
        if any(char.isdigit() for char in token):
            continue
        if any(token in other_token or other_token in token for other_token in other):
            continue
        result.add(token)
    return result


def _has_conflicting_tokens(a: Event, b: Event) -> bool:
    """True when each headline names a different specific (평택 vs 화성 공장)."""
    tokens_a = normalize_title_tokens(a.event_name)
    tokens_b = normalize_title_tokens(b.event_name)
    keys = {company_key(a.primary_company), company_key(b.primary_company)}
    return bool(
        _distinctive_only(tokens_a - tokens_b, tokens_b, keys)
        or _distinctive_only(tokens_b - tokens_a, tokens_a, keys)
    )


def _windows_close(a: Event, b: Event) -> bool:
    a_start, a_end = a.window_start or a.event_date, a.window_end or a.event_date
    b_start, b_end = b.window_start or b.event_date, b.window_end or b.event_date
    if a_start <= b_end and b_start <= a_end:
        return True
    return abs((a_start - b_start).days) <= WINDOW_PROXIMITY_DAYS


def _is_merge_candidate(ev: Event) -> bool:
    return (
        ev.source_name == "NEWS_FUTURE"
        and ev.ingest_mode == "AUTO"
        and not ev.needs_review
        and ev.status != "CANCELLED"
    )


def _pairwise_mergeable(a: Event, b: Event, *, window_bucket: bool) -> bool:
    if a.event_type != b.event_type:
        return False
    if not _windows_close(a, b):
        return False
    similarity = title_similarity(a.event_name, b.event_name)
    threshold = WINDOW_BUCKET_SIMILARITY if window_bucket else SIMILARITY_THRESHOLD
    if similarity < threshold:
        return False
    if similarity >= NEAR_IDENTICAL_SIMILARITY:
        # Near-identical wording merges on its own — unless each side names
        # a different specific (another plant, city, or product), which
        # means two distinct schedules with parallel headline templates.
        return not _has_conflicting_tokens(a, b)
    return bool(_distinctive_shared(a, b))


class _UnionFind:
    def __init__(self, ids: Iterable[str]) -> None:
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _representative_key(ev: Event) -> tuple[int, int, float, str]:
    """Most informative survivor first: precision, evidence, earliest report."""
    return (
        _PRECISION_RANK.get(ev.date_precision, 0),
        len(ev.evidence_text or ""),
        -ev.announced_at.timestamp(),
        ev.event_id,
    )


def merge_duplicate_news_events(
    events: list[Event],
    existing_revisions: Iterable[EventRevision] = (),
    now: Optional[datetime] = None,
) -> NewsDedupeResult:
    """Merge duplicate AUTO news events, keeping provenance as revisions."""
    if now is None:
        now = datetime.now()

    candidates = [ev for ev in events if _is_merge_candidate(ev)]
    if len(candidates) < 2:
        return NewsDedupeResult(events=list(events))

    union_find = _UnionFind(ev.event_id for ev in candidates)
    by_id = {ev.event_id: ev for ev in candidates}

    buckets: dict[tuple, list[Event]] = {}
    for ev in candidates:
        key_company = company_key(ev.primary_company)
        if key_company:
            buckets.setdefault((ev.event_type, "company", key_company), []).append(ev)
        if ev.primary_ticker:
            buckets.setdefault((ev.event_type, "ticker", ev.primary_ticker), []).append(ev)
        window = (
            (ev.window_start or ev.event_date).isoformat(),
            (ev.window_end or ev.event_date).isoformat(),
        )
        buckets.setdefault((ev.event_type, "window", window), []).append(ev)

    for (event_type, kind, _), group in buckets.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if union_find.find(a.event_id) != union_find.find(b.event_id) and _pairwise_mergeable(
                    a, b, window_bucket=(kind == "window")
                ):
                    union_find.union(a.event_id, b.event_id)

    clusters: dict[str, list[Event]] = {}
    for ev in candidates:
        clusters.setdefault(union_find.find(ev.event_id), []).append(ev)

    absorbed_ids: set[str] = set()
    new_revisions: list[EventRevision] = []
    known_merges = {
        (r.event_id, r.old_value)
        for r in existing_revisions
        if r.field_name == "duplicate_merged"
    }
    next_rev: dict[str, int] = {}
    for r in existing_revisions:
        next_rev[r.event_id] = max(next_rev.get(r.event_id, 0), r.revision_no)

    representatives: dict[str, Event] = {}
    clusters_merged = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        clusters_merged += 1
        ordered = sorted(members, key=_representative_key, reverse=True)
        representative = ordered[0]
        # Fill a missing primary anchor from the strongest absorbed copy
        # instead of dropping the only article that carried a ticker.
        if not representative.primary_ticker:
            for absorbed in ordered[1:]:
                if absorbed.primary_ticker:
                    representative = representative.model_copy(
                        update={
                            "primary_ticker": absorbed.primary_ticker,
                            "primary_company": absorbed.primary_company or representative.primary_company,
                        }
                    )
                    break
        representatives[representative.event_id] = representative
        for absorbed in ordered[1:]:
            absorbed_ids.add(absorbed.event_id)
            if (representative.event_id, absorbed.event_id) in known_merges:
                continue
            known_merges.add((representative.event_id, absorbed.event_id))
            next_rev[representative.event_id] = next_rev.get(representative.event_id, 0) + 1
            new_revisions.append(
                EventRevision(
                    event_id=representative.event_id,
                    revision_no=next_rev[representative.event_id],
                    changed_at=now,
                    field_name="duplicate_merged",
                    old_value=absorbed.event_id,
                    new_value=absorbed.source_url,
                    source_url=absorbed.source_url,
                    change_reason=f"동일 사건 뉴스 중복 병합: {absorbed.event_name}",
                )
            )

    merged_events = [
        representatives.get(ev.event_id, ev)
        for ev in events
        if ev.event_id not in absorbed_ids
    ]
    return NewsDedupeResult(
        events=merged_events,
        revisions=new_revisions,
        clusters_merged=clusters_merged,
        events_absorbed=len(absorbed_ids),
    )
