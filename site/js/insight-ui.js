/** Evidence explanations shared by dashboard and detail. */
function renderPriorityCell(event) {
  const i = event.insight;
  if (!i) return `<span>${event.event_score || 0}</span>`;
  return `<div class="priority-cell"><span class="priority-number">${i.score}</span>
    <span class="priority-tier tier-${escapeHtml(i.tier.toLowerCase())}">${escapeHtml(i.label)}</span>
    ${i.missing.length ? `<small title="${escapeHtml(i.missing.join(' · '))}">보완 ${i.missing.length}개 · ${escapeHtml(i.missing[0])}</small>` : '<small>핵심 근거 확보</small>'}</div>`;
}

function renderDashboardSummary(events) {
  const container = document.getElementById('radarOverview');
  if (!container) return;
  const active = events.filter(e=>e.insight?.tier !== 'PAST');
  const stats = [[active.length,'관찰 중인 일정'],[active.filter(e=>e.insight?.coverage?.complete_events > 0).length,'과거 D+5 비교 가능'],
    [active.filter(e=>e.insight?.market).length,'현재 가격 관측'],[active.filter(e=>e.insight?.tier==='CHECK').length,'관련주 추가 확인']];
  container.innerHTML = stats.map(([n,label])=>`<div class="overview-stat"><strong>${n}</strong><span>${label}</span></div>`).join('');
}

function renderDetailInsight(d) {
  const i = d.insight;
  const container = document.getElementById('decisionInsight');
  if (!i || !container) return;
  const m = i.market;
  const c = i.coverage || {};
  const confidence = {NONE:'비교 표본 없음',LIMITED:'소표본 · 참고용',DEVELOPING:'표본 축적 중',SUPPORTED:'과거 비교 근거 확보'}[i.history_confidence];
  container.innerHTML = `<div class="decision-top"><div><span class="eyebrow">관찰 우선순위</span><h2>${i.score}<small>/100</small> <span class="priority-tier tier-${escapeHtml(i.tier.toLowerCase())}">${escapeHtml(i.label)}</span></h2></div><p>${escapeHtml(i.methodology)}</p></div>
    <div class="evidence-dimensions">${Object.values(i.components).map(x=>`<div><span>${escapeHtml(x.label)}</span><strong>${x.points}<small> / ${x.max}</small></strong><progress value="${x.points}" max="${x.max}"></progress></div>`).join('')}</div>
    <div class="decision-reasons">${i.reasons.map(r=>`<span>${escapeHtml(r)}</span>`).join('')}</div>
    ${i.missing.length ? `<p class="data-gaps"><strong>추가로 필요한 근거</strong> ${escapeHtml(i.missing.join(' · '))}</p>` : ''}
    <div class="study-coverage"><strong>${escapeHtml(confidence)}</strong><span>비교 대상 ${c.eligible_events || 0}건 → 가격 확보 ${c.priced_events || 0}건 → D+5 완료 ${c.complete_events || 0}건 / 종목 표본 ${c.security_samples || 0}개</span>
      ${c.not_calculated_events ? `<span>계산 미완료 ${c.not_calculated_events}건: 가격 또는 기준일 데이터 보완 필요</span>` : ''}</div>
    <div class="market-observation"><strong>현재 가격 관측</strong>${m ? `<span>${escapeHtml(m.ticker || d.ticker)} · 조정종가 ${Number(m.price).toLocaleString('ko-KR')}</span><span>최근 20거래일 ${pct(m.return_20d)} · 거래량 ${m.volume_ratio_20d == null ? '미확인' : m.volume_ratio_20d.toFixed(2)+'배'}</span><small>${escapeHtml(m.as_of)} 종가 기준 · ${escapeHtml(m.source)} · 과거 백테스트와 별도 관측</small>` : '<span>최근 21거래일 이상의 유효 가격을 확보하지 못했습니다.</span>'}</div>`;
}

function renderOutcomeTable(peer, proxy) {
  if (!peer.outcomes?.length) return '';
  return `<div class="peer-outcomes"><table><thead><tr><th>종목</th><th>D+5</th><th>${proxy ? '시장 반응' : '시장 대비'}</th><th>D+20</th></tr></thead><tbody>${peer.outcomes.map(s=>`<tr><td><code>${escapeHtml(s.ticker)}</code></td><td>${s.return_d5 == null ? '미완료' : pct(s.return_d5)}</td><td>${proxy ? '지수 자체 관측' : s.abnormal_d5 == null ? '—' : pct(s.abnormal_d5)}</td><td>${s.return_d20 == null ? '미완료' : pct(s.return_d20)}</td></tr>`).join('')}</tbody></table></div>`;
}
