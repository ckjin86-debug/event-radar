/**
 * Main application script for Event Radar dashboard.
 */

let filterEngine = null;

async function initDashboard() {
  try {
    const metaResp = await fetch("data/metadata.json");
    if (metaResp.ok) {
      const meta = await metaResp.json();
      const updatedElem = document.getElementById("lastUpdated");
      if (updatedElem && meta.generated_at) {
        updatedElem.textContent = new Date(meta.generated_at).toLocaleString("ko-KR");
      }
    }

    const evResp = await fetch("data/events.json");
    if (!evResp.ok) throw new Error("Failed to load events.json");
    const events = await evResp.json();

    filterEngine = new EventFilter(events);
    renderTable(filterEngine.apply());
    setupEventListeners();
    loadHistoricalLibrary();
  } catch (err) {
    console.error("Dashboard init error:", err);
    const tbody = document.getElementById("eventsTableBody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 24px; color:#f87171;">데이터를 불러오는 중 오류가 발생했습니다: ${err.message}</td></tr>`;
    }
  }
}

async function loadHistoricalLibrary() {
  const container = document.getElementById("historicalLibrary");
  if (!container) return;

  try {
    const resp = await fetch("data/historical_events.json");
    if (!resp.ok) throw new Error("historical_events.json not found");
    const history = await resp.json();
    renderHistoricalLibrary(history);
  } catch (err) {
    console.warn("Historical library error:", err);
    container.innerHTML = `<div class="history-empty">과거 사례 데이터가 아직 생성되지 않았습니다.</div>`;
  }
}

function renderHistoricalLibrary(history) {
  const container = document.getElementById("historicalLibrary");
  if (!container) return;

  if (!history || history.length === 0) {
    container.innerHTML = `<div class="history-empty">등록된 과거 사례가 없습니다.</div>`;
    return;
  }

  container.innerHTML = history.map(item => {
    const related_securities = item.related_securities || [];
    const securitiesHtml = related_securities.length
      ? related_securities.map(sec => `
          <span class="history-security">
            <code>${escapeHtml(sec.ticker || "-")}</code>
            <span class="badge ${gradeClass(sec.relation_grade)}">${escapeHtml(sec.relation_grade)}</span>
          </span>
        `).join("")
      : `<span class="text-muted">관련주 미매핑</span>`;

    return `
      <article class="history-card">
        <div class="history-card-top">
          <span class="history-date">${escapeHtml(item.event_date)}</span>
          <span class="badge badge-country">${escapeHtml(item.country)}</span>
          <span class="history-type">${escapeHtml(item.event_type)}</span>
        </div>
        <h3>${escapeHtml(item.event_name)}</h3>
        <p>${escapeHtml(item.evidence_text || item.company || "")}</p>
        <div class="history-securities">${securitiesHtml}</div>
        ${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link history-source">근거 출처 ↗</a>` : ""}
      </article>
    `;
  }).join("");
}

function formatEventDate(ev) {
  const precision = ev.date_precision || "EXACT_DATE";
  const start = ev.window_start || ev.event_date;
  const end = ev.window_end || ev.event_date;

  if (precision === "EXACT_DATE" || !start || !end) return ev.event_date || start || "-";

  const startDate = new Date(`${start}T00:00:00`);
  const year = startDate.getFullYear();
  const month = startDate.getMonth() + 1;

  if (precision === "MONTH") return `${year}년 ${month}월`;
  if (precision === "QUARTER") return `${year}년 ${Math.floor((month - 1) / 3) + 1}분기`;
  if (precision === "HALF_YEAR") return `${year}년 ${month <= 6 ? "상반기" : "하반기"}`;
  if (precision === "YEAR") return `${year}년 내`;
  if (precision === "WEEK") return `${start} ~ ${end}`;
  return start === end ? start : `${start} ~ ${end}`;
}

function periodBadgeText(ev) {
  const labels = {
    WEEK: "주간",
    MONTH: "월간",
    QUARTER: "분기",
    HALF_YEAR: "반기",
    YEAR: "연내",
  };
  return labels[ev.date_precision] || null;
}

function gradeClass(grade) {
  if (grade === "A") return "badge-a";
  if (grade === "B") return "badge-b";
  if (grade === "THEME") return "badge-theme";
  return "badge-unmapped";
}

function renderTable(events) {
  const tbody = document.getElementById("eventsTableBody");
  if (!tbody) return;

  if (events.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 32px; color:#94a3b8;">조건에 일치하는 일정이 없습니다.</td></tr>`;
    return;
  }

  tbody.innerHTML = events.map(ev => {
    let ddayClass = "badge-dday";
    const periodLabel = periodBadgeText(ev);
    let ddayText = periodLabel || `D${ev.d_day > 0 ? "-" + ev.d_day : "+" + Math.abs(ev.d_day)}`;

    if (!periodLabel) {
      if (ev.d_day === 0) {
        ddayText = "D-Day";
        ddayClass += " imminent";
      } else if (ev.d_day < 0) {
        ddayClass += " past";
      } else if (ev.d_day <= 3) {
        ddayClass += " imminent";
      }
    }

    const statusClass = ev.status === "CONFIRMED" ? "badge-confirmed" : "badge-expected";
    const score = Math.max(0, Math.min(100, ev.event_score || 0));
    const tickerLabel = ev.ticker || "미매핑";
    const related = (ev.related_securities || []).filter(s => s.ticker);
    const tickersHtml = related.length ? related.map(s => `<div class="listed-security"><code>${escapeHtml(s.ticker)}</code> <small>${escapeHtml(s.relation_grade)}</small>${s.from_entity ? `<div class="security-name">${escapeHtml(s.from_entity)}</div>` : ""}</div>`).join("") : `<code>${escapeHtml(tickerLabel)}</code>`;

    return `
      <tr>
        <td><span class="badge ${ddayClass}">${ddayText}</span></td>
        <td><span class="badge badge-country">${ev.country}</span></td>
        <td><strong>${escapeHtml(ev.company)}</strong></td>
        <td>${tickersHtml}</td>
        <td><a href="event.html?id=${encodeURIComponent(ev.event_id)}" class="row-link">${escapeHtml(ev.event_name)}</a></td>
        <td>${escapeHtml(formatEventDate(ev))}</td>
        <td><span class="badge ${gradeClass(ev.relation_grade)}">${escapeHtml(ev.relation_grade)} (${ev.relation_score})</span></td>
        <td>
          <div class="score-cell">
            <span>${score}</span>
            <div class="score-bar"><div class="score-fill" style="width: ${score}%;"></div></div>
          </div>
        </td>
        <td><span class="badge ${statusClass}">${ev.status}</span></td>
        <td>
          ${ev.source_url ? `<a href="${escapeHtml(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link" style="font-size:0.8rem;">${escapeHtml(ev.source_name)} ↗</a>` : `<span class="text-muted">${escapeHtml(ev.source_name)}</span>`}
        </td>
      </tr>
    `;
  }).join("");
}

function setupEventListeners() {
  document.querySelectorAll(".btn-pill").forEach(btn => {
    btn.addEventListener("click", e => {
      const group = e.target.closest(".filter-row");
      group.querySelectorAll(".btn-pill").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");

      const filterKey = e.target.dataset.filterKey;
      const filterVal = e.target.dataset.filterValue;
      if (filterKey && filterVal && filterEngine) {
        filterEngine.setCriterion(filterKey, filterVal);
        renderTable(filterEngine.apply());
      }
    });
  });

  const searchInput = document.getElementById("searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", e => {
      if (filterEngine) {
        filterEngine.setCriterion("search", e.target.value);
        renderTable(filterEngine.apply());
      }
    });
  }

  const sortSelect = document.getElementById("sortSelect");
  if (sortSelect) {
    sortSelect.addEventListener("change", e => {
      if (filterEngine) {
        filterEngine.setCriterion("sort", e.target.value);
        renderTable(filterEngine.apply());
      }
    });
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

document.addEventListener("DOMContentLoaded", initDashboard);
