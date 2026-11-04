/**
 * Detailed event view controller.
 */

async function initEventDetail() {
  const params = new URLSearchParams(window.location.search);
  const eventId = params.get("id");

  if (!eventId) {
    document.getElementById("detailContainer").innerHTML = `
      <div class="card" style="text-align: center; color: #f87171;">
        이벤트 ID가 제공되지 않았습니다. <br><br>
        <a href="index.html" class="row-link">← 목록으로 돌아가기</a>
      </div>
    `;
    return;
  }

  try {
    const resp = await fetch("data/event_details.json");
    if (!resp.ok) throw new Error("Failed to load event_details.json");
    const allDetails = await resp.json();
    const detail = allDetails[eventId];

    if (!detail) {
      document.getElementById("detailContainer").innerHTML = `
        <div class="card" style="text-align: center; color: #f87171;">
          해당 ID(${escapeHtml(eventId)})의 이벤트를 찾을 수 없습니다. <br><br>
          <a href="index.html" class="row-link">← 목록으로 돌아가기</a>
        </div>
      `;
      return;
    }

    renderDetail(detail);
  } catch (err) {
    console.error("Detail error:", err);
    document.getElementById("detailContainer").innerHTML = `
      <div class="card" style="text-align: center; color: #f87171;">
        상세 정보를 불러오는 중 오류가 발생했습니다: ${err.message}
      </div>
    `;
  }
}

function formatEventDate(d) {
  const precision = d.date_precision || "EXACT_DATE";
  const start = d.window_start || d.event_date;
  const end = d.window_end || d.event_date;

  if (precision === "EXACT_DATE" || !start || !end) return d.event_date || start || "-";

  const startDate = new Date(`${start}T00:00:00`);
  const year = startDate.getFullYear();
  const month = startDate.getMonth() + 1;

  if (precision === "MONTH") return `${year}년 ${month}월 (${start} ~ ${end})`;
  if (precision === "QUARTER") return `${year}년 ${Math.floor((month - 1) / 3) + 1}분기 (${start} ~ ${end})`;
  if (precision === "HALF_YEAR") return `${year}년 ${month <= 6 ? "상반기" : "하반기"} (${start} ~ ${end})`;
  if (precision === "YEAR") return `${year}년 내 (${start} ~ ${end})`;
  return start === end ? start : `${start} ~ ${end}`;
}

function relationBadgeClass(grade) {
  if (grade === "A") return "badge-a";
  if (grade === "B") return "badge-b";
  if (grade === "THEME") return "badge-theme";
  return "badge-unmapped";
}

function pct(value, digits = 1) {
  return `${((value || 0) * 100).toFixed(digits)}%`;
}

function renderBacktestVerdict(d) {
  const elem = document.getElementById("backtestVerdict");
  if (!elem) return;

  const peerN = d.peer_sample_n || 0;
  const d5N = d.d5_sample_n || 0;
  const bs = d.backtest_summary || {};
  const completed = d.insight?.coverage?.complete_events || bs.event_n || 0;

  if (peerN === 0) {
    elem.className = "backtest-verdict neutral";
    elem.innerHTML = `<strong>비교 가능한 과거 사례가 아직 없습니다.</strong><span>동일 국가·유형·관계등급의 정확한 날짜와 실제 주가가 있는 사례만 비교합니다. 데이터 없음은 수익률 0%를 뜻하지 않습니다.</span>`;
    return;
  }

  if (d5N === 0) {
    elem.className = "backtest-verdict caution";
    elem.innerHTML = `<strong>과거 비교 사례 ${peerN}건 · D+5 완료 표본 없음</strong><span>비교 사례는 있지만 아직 이벤트 후 5거래일까지 데이터가 완성되지 않아 D+5 성과는 판단하지 않습니다.</span>`;
    return;
  }

  const edge = bs.mean_abnormal_return || 0;
  if (completed < 3 || d.market_proxy_study) {
    elem.className = 'backtest-verdict caution';
    elem.innerHTML = `<strong>과거 비교 ${peerN}건 · D+5 완료 사건 ${completed}건 / 종목 표본 ${d5N}개</strong><span>${d.market_proxy_study ? '지수 자체의 과거 반응입니다. 개별 관련주 수익률로 해석하지 않습니다.' : '완료 사건이 3건 미만인 소표본입니다. 방향성 판단에 사용하기에는 근거가 부족합니다.'}</span>`;
    return;
  }
  elem.className = `backtest-verdict ${edge >= 0 ? "positive-verdict" : "negative-verdict"}`;
  elem.innerHTML = `<strong>과거 비교 사례 ${peerN}건 · D+5 종목표본 ${d5N}개</strong><span>D+5 평균 초과수익률 ${pct(edge)} · 승률 ${pct(bs.win_rate, 0)}</span>`;
}

function renderBacktestStats(d) {
  const statsElem = document.getElementById("backtestStats");
  if (!statsElem) return;

  const bs = d.backtest_summary || {};
  const peerN = d.peer_sample_n || 0;
  const d5N = d.d5_sample_n || 0;
  const noD5 = d5N === 0;
  const measuredReturn = d.market_proxy_study ? bs.mean_return : bs.mean_abnormal_return;
  const measuredWin = d.market_proxy_study ? bs.absolute_win_rate : bs.win_rate;

  statsElem.innerHTML = `
    <div class="stat-box"><div class="stat-val">${peerN}건</div><div class="stat-label">비교 가능한 과거 사건</div></div>
    <div class="stat-box"><div class="stat-val">${d5N}개</div><div class="stat-label">D+5 완료 종목 표본</div></div>
    <div class="stat-box"><div class="stat-val ${noD5 ? "muted-value" : ((measuredReturn || 0) >= 0 ? "positive" : "negative")}">${noD5 ? "데이터 없음" : pct(measuredReturn)}</div><div class="stat-label">D+5 ${d.market_proxy_study ? '시장 절대수익률' : '평균 초과수익률'}</div></div>
    <div class="stat-box"><div class="stat-val ${noD5 ? "muted-value" : ((measuredWin || 0) >= 0.5 ? "positive" : "negative")}">${noD5 ? "데이터 없음" : pct(measuredWin, 0)}</div><div class="stat-label">D+5 ${d.market_proxy_study ? '시장 상승 비율' : '초과수익 승률'}</div></div>
  `;
}

function renderHistoricalPeers(d) {
  const container = document.getElementById("historicalPeers");
  if (!container) return;

  const peers = d.historical_peers || [];
  if (peers.length === 0) {
    container.innerHTML = `<div class="history-empty">현재 조건과 일치하는 과거 비교 사례가 없습니다.</div>`;
    return;
  }

  container.innerHTML = peers.map(peer => {
    const securities = peer.related_securities || [];
    const securitiesHtml = securities.length
      ? securities.map(sec => `
          <span class="history-security">
            <code>${escapeHtml(sec.ticker || "-")}</code>
            <span class="badge ${relationBadgeClass(sec.relation_grade)}">${escapeHtml(sec.relation_grade)}</span>
          </span>
        `).join("")
      : `<span class="text-muted">관련주 미매핑</span>`;
    const progress = peer.max_offset >= 5
      ? "D+5 완료"
      : `현재 D${peer.max_offset >= 0 ? "+" : ""}${peer.max_offset}까지`;

    return `
      <article class="history-card peer-card">
        <div class="history-card-top">
          <span class="history-date">${escapeHtml(peer.event_date)}</span>
          <span class="badge badge-country">${escapeHtml(peer.country)}</span>
          <span class="history-progress">${escapeHtml(progress)}</span>
        </div>
        <h3>${escapeHtml(peer.event_name)}</h3>
        <p>${escapeHtml(peer.evidence_text || peer.company || "")}</p>
        <div class="history-securities">${securitiesHtml}</div>
        ${typeof renderOutcomeTable === 'function' ? renderOutcomeTable(peer, d.market_proxy_study) : ''}
        ${peer.source_url ? `<a href="${escapeHtml(peer.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link history-source">사례 근거 ↗</a>` : ""}
      </article>
    `;
  }).join("");
}

function renderBestStrategy(d) {
  const elem = document.getElementById("bestStrategy");
  if (!elem) return;

  const sampled = (d.strategy_summary || []).filter(s => s.sample_n > 0);
  if (sampled.length === 0) {
    elem.innerHTML = `<strong>전략 비교 데이터가 없습니다.</strong><span>과거 표본이 쌓이면 구간별 성과를 비교합니다.</span>`;
    return;
  }

  const metric = d.market_proxy_study ? "mean_return" : "mean_abnormal_return";
  const best = sampled.reduce((a, b) => b[metric] > a[metric] ? b : a);
  const eventN = best.event_n || 0;
  const caution = ` · 사건 ${eventN}건 / 종목 ${best.sample_n}개${eventN < 3 ? ' · 소표본 참고용' : ''}`;
  elem.innerHTML = `
    <div>
      <span class="best-label">가장 좋았던 구간</span>
      <strong>${escapeHtml(best.name)}</strong>
    </div>
    <div class="best-numbers">
      <span>평균 수익률 <strong class="${best.mean_return >= 0 ? "positive" : "negative"}">${pct(best.mean_return)}</strong></span>
      ${d.market_proxy_study ? "" : `<span>시장 대비 <strong class="${best.mean_abnormal_return >= 0 ? "positive" : "negative"}">${pct(best.mean_abnormal_return)}</strong></span>`}
      <span class="text-muted">${escapeHtml(caution)}</span>
    </div>
  `;
}

function renderDetail(d) {
  const tickerLabel = d.ticker || "미매핑";
  document.title = `${d.event_name} | Event Radar`;
  document.getElementById("eventTitle").textContent = d.event_name;
  if (typeof renderDetailInsight === 'function') renderDetailInsight(d);

  const basicInfoElem = document.getElementById("basicInfo");
  if (basicInfoElem) {
    const scheduleContext = (d.date_precision || "EXACT_DATE") === "EXACT_DATE"
      ? d.event_time_context
      : d.date_precision;
    basicInfoElem.innerHTML = `
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
        <div><span class="text-muted">국가 / 관련 티커:</span> <strong>${d.country} / ${escapeHtml(tickerLabel)}</strong></div>
        <div><span class="text-muted">이벤트 유형:</span> <strong>${d.event_type}</strong></div>
        <div><span class="text-muted">${d.source_name === "FED_FOMC" ? "일정 공지일" : "최초 발표일"}:</span> <strong>${d.source_name === "FED_FOMC" ? "미확인" : d.announced_at ? d.announced_at.slice(0, 10) : "-"}</strong></div>
        <div><span class="text-muted">이벤트 예정일:</span> <strong style="color:var(--accent-blue);">${escapeHtml(formatEventDate(d))} (${escapeHtml(scheduleContext)})</strong></div>
        <div><span class="text-muted">확정 상태:</span> <span class="badge ${d.status === 'CONFIRMED' ? 'badge-confirmed' : 'badge-expected'}">${d.status}</span></div>
        <div>
          <span class="text-muted">이벤트 출처:</span>
          ${d.source_url ? `<a href="${escapeHtml(d.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link">${escapeHtml(d.source_name)} ↗</a>` : escapeHtml(d.source_name)}
        </div>
      </div>
      ${d.evidence_text ? `<div style="margin-top: 14px; padding: 10px; background: var(--bg-primary); border-radius: 6px; font-size: 0.85rem; color: #cbd5e1;"><strong>근거:</strong> ${escapeHtml(d.evidence_text)}</div>` : ''}
    `;
  }

  const scoreElem = document.getElementById("scoreBreakdown");
  if (scoreElem && d.insight) {
    scoreElem.innerHTML = `<p class="section-subtitle">${escapeHtml(d.insight.methodology)}</p><div class="compact-priority">${typeof renderPriorityCell === 'function' ? renderPriorityCell(d) : d.insight.score}</div><p>${escapeHtml(d.insight.reasons.join(' · '))}</p>`;
  } else if (scoreElem && d.score_breakdown) {
    const sb = d.score_breakdown;
    scoreElem.innerHTML = `
      <div style="text-align: center; margin-bottom: 16px;">
        <span style="font-size: 2.2rem; font-weight: 800; color: var(--accent-green);">${sb.total}</span>
        <span style="color: var(--text-secondary); font-size: 1rem;"> / 100점</span>
      </div>
      <div style="display:flex; flex-direction:column; gap:8px; font-size: 0.85rem;">
        <div style="display:flex; justify-content:space-between;"><span class="text-muted">일정 확정도 (20점):</span> <strong>${sb.schedule}점</strong></div>
        <div style="display:flex; justify-content:space-between;"><span class="text-muted">관계 직접성 (20점):</span> <strong>${sb.relation}점</strong></div>
        <div style="display:flex; justify-content:space-between;"><span class="text-muted">과거 Edge (30점):</span> <strong>${sb.edge}점</strong></div>
        <div style="display:flex; justify-content:space-between;"><span class="text-muted">Robustness (15점):</span> <strong>${sb.robustness}점</strong></div>
        <div style="display:flex; justify-content:space-between;"><span class="text-muted">현재 Setup (15점):</span> <strong>${sb.setup}점</strong></div>
      </div>
    `;
  }

  renderBacktestVerdict(d);
  renderBacktestStats(d);
  renderHistoricalPeers(d);
  const strategyCard = document.getElementById("strategyCard");
  if (strategyCard) strategyCard.hidden = Boolean(d.market_proxy_study);
  if (!d.market_proxy_study) renderBestStrategy(d);
  const curveNote = document.getElementById("curveNote");
  if (curveNote && d.market_proxy_study) {
    curveNote.textContent = "D0 대비 지수 절대수익률 · 사건별 동일 가중";
  }

  if (d.event_curve && d.event_curve.length > 0) {
    renderEventCurveChart("curveChartCanvas", d.event_curve, d.market_proxy_study);
  }

  const relElem = document.getElementById("relatedSecuritiesBody");
  if (relElem) {
    const list = d.related_securities || [];
    if (list.length === 0) {
      relElem.innerHTML = `<tr><td colspan="4" class="text-muted" style="text-align:center;">관련 종목이 없습니다.</td></tr>`;
    } else {
      relElem.innerHTML = list.map(s => `
        <tr>
          <td><code>${escapeHtml(s.ticker || '미매핑')}</code></td>
          <td><span class="badge ${relationBadgeClass(s.relation_grade)}">${escapeHtml(s.relation_grade)}</span></td>
          <td>${s.relation_score}점 (${escapeHtml(s.relation_type)})</td>
          <td style="font-size:0.8rem; color:#cbd5e1;">${escapeHtml(s.evidence_text || '-')}</td>
        </tr>
      `).join("");
    }
  }

  const stratElem = document.getElementById("strategiesTableBody");
  if (stratElem) {
    const list = d.strategy_summary || [];
    if (list.length === 0) {
      stratElem.innerHTML = `<tr><td colspan="7" class="text-muted" style="text-align:center;">과거 동일 이벤트 표본이 없습니다.</td></tr>`;
    } else {
      stratElem.innerHTML = list.map(s => `
        <tr>
          <td><strong>${escapeHtml(s.name)}</strong></td>
          <td>${s.event_n == null ? '' : s.event_n + '건 / '}${s.sample_n}개</td>
          <td class="${s.sample_n ? (s.mean_return >= 0 ? 'stat-val positive' : 'stat-val negative') : 'muted-value'}" style="font-size:0.9rem;">${s.sample_n ? pct(s.mean_return) : '데이터 없음'}</td>
          <td class="${s.sample_n ? (s.mean_abnormal_return >= 0 ? 'stat-val positive' : 'stat-val negative') : 'muted-value'}" style="font-size:0.9rem;">${s.sample_n ? pct(s.mean_abnormal_return) : '데이터 없음'}</td>
          <td>${s.sample_n ? pct(s.win_rate, 0) : '—'}</td>
          <td style="color:var(--accent-red); font-size:0.9rem;">${s.sample_n ? '-' + ((s.max_drawdown || 0) * 100).toFixed(1) + '%' : '—'}</td>
          <td><span class="badge" style="background:#334155;">${s.sample_n ? s.robustness_score : '—'}</span></td>
        </tr>
      `).join("");
    }
  }

  const revElem = document.getElementById("revisionsTableBody");
  if (revElem) {
    const revs = d.revisions || [];
    if (revs.length === 0) {
      revElem.innerHTML = `<tr><td colspan="5" class="text-muted" style="text-align:center;">변경 이력이 없습니다. 최초 등록 상태 유지 중입니다.</td></tr>`;
    } else {
      revElem.innerHTML = revs.map(r => `
        <tr>
          <td>#${r.revision_no}</td>
          <td>${r.changed_at ? r.changed_at.slice(0, 16).replace("T", " ") : "-"}</td>
          <td><code>${escapeHtml(r.field_name)}</code></td>
          <td><del style="color:#94a3b8;">${escapeHtml(r.old_value)}</del> → <strong style="color:var(--accent-blue);">${escapeHtml(r.new_value)}</strong></td>
          <td style="font-size:0.8rem; color:#cbd5e1;">${escapeHtml(r.change_reason || '-')}</td>
        </tr>
      `).join("");
    }
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", initEventDetail);
