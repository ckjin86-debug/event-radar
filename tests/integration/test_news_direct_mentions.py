from datetime import date, datetime
import json

import pandas as pd

from event_radar.entities import EntityUniverse, SecurityMention
from event_radar.models import RawEvent
from event_radar.pipeline import PipelineConfig, run_pipeline


class DescriptionParentCollector:
    source_name = "NEWS_FUTURE"

    def collect(self, since: datetime) -> list[RawEvent]:
        return [
            RawEvent(
                source_name="NEWS_FUTURE",
                source_kind="SECONDARY",
                source_event_uid="NEWS_PARENT_01",
                source_url="https://example.com/news/parent",
                country="KR",
                primary_ticker="^KS11",
                primary_company="롯데바이오로직스",
                event_type="CAPEX",
                event_name="롯데바이오로직스, 11월 송도 공장 준공 예정",
                announced_at=datetime(2026, 11, 2),
                event_date=date(2026, 11, 1),
                date_precision="MONTH",
                window_start=date(2026, 11, 1),
                window_end=date(2026, 11, 30),
                status="EXPECTED",
                evidence_text="롯데바이오로직스, 11월 송도 공장 준공 예정. 롯데지주 계열 바이오 사업 확대.",
            )
        ]


def test_short_parent_name_does_not_match_unlisted_subsidiary_prefix():
    universe = EntityUniverse([
        SecurityMention(company_name="LG", ticker="003550", country="KR"),
    ])

    assert universe.resolve_mentions("LG CNS, 인니 데이터센터 내달 준공", "KR") == []
    assert [m.ticker for m in universe.resolve_mentions("LG, 내년 투자계획 발표", "KR")] == ["003550"]


def test_news_description_only_parent_is_not_grade_a_direct_issuer(tmp_path):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    config_dir = tmp_path / "config"
    (data_dir / "canonical").mkdir(parents=True)
    (data_dir / "derived").mkdir(parents=True)
    (site_dir / "data").mkdir(parents=True)
    config_dir.mkdir(parents=True)

    universe = EntityUniverse([
        SecurityMention(company_name="롯데지주", ticker="004990", country="KR"),
    ])
    run_pipeline(
        collectors=[DescriptionParentCollector()],
        config=PipelineConfig(
            data_dir=data_dir,
            site_dir=site_dir,
            config_dir=config_dir,
            entity_universe=universe,
        ),
        now=datetime(2026, 11, 2, 10, 0),
        skip_price_fetch=True,
    )

    mapped = pd.read_csv(data_dir / "derived" / "event_security_map.csv", dtype={"ticker": str})
    assert mapped.empty
    events = json.loads((site_dir / "data" / "events.json").read_text(encoding="utf-8"))
    assert events == []
