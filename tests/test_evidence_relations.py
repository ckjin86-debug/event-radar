from datetime import date, datetime

from event_radar.models import Event
from event_radar.entity_resolver import ListedCompanyRegistry


def article(text, when=datetime(2026, 10, 30)):
    return Event(event_id='article', country='KR', primary_company='한빛전자', primary_ticker='',
        event_type='CONTRACT', event_name=text, evidence_text=text, announced_at=when,
        event_date=date(2026, 12, 1), source_name='NEWS_FUTURE', source_url='https://example.com/fact',
        first_seen_at=when, last_seen_at=when)


def test_explicit_economic_pair_keeps_quote_url_and_known_date():
    from event_radar.evidence_relations import discover_relations
    registry = ListedCompanyRegistry({'한빛전자':'111111', '대한소재':'222222'})
    relations = discover_relations([article('한빛전자는 대한소재와 소재 공급 계약을 체결했다')], registry, date(2026, 11, 3))
    assert {(r.from_entity, r.to_ticker, r.relation_grade) for r in relations} == {('111111', '222222', 'B'), ('222222', '111111', 'B')}
    assert all(r.source_url == 'https://example.com/fact' and r.relation_known_date == date(2026, 10, 30) for r in relations)


def test_speculative_unconnected_or_ambiguous_mentions_do_not_become_relations():
    from event_radar.evidence_relations import discover_relations
    registry = ListedCompanyRegistry({'한빛전자':'111111', '대한소재':'222222', '새빛산업':'333333'})
    for text in ['한빛전자는 대한소재와 공급 계약을 검토 중이다',
                 '한빛전자는 대한소재와 공급 계약을 체결하지 않았다',
                 '한빛전자는 고객사에 공급 계약을 체결했다, 경쟁사 대한소재도 상승',
                 '한빛전자는 대한소재에 소송을 제기했고, 미국 법인과 공급 계약을 체결했다',
                 '한빛전자·대한소재·새빛산업 공급 계약 체결',
                 '한빛전자와 대한소재가 공급 계약 체결 가능성을 부인했다']:
        assert discover_relations([article(text)], registry, date(2026, 11, 3)) == []


def test_future_article_cannot_become_historical_relationship():
    from event_radar.evidence_relations import discover_relations
    registry = ListedCompanyRegistry({'한빛전자':'111111', '대한소재':'222222'})
    assert discover_relations([article('한빛전자는 대한소재와 공급 계약을 체결했다', datetime(2026, 11, 5))], registry, date(2026, 11, 3)) == []


def test_body_only_company_is_context_not_direct_participant():
    event = article('한빛전자, 신규 라인 가동')
    event.evidence_text += '. 업계 비교 대상으로 대한소재도 언급됐다'
    rows = ListedCompanyRegistry({'한빛전자':'111111', '대한소재':'222222'}).resolve_mentions(event)
    assert next(s for s in rows if s.ticker == '111111').relation_grade == 'A'
    assert next(s for s in rows if s.ticker == '222222').relation_grade == 'THEME'

def test_secondary_headline_mention_is_context():
    event = article('한빛전자 신규 라인 가동, 비교 대상으로 대한소재도 언급')
    rows = ListedCompanyRegistry({'한빛전자':'111111', '대한소재':'222222'}).resolve_mentions(event)
    assert {s.ticker: s.relation_grade for s in rows} == {'111111': 'A', '222222': 'THEME'}
