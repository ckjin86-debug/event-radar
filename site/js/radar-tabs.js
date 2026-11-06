/**
 * Radar tabs: keeps 5% ownership filings (DART_5PCT) separate from scheduled events.
 * Loaded after app.js / filters.js. 5% rows come from data/five_pct.json (not overwritten
 * by the scheduled collector) and are drawn with their own row format.
 */
(function () {
  "use strict";

  const isFive = ev => String(ev.event_type || "").toUpperCase() === "5PCT_OWNERSHIP" ||
    String(ev.source_name || "").toUpperCase() === "DART_5PCT";

  let fiveRows = [];
  let currentTab = "all";

  function kstToday() {
    return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
  }
  function daysSince(dateStr) {
    if (!dateStr) return null;
    const a = Date.parse(kstToday() + "T00:00:00Z");
    const b = Date.parse(dateStr + "T00:00:00Z");
    return Number.isNaN(b) ? null : Math.round((a - b) / 86400000);
  }

  function includeFive() { return currentTab === "all" || currentTab === "5pct"; }
  function includeNormal() { return currentTab !== "5pct"; }

  // ---- filtering: run the existing engine separately on each data type ----
  const baseApply = EventFilter.prototype.apply;
  EventFilter.prototype.apply = function () {
    const all = this.allEvents;
    const normal = all.filter(ev => !isFive(ev));
    const byId = new Map();
    all.filter(isFive).forEach(ev => byId.set(ev.event_id, ev));
    fiveRows.forEach(ev => byId.set(ev.event_id, ev));
    const five = Array.from(byId.values());

    let r1 = [], r2 = [];
    try {
      if (includeNormal()) {
        this.allEvents = normal;
        r1 = baseApply.call(this);
      }
      if (includeFive()) {
        this.allEvents = five;
        const savedHorizon = this.criteria.horizon;
        // Filings are not scheduled events: "다가오는 일정" must not hide them.
        if (savedHorizon === "upcoming") this.criteria.horizon = "all";
        try { r2 = baseApply.call(this); } finally { this.criteria.horizon = savedHorizon; }
      }
    } finally {
      this.allEvents = all;
    }
    if (this.criteria.sort === "dday_asc") {
      return r2.concat(r1).sort((a, b) => a.d_day - b.d_day);
    }
    return r2.concat(r1);
  };

  // ---- rendering ----
  const baseRenderTable = window.renderTable;

  function fiveRowHtml(ev) {
    const esc = escapeHtml;
    const n = daysSince(ev.event_date);
    const ago = n === null ? "-" : n <= 0 ? "오늘" : "D+" + n;
    const rel = (ev.related_securities || []).filter(s => s.ticker);
    const tickers = rel.length
      ? rel.slice(0, 3).map(s => `<div class="listed-security"><code>${esc(s.ticker)}</code> <small>${esc(s.relation_grade || "")}</small>${s.name ? `<div class="security-name">${esc(s.name)}</div>` : ""}</div>`).join("")
      : `<code>${esc(ev.ticker || "미매핑")}</code>`;
    const ins = ev.insight || {};
    const tier = ins.tier ? `<span class="badge badge-confirmed">${esc(ins.tier)}</span> ` : "";
    const summary = ins.summary ? `<div class="event-reason">${esc(ins.summary)}</div>` : "";
    const grade = ev.relation_grade ? `${esc(ev.relation_grade)}${ev.relation_score != null ? " (" + esc(ev.relation_score) + ")" : ""}` : "-";
    const gradeCls = typeof gradeClass === "function" ? gradeClass(ev.relation_grade) : "";
    const src = ev.source_url
      ? `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link" style="font-size:0.8rem;">${esc(ev.source_name || "DART")} ↗</a>`
      : `<span class="text-muted">${esc(ev.source_name || "-")}</span>`;
    return `<tr>
      <td><span class="badge badge-dday">${esc(ago)}</span></td>
      <td><span class="badge badge-country">${esc(ev.country || "")}</span></td>
      <td><strong>${esc(ev.company || "")}</strong></td>
      <td>${tickers}</td>
      <td>💎 ${esc(ev.event_name || "")}${summary}</td>
      <td>${esc(ev.event_date || "-")}</td>
      <td><span class="badge ${gradeCls}">${grade}</span></td>
      <td>${tier}<div><small class="text-muted">5% 공시 · 점수 미산정</small></div></td>
      <td><span class="badge ${ev.status === "CONFIRMED" ? "badge-confirmed" : "badge-expected"}">${esc(ev.status || "-")}</span></td>
      <td>${src}</td>
    </tr>`;
  }

  function errorRowHtml(ev, err) {
    return `<tr><td colspan="10" style="color:#f87171;padding:10px;">표시 오류: ${escapeHtml(ev && ev.event_id)} (${escapeHtml(err && err.message)})</td></tr>`;
  }

  window.renderTable = function (events) {
    const tbody = document.getElementById("eventsTableBody");
    if (!tbody) return;
    const summary = () => {
      if (typeof renderDashboardSummary === "function") {
        try { renderDashboardSummary(events); } catch (e) { console.warn("summary", e); }
      }
    };
    if (!events.length) {
      summary();
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 32px; color:#94a3b8;">${currentTab === "5pct" ? "조건에 일치하는 5% 공시가 없습니다." : "조건에 일치하는 일정이 없습니다."}</td></tr>`;
      return;
    }
    const rows = events.map(ev => {
      try {
        if (isFive(ev)) return fiveRowHtml(ev);
        baseRenderTable([ev]); // existing renderer for scheduled events
        return tbody.innerHTML;
      } catch (err) {
        console.error("row render failed", ev && ev.event_id, err);
        return errorRowHtml(ev, err);
      }
    });
    tbody.innerHTML = rows.join("");
    summary();
  };

  // ---- tabs ----
  const TABS = {
    all:     { btn: "tabAll",     criteria: { category: "all", horizon: "upcoming", grade: "all" } },
    "5pct":  { btn: "tab5pct",    criteria: { category: "지분공시", horizon: "all", grade: "all" } },
    dday:    { btn: "tabDday",    criteria: { category: "all", horizon: "30d", grade: "all" } },
    overlap: { btn: "tabOverlap", criteria: { category: "all", horizon: "upcoming", grade: "A" } },
  };

  window.switchRadarTab = function (key) {
    const tab = TABS[key];
    if (!tab) return;
    currentTab = key;
    Object.keys(TABS).forEach(k => {
      const b = document.getElementById(TABS[k].btn);
      if (!b) return;
      b.style.background = "#1e293b";
      b.style.color = k === "overlap" ? "#ec4899" : "#94a3b8";
    });
    const active = document.getElementById(tab.btn);
    if (active) {
      active.style.background = key === "overlap" ? "#ec4899" : "#38bdf8";
      active.style.color = "#0f172a";
    }
    if (typeof filterEngine === "undefined" || !filterEngine) return;
    Object.keys(tab.criteria).forEach(c => {
      filterEngine.setCriterion(c, tab.criteria[c]);
      document.querySelectorAll(`.btn-pill[data-filter-key="${c}"]`).forEach(p => {
        p.classList.toggle("active", p.getAttribute("data-filter-value") === tab.criteria[c]);
      });
    });
    renderTable(filterEngine.apply());
  };
  window.eventFilter = null;
  window.app = { renderTable: () => { if (filterEngine) renderTable(filterEngine.apply()); } };

  // ---- load 5% data ----
  fetch("data/five_pct.json")
    .then(r => { if (!r.ok) throw new Error("five_pct.json " + r.status); return r.json(); })
    .then(rows => {
      fiveRows = Array.isArray(rows) ? rows : [];
      if (typeof filterEngine !== "undefined" && filterEngine) renderTable(filterEngine.apply());
    })
    .catch(err => console.warn("5% data not loaded:", err));
})();
