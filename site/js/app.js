/**
 * Main application script for Event Radar dashboard.
 */

let filterEngine = null;

async function initDashboard() {
  try {
    // 1. Fetch metadata
    const metaResp = await fetch("data/metadata.json");
    if (metaResp.ok) {
      const meta = await metaResp.json();
      const updatedElem = document.getElementById("lastUpdated");
      if (updatedElem && meta.generated_at) {
        updatedElem.textContent = new Date(meta.generated_at).toLocaleString("ko-KR");
      }
    }

    // 2. Fetch events
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

function renderTable(events) {
  const tbody = document.getElementById("eventsTableBody");
  if (!tbody) return;

  if (events.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 32px; color:#94a3b8;">조건에 일치하는 일정이 없습니다.</td></tr>`;
    return;
  }

  tbody.innerHTML = events.map(ev => {
    // D-Day badge
    let ddayClass = "badge-dday";
    let ddayText = `D${ev.d_day >= 0 ? "+" + ev.d_day : ev.d_day}`;
    if (ev.d_day === 0) {
      ddayText = "D-Day";
      ddayClass += " imminent";
    } else if (ev.d_day < 0) {
      ddayClass += " past";
    } else if (ev.d_day <= 3) {
      ddayClass += " imminent";
    }

    // Grade badge
    const gradeClass = ev.relation_grade === "A" ? "badge-a" : "badge-b";

    // Status badge
    const statusClass = ev.status === "CONFIRMED" ? "badge-confirmed" : "badge-expected";

    // Score fill width
    const score = Math.max(0, Math.min(100, ev.event_score || 0));

    return `
      <tr>
        <td><span class="badge ${ddayClass}">${ddayText}</span></td>
        <td><span class="badge badge-country">${ev.country}</span></td>
        <td><strong>${escapeHtml(ev.company)}</strong></td>
        <td><code>${escapeHtml(ev.ticker)}</code></td>
        <td><a href="event.html?id=${encodeURIComponent(ev.event_id)}" class="row-link">${escapeHtml(ev.event_name)}</a></td>
        <td>${ev.event_date}</td>
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
  // Pill button filter clicks
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

  // Search input
  const searchInput = document.getElementById("searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", e => {
      if (filterEngine) {
        filterEngine.setCriterion("search", e.target.value);
        renderTable(filterEngine.apply());
      }
    });
  }

  // Sort select
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
