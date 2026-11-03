from event_radar.collectors.news_future import classify_catalyst


def test_classify_expanded_high_signal_future_catalysts():
    assert classify_catalyst("현대차, 내년 양산 시작 예정") == "PLANT_OPERATION"
    assert classify_catalyst("LG에너지솔루션, 내년 공장 준공 예정") == "CAPEX"
    assert classify_catalyst("바이오기업, 12월 FDA 결정 예정") == "APPROVAL"
    assert classify_catalyst("제약사, 내년 1분기 임상 톱라인 발표 예정") == "CLINICAL_RESULT"
