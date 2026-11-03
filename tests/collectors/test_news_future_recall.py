from event_radar.collectors.news_future import DEFAULT_QUERIES


def test_default_queries_cover_high_impact_scheduled_catalysts_without_listing_noise():
    queries = set(DEFAULT_QUERIES)

    required = {
        "착공 예정",
        "상업 가동 예정",
        "양산 시작 예정",
        "증설 예정",
        "준공 예정",
        "선고 예정",
        "승인 결정 예정",
        "FDA 결정 예정",
        "임상 결과 발표",
        "톱라인 발표 예정",
        "인수 완료 예정",
        "인수 마무리 예정",
        "합병 완료 예정",
        "입찰 결과 예정",
        "공급계약 예정",
    }
    assert required.issubset(queries)
    assert not any("상장" in query for query in queries)
