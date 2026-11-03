"""Domain models for Event Radar."""

from __future__ import annotations
from datetime import date, datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


CountryType = Literal["KR", "US"]
EventTimeContext = Literal["PREMARKET", "INTRADAY", "AFTERHOURS", "DATE_ONLY"]
EventStatus = Literal["CONFIRMED", "EXPECTED", "RUMORED", "CANCELLED"]
SourceKind = Literal["REGULATOR", "EXCHANGE", "COMPANY", "ORGANIZER", "SECONDARY"]
IngestMode = Literal["AUTO", "MANUAL", "AUTO+MANUAL"]
RelationGrade = Literal["A", "B", "C"]
DatePrecision = Literal["EXACT_DATE", "WEEK", "MONTH", "QUARTER", "HALF_YEAR", "YEAR"]


class RawEvent(BaseModel):
    """Raw event collected from providers or submitted manually."""

    source_name: str
    source_kind: SourceKind = "REGULATOR"
    source_event_uid: Optional[str] = None
    source_url: str = ""
    country: str
    primary_ticker: str
    primary_company: str
    event_type: str
    event_name: str
    announced_at: datetime | date | str
    event_date: date | str
    date_precision: DatePrecision = "EXACT_DATE"
    window_start: date | str | None = None
    window_end: date | str | None = None
    event_time_context: EventTimeContext = "DATE_ONLY"
    status: EventStatus = "CONFIRMED"
    evidence_text: str = ""
    ingest_mode: IngestMode = "AUTO"
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country", mode="before")
    @classmethod
    def clean_country(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.strip().upper()
            if v in ("KR", "US"):
                return v
        return "KR"

    @field_validator("primary_ticker", mode="before")
    @classmethod
    def clean_ticker(cls, v: Any) -> str:
        return str(v).strip().upper() if v is not None else ""

    @field_validator("event_type", mode="before")
    @classmethod
    def clean_event_type(cls, v: Any) -> str:
        return str(v).strip().upper() if v is not None else ""


class Event(BaseModel):
    """Canonical event model matching data/canonical/events.csv."""

    event_id: str
    country: CountryType
    event_type: str
    event_name: str
    primary_ticker: str
    primary_company: str
    announced_at: datetime
    event_date: date
    date_precision: DatePrecision = "EXACT_DATE"
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    event_time_context: EventTimeContext = "DATE_ONLY"
    status: EventStatus = "CONFIRMED"
    source_kind: SourceKind = "REGULATOR"
    source_name: str
    source_url: str = ""
    source_event_uid: Optional[str] = None
    evidence_text: str = ""
    ingest_mode: IngestMode = "AUTO"
    first_seen_at: datetime
    last_seen_at: datetime
    needs_review: bool = False


class EventRevision(BaseModel):
    """Record of changes to an event matching data/canonical/event_revisions.csv."""

    event_id: str
    revision_no: int
    changed_at: datetime
    field_name: str
    old_value: str
    new_value: str
    source_url: str = ""
    change_reason: str = ""


class Security(BaseModel):
    """Traded security metadata matching data/canonical/securities.csv."""

    ticker: str
    company_name: str
    country: CountryType
    exchange: str
    currency: str
    benchmark_ticker: str
    active_from: Optional[date] = None
    active_to: Optional[date] = None


class Relation(BaseModel):
    """Economic relationship between entities matching data/canonical/relations.csv."""

    relation_id: str
    from_entity: str
    to_ticker: str
    relation_type: str
    relation_grade: RelationGrade
    relation_score: int = Field(ge=0, le=100)
    relation_known_date: date
    relation_start_date: date
    relation_end_date: Optional[date] = None
    evidence_source: str = ""
    source_url: str = ""
    ingest_mode: IngestMode = "AUTO"


class EventSecurity(BaseModel):
    """Mapped event to security relationship for backtesting and display."""

    event_id: str
    ticker: str
    relation_grade: RelationGrade
    relation_score: int
    relation_type: str
    evidence_text: str = ""
