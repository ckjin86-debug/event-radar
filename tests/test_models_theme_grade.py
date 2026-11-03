from event_radar.models import EventSecurity


def test_event_security_accepts_theme_grade():
    row = EventSecurity(
        event_id="e1",
        ticker="053290",
        relation_grade="THEME",
        relation_score=38,
        relation_type="POLITICAL_THEME",
        evidence_text="market narrative",
    )
    assert row.relation_grade == "THEME"
