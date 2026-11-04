"""Explainable monitoring priority and dated market observations, never forecasts."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from event_radar.models import Event, EventSecurity


def market_snapshot(prices: pd.DataFrame, as_of: date) -> dict | None:
    if prices.empty or 'date' not in prices:
        return None
    frame = prices.copy()
    frame['date'] = pd.to_datetime(frame['date']).dt.date
    frame = frame[frame['date'] <= as_of].sort_values('date').drop_duplicates('date')
    column = 'adj_close' if 'adj_close' in frame else 'close'
    if column not in frame:
        return None
    frame[column] = pd.to_numeric(frame[column], errors='coerce')
    frame = frame[np.isfinite(frame[column]) & (frame[column] > 0)]
    if len(frame) < 21 or (as_of - frame.iloc[-1]['date']).days > 7:
        return None
    latest = frame.iloc[-1]
    volume_ratio = None
    if 'volume' in frame:
        prior_volume = pd.to_numeric(frame.iloc[-21:-1]['volume'], errors='coerce').mean()
        if prior_volume > 0 and pd.notna(latest['volume']):
            volume_ratio = round(float(latest['volume']) / prior_volume, 3)
    return dict(as_of=latest['date'].isoformat(), price=round(float(latest[column]), 4),
                return_20d=round(float(latest[column]) / float(frame.iloc[-21][column]) - 1, 6),
                volume_ratio_20d=volume_ratio, sessions=len(frame), source='Yahoo Finance')


def build_insight(event: Event, securities: list[EventSecurity], today: date,
                  coverage: dict, summary, market: dict | None) -> dict:
    """Fixed maxima; no redistribution or bonus points for unavailable inputs."""
    reasons, missing = [], []
    official = event.source_kind in {'REGULATOR', 'EXCHANGE', 'COMPANY', 'ORGANIZER'}
    precision = {'EXACT_DATE':8, 'WEEK':6, 'MONTH':4, 'QUARTER':2, 'HALF_YEAR':1, 'YEAR':0}.get(event.date_precision, 0)
    schedule = min(30, {'CONFIRMED':18, 'EXPECTED':10, 'RUMORED':2}.get(event.status, 0) + precision + (4 if official else 1))
    reasons.append(('공식 일정' if official else '기사 기반 일정') + (' · 날짜 확정' if event.date_precision == 'EXACT_DATE' else ' · 기간형 일정'))
    direct = [s for s in securities if s.ticker and s.relation_grade == 'A']
    economic = [s for s in securities if s.ticker and s.relation_grade == 'B']
    themes = [s for s in securities if s.ticker and s.relation_grade == 'THEME']
    relation = (25 if official else 21) if direct else 20 if economic else 6 if themes else 3 if any(s.relation_grade == 'PROXY' for s in securities) else 0
    reasons.append(f'직접 {len(direct)}개 · 경제관계 {len(economic)}개' if direct or economic else '검증된 개별 관련주 부족')
    if not direct and not economic:
        missing.append('검증된 개별 관련주')
    n = coverage.get('complete_events', 0)
    confidence = 'NONE' if n == 0 else 'LIMITED' if n < 3 else 'DEVELOPING' if n < 8 else 'SUPPORTED'
    history = min(5, n * 2) if n < 3 else min(20, n * 2 + 4)
    if n >= 3 and summary is not None:
        history += min(5, max(0, round(float(summary.median_abnormal_return) * 30 + (float(summary.win_rate) - .5) * 4)))
    history = min(25, history)
    reasons.append(f'D+5 완료 사건 {n}건' + (' · 소표본' if 0 < n < 3 else ''))
    if n < 3:
        missing.append('충분한 과거 사건 표본')
    if market:
        try:
            age_days = (today - date.fromisoformat(market['as_of'])).days
        except (KeyError, TypeError, ValueError):
            age_days = -1
        if not 0 <= age_days <= 7:
            market = None
    market_points = 0
    if market:
        market_points = 10 if market['volume_ratio_20d'] is not None else 7
        if market['return_20d'] > .2:
            market_points = max(0, market_points - 5)
            reasons.append('최근 20거래일 20% 이상 상승 · 급등 부담')
    else:
        missing.append('최근 가격·거래량')
    start = event.window_start or event.event_date
    end = event.window_end or event.event_date
    days = (max(start, today) - today).days
    age = (today - event.announced_at.date()).days
    timing = (8 if days <= 7 else 6 if days <= 30 else 3 if days <= 90 else 1) + (2 if age <= 7 else 1 if age <= 30 else 0)
    components = dict(schedule=dict(label='일정 신뢰도', points=schedule, max=30),
        relation=dict(label='관련주 근거', points=relation, max=25),
        history=dict(label='과거 비교 근거', points=history, max=25),
        market=dict(label='현재 가격 관측', points=market_points, max=10),
        timing=dict(label='일정 접근·신선도', points=timing, max=10))
    score = sum(c['points'] for c in components.values())
    past = end < today or event.status == 'CANCELLED'
    if past:
        score = 0
    tier = 'PAST' if past else 'FOCUS' if score >= 65 and n >= 3 and (direct or economic) else 'WATCH' if direct or economic or any(s.relation_grade == 'PROXY' for s in securities) else 'CHECK'
    label = {'FOCUS':'근거 충실', 'WATCH':'일정 관찰', 'CHECK':'추가 확인', 'PAST':'지난 일정'}[tier]
    return dict(score=score, tier=tier, label=label, components=components, reasons=reasons, missing=missing,
                history_confidence=confidence, market=market, coverage=coverage,
                methodology='관찰 우선순위이며 매수 추천이나 수익 확률이 아닙니다. 미확인 항목에는 점수를 부여하지 않습니다.')
