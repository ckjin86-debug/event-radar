from datetime import datetime

from event_radar.collectors.historical_seed import HistoricalSeedCollector


def test_historical_seed_collector_loads_old_events_even_when_since_is_recent(tmp_path):
    path = tmp_path / "historical_events.csv"
    path.write_text(
        "source_event_uid,country,primary_ticker,primary_company,event_type,event_name,announced_at,event_date,status,evidence_text,source_url\n"
        "seed-1,KR,180640,한진칼,CONTROL_DISPUTE,한진칼 경영권 분쟁 주총 표대결,2020-03-27,2020-03-27,CONFIRMED,주총 표대결 결과,https://example.com/hanjin\n",
        encoding="utf-8",
    )
    collector = HistoricalSeedCollector(config_path=path)

    rows = collector.collect(since=datetime(2026, 11, 1))

    assert len(rows) == 1
    assert rows[0].source_name == "HISTORICAL_SEED"
    assert rows[0].primary_ticker == "180640"
    assert rows[0].event_type == "CONTROL_DISPUTE"
    assert str(rows[0].event_date) == "2020-03-27"
