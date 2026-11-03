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

  } catch (err) {
    console.error("Dashboard init error:", err);
    const tbody = document.getElementById("eventsTableBody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 24px; color:#f87171;">데이터를 불러오는 중 오류가 발생했습니다: ${err.message}</td></tr>`;
    }
  }
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
    let ddayText = periodLabel || `D${ev.d_day >= 0 ? "+" + ev.d_day : ev.d_day}`;

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

    const gradeClass = ev.relation_grade === "A" ? "badge-a" : "badge-b";
    const statusClass = ev.status === "CONFIRMED" ? "badge-confirmed" : "badge-expected";
    const score = Math.max(0, Math.min(100, ev.event_score || 0));

    return `
      <tr>
        <td><span class="badge ${ddayClass}">${ddayText}</span></td>
        <td><span class="badge badge-country">${ev.country}</span></td>
        <td><strong>${escapeHtml(ev.company)}</strong></td>
        <td><code>${escapeHtml(ev.ticker)}</code></td>
        <td><a href="event.html?id=${encodeURIComponent(ev.event_id)}" class="row-link">${escapeHtml(ev.event_name)}</a></td>
        <td>${escapeHtml(formatEventDate(ev))}</td>
        <td><span class="badge ${gradeClass}">${ev.relation_grade} (${ev.relation_score})</span></td>
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
