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

function renderDetail(d) {
  const tickerLabel = d.ticker || "미매핑";
  document.title = `${d.company} (${tickerLabel}) - ${d.event_name} | Event Radar`;
  document.getElementById("eventTitle").textContent = `${d.company} (${tickerLabel}) - ${d.event_name}`;

  const basicInfoElem = document.getElementById("basicInfo");
  if (basicInfoElem) {
    const scheduleContext = (d.date_precision || "EXACT_DATE") === "EXACT_DATE"
      ? d.event_time_context
      : d.date_precision;
    basicInfoElem.innerHTML = `
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
        <div><span class="text-muted">국가 / 티커:</span> <strong>${d.country} / ${escapeHtml(tickerLabel)}</strong></div>
        <div><span class="text-muted">이벤트 유형:</span> <strong>${d.event_type}</strong></div>
        <div><span class="text-muted">최초 발표일:</span> <strong>${d.announced_at ? d.announced_at.slice(0, 10) : "-"}</strong></div>
        <div><span class="text-muted">이벤트 예정일:</span> <strong style="color:var(--accent-blue);">${escapeHtml(formatEventDate(d))} (${escapeHtml(scheduleContext)})</strong></div>
        <div><span class="text-muted">확정 상태:</span> <span class="badge ${d.status === 'CONFIRMED' ? 'badge-confirmed' : 'badge-expected'}">${d.status}</span></div>
        <div>
          <span class="text-muted">공식 출처:</span> 
          ${d.source_url ? `<a href="${escapeHtml(d.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link">${escapeHtml(d.source_name)} ↗</a>` : escapeHtml(d.source_name)}
        </div>
      </div>
      ${d.evidence_text ? `<div style="margin-top: 14px; padding: 10px; background: var(--bg-primary); border-radius: 6px; font-size: 0.85rem; color: #cbd5e1;"><strong>근거:</strong> ${escapeHtml(d.evidence_text)}</div>` : ''}
    `;
  }

  const scoreElem = document.getElementById("scoreBreakdown");
  if (scoreElem && d.score_breakdown) {
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

  const bs = d.backtest_summary || {};
  const statsElem = document.getElementById("backtestStats");
  if (statsElem) {
    statsElem.innerHTML = `
      <div class="stat-box"><div class="stat-val">${bs.sample_n || 0}건</div><div class="stat-label">과거 동일 이벤트 표본 (N)</div></div>
      <div class="stat-box"><div class="stat-val ${(bs.mean_return || 0) >= 0 ? 'positive' : 'negative'}">${((bs.mean_return || 0) * 100).toFixed(1)}%</div><div class="stat-label">D+5 평균 수익률</div></div>
      <div class="stat-box"><div class="stat-val ${(bs.mean_abnormal_return || 0) >= 0 ? 'positive' : 'negative'}">${((bs.mean_abnormal_return || 0) * 100).toFixed(1)}%</div><div class="stat-label">D+5 평균 초과수익률</div></div>
      <div class="stat-box"><div class="stat-val ${((bs.win_rate || 0) >= 0.5) ? 'positive' : 'negative'}">${((bs.win_rate || 0) * 100).toFixed(0)}%</div><div class="stat-label">D+5 초과수익 승률</div></div>
      <div class="stat-box"><div class="stat-val negative">-${((bs.max_drawdown || 0) * 100).toFixed(1)}%</div><div class="stat-label">표본 최대 낙폭 (MDD)</div></div>
    `;
  }

  if (d.event_curve && d.event_curve.length > 0) {
    renderEventCurveChart("curveChartCanvas", d.event_curve);
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
          <td>${s.sample_n}</td>
          <td class="${s.mean_return >= 0 ? 'stat-val positive' : 'stat-val negative'}" style="font-size:0.9rem;">${(s.mean_return * 100).toFixed(1)}%</td>
          <td class="${s.mean_abnormal_return >= 0 ? 'stat-val positive' : 'stat-val negative'}" style="font-size:0.9rem;">${(s.mean_abnormal_return * 100).toFixed(1)}%</td>
          <td>${(s.win_rate * 100).toFixed(0)}%</td>
          <td style="color:var(--accent-red); font-size:0.9rem;">-${(s.max_drawdown * 100).toFixed(1)}%</td>
          <td><span class="badge" style="background:#334155;">${s.robustness_score}</span></td>
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
