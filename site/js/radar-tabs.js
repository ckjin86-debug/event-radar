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

  // Alpha score from the ported Super Radar rules (fallback: legacy event_score).
  function fiveScore(ev) {
    const raw = ev.alpha_score != null ? ev.alpha_score : ev.event_score;
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  function fmtSigned(n) { return n > 0 ? "+" + n : String(n); }
  function fmtNum(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "";
    return n.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  function fmtPct(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "";
    return (n > 0 ? "+" : "") + n.toFixed(1) + "%";
  }
  function scoreToneClass(n) { return n > 0 ? "five-score-pos" : n < 0 ? "five-score-neg" : "five-score-zero"; }

  function purposeLevel(p) {
    if (!p) return 0;
    if (String(p).includes("경영권")) return 3;
    if (String(p).includes("일반투자")) return 2;
    if (String(p).includes("단순투자")) return 1;
    return 0;
  }

  // Chips under the event name: investor class, purpose change, accumulation
  // streak, freshness (only when not CURRENT). Missing fields are omitted.
  function fiveMetaHtml(ev) {
    const esc = escapeHtml;
    const chips = [];
    if (ev.investor_class) {
      chips.push(`<span class="five-chip five-chip-investor">${esc(ev.investor_class)}</span>`);
    }
    const prev = ev.purpose_prev, cur = ev.purpose_current;
    if (prev && cur && prev !== cur) {
      const up = purposeLevel(cur) > purposeLevel(prev);
      const down = purposeLevel(cur) < purposeLevel(prev);
      const cls = up ? " five-chip-purpose-up" : down ? " five-chip-purpose-down" : "";
      chips.push(`<span class="five-chip${cls}" title="보유목적 변화">${esc(prev)} → ${esc(cur)}</span>`);
    } else if (cur || prev) {
      chips.push(`<span class="five-chip" title="보유목적">${esc(cur || prev)}</span>`);
    }
    const accum = Number(ev.accumulation_count);
    if (Number.isFinite(accum) && accum >= 2) {
      chips.push(`<span class="five-chip five-chip-accum">연속매집 ${accum}회</span>`);
    }
    if (ev.freshness && ev.freshness !== "CURRENT") {
      chips.push(`<span class="five-chip five-chip-fresh">${esc(ev.freshness)}</span>`);
    }
    return chips.length ? `<div class="five-meta">${chips.join("")}</div>` : "";
  }

  // Acquirer average price vs current price (S6 safety margin), when priced.
  function fivePriceHtml(ev) {
    if (ev.est_avg_price == null || ev.current_price == null) return "";
    const esc = escapeHtml;
    let gap = "";
    if (ev.price_gap_pct != null && Number.isFinite(Number(ev.price_gap_pct))) {
      const g = Number(ev.price_gap_pct);
      gap = ` (<span class="${scoreToneClass(-g === 0 ? 0 : g < 0 ? 1 : -1)}">${fmtPct(g)}</span>)`;
    }
    const src = ev.price_source ? ` <small class="text-muted">${esc(ev.price_source)}</small>` : "";
    return `<div class="five-price">평단 ${fmtNum(ev.est_avg_price)} · 현재 ${fmtNum(ev.current_price)}${gap}${src}</div>`;
  }

  function fiveScoreCellHtml(ev) {
    const esc = escapeHtml;
    const ins = ev.insight || {};
    const tier = ins.tier ? `<span class="badge badge-confirmed">${esc(ins.tier)}</span> ` : "";
    const s = fiveScore(ev);
    if (s === null) return `${tier}<div><small class="text-muted">5% 공시</small></div>`;
    return `${tier}<div class="five-score ${scoreToneClass(s)}">${fmtSigned(s)}</div><div><small class="text-muted">알파 점수</small></div>`;
  }

  function fiveHasDetail(ev) {
    return (Array.isArray(ev.score_breakdown) && ev.score_breakdown.length > 0) ||
      Boolean(ev.insight && ev.insight.summary);
  }

  function fiveDetailHtml(ev) {
    if (!fiveHasDetail(ev)) return "";
    const esc = escapeHtml;
    const ins = ev.insight || {};
    const bd = Array.isArray(ev.score_breakdown) ? ev.score_breakdown : [];
    const items = bd.map(b => {
      const p = Number(b && b.points) || 0;
      const pcls = p > 0 ? "five-pt-pos" : p < 0 ? "five-pt-neg" : "five-pt-zero";
      return `<li><span class="five-bd-strategy">${esc((b && b.strategy) || "")}</span><span class="five-bd-points ${pcls}">${fmtSigned(p)}</span><span class="five-bd-reason">${esc((b && b.reason) || "")}</span></li>`;
    }).join("");
    const total = fiveScore(ev);
    return `<tr class="five-detail-row" data-five-detail="${esc(ev.event_id || "")}" hidden>
      <td colspan="10"><div class="five-detail">
        ${ins.summary ? `<p class="five-detail-summary">${esc(ins.summary)}</p>` : ""}
        ${bd.length ? `<div class="five-detail-head">점수 근거 (전략별 분해)${total !== null ? ` · 합계 <strong>${fmtSigned(total)}</strong>` : ""}</div><ul class="five-breakdown">${items}</ul>` : ""}
      </div></td>
    </tr>`;
  }

  function fiveRowHtml(ev) {
    const esc = escapeHtml;
    const n = daysSince(ev.event_date);
    const ago = n === null ? "-" : n <= 0 ? "오늘" : "D+" + n;
    const rel = (ev.related_securities || []).filter(s => s.ticker);
    const tickers = rel.length
      ? rel.slice(0, 3).map(s => `<div class="listed-security"><code>${esc(s.ticker)}</code> <small>${esc(s.relation_grade || "")}</small>${s.name ? `<div class="security-name">${esc(s.name)}</div>` : ""}</div>`).join("")
      : `<code>${esc(ev.ticker || "미매핑")}</code>`;
    const ins = ev.insight || {};
    const summary = ins.summary ? `<div class="event-reason">${esc(ins.summary)}</div>` : "";
    const grade = ev.relation_grade ? `${esc(ev.relation_grade)}${ev.relation_score != null ? " (" + esc(ev.relation_score) + ")" : ""}` : "-";
    const gradeCls = typeof gradeClass === "function" ? gradeClass(ev.relation_grade) : "";
    const src = ev.source_url
      ? `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer" class="row-link" style="font-size:0.8rem;">${esc(ev.source_name || "DART")} ↗</a>`
      : `<span class="text-muted">${esc(ev.source_name || "-")}</span>`;
    const toggle = fiveHasDetail(ev)
      ? `<button type="button" class="five-toggle" data-five-toggle="${esc(ev.event_id || "")}" aria-expanded="false">상세 ▾</button>`
      : "";
    return `<tr>
      <td><span class="badge badge-dday">${esc(ago)}</span></td>
      <td><span class="badge badge-country">${esc(ev.country || "")}</span></td>
      <td><strong>${esc(ev.company || "")}</strong></td>
      <td>${tickers}</td>
      <td>💎 ${esc(ev.event_name || "")}${summary}${fiveMetaHtml(ev)}${fivePriceHtml(ev)}${toggle}</td>
      <td>${esc(ev.event_date || "-")}</td>
      <td><span class="badge ${gradeCls}">${grade}</span></td>
      <td>${fiveScoreCellHtml(ev)}</td>
      <td><span class="badge ${ev.status === "CONFIRMED" ? "badge-confirmed" : "badge-expected"}">${esc(ev.status || "-")}</span></td>
      <td>${src}</td>
    </tr>` + fiveDetailHtml(ev);
  }

  // Expand/collapse the score-breakdown detail row (event delegation, bound once).
  const fiveTbody = document.getElementById("eventsTableBody");
  if (fiveTbody && !fiveTbody.dataset.fiveToggleBound) {
    fiveTbody.dataset.fiveToggleBound = "1";
    fiveTbody.addEventListener("click", e => {
      const btn = e.target && e.target.closest ? e.target.closest("[data-five-toggle]") : null;
      if (!btn) return;
      const id = btn.getAttribute("data-five-toggle");
      let row = null;
      fiveTbody.querySelectorAll("[data-five-detail]").forEach(r => {
        if (r.getAttribute("data-five-detail") === id) row = r;
      });
      if (!row) return;
      const open = Boolean(row.hidden);
      row.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = open ? "상세 ▴" : "상세 ▾";
    });
  }

  // =====================================================================
  // 5pct tab: faithful reproduction of the original DART 5% Super Radar
  // dashboard display (market switcher, backtest panel, KPI cards,
  // original table columns and detail modal). Data comes from
  // five_pct.json fields only; values the feed does not carry yet
  // (holding ratio, backtest returns) are shown as "-"/"도래전",
  // exactly like the original did before its backtester ran.
  // =====================================================================
  let fiveMarket = "KR";
  const fiveById = new Map();

  window.switchFiveMarket = function (m) {
    fiveMarket = m === "US" ? "US" : "KR";
    if (typeof filterEngine !== "undefined" && filterEngine) renderTable(filterEngine.apply());
  };

  const theadEl = document.querySelector(".radar-table thead");
  const defaultTheadHtml = theadEl ? theadEl.innerHTML : null;
  const FIVE_THEAD_HTML = `<tr>
      <th style="width:68px;">스코어</th>
      <th>종목명 (코드/티커)</th>
      <th>보고자 (주체 분류)</th>
      <th>보유목적 (직전 → 현재)</th>
      <th>보유비율 (변동폭)</th>
      <th>세력 매집단가 vs 현재가 (안전마진)</th>
      <th>포착 시그널 & 변동사유</th>
      <th style="background:#17253b; color:#7dd3fc;">① 신규접수일 대비 (최근 모멘텀)</th>
      <th style="background:#1e1b38; color:#c4b5fd;">② 최초 5% 공시일 대비 (트랙레코드)</th>
      <th style="width:96px;">상세/단가</th>
    </tr>`;

  function fiveReporter(ev) {
    if (ev.reporter) return String(ev.reporter).trim();
    const m = /\(대표보고자:\s*([^)]+)\)/.exec(ev.event_name || "");
    return m ? m[1].trim() : "";
  }
  // Original normalizePurpose() long labels, mapped from the short forms
  // stored in five_pct.json.
  function purposeDisplay(p) {
    if (!p) return "";
    if (String(p).includes("경영권")) return "경영권 영향 (13D)";
    if (String(p).includes("일반투자")) return "일반투자 (적극주주)";
    if (String(p).includes("단순투자")) return "단순투자 (13G/약식)";
    return String(p);
  }
  function fiveFreshness(ev) {
    if (ev.freshness) return ev.freshness;
    const d = daysSince(ev.event_date);
    if (d === null) return "";
    return d <= 30 ? "CURRENT" : d <= 90 ? "RECENT" : d <= 180 ? "AGING" : "STALE";
  }
  function fmtMoney(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n === 0) return "-";
    return Math.round(n).toLocaleString("ko-KR") + "원";
  }

  // Signal tags, derived from the same fields the original rules.js tags
  // were built from (investor class, purpose change, streak, breakdown).
  function fiveTagsHtml(ev) {
    const esc = escapeHtml;
    const tags = [];
    const ic = ev.investor_class || "";
    const invCls = ic.includes("행동주의") ? "sr-tag-activist" : ic.includes("가치투자") ? "sr-tag-value"
      : ic.includes("PEF") ? "sr-tag-pef" : ic.includes("슈퍼개미") ? "sr-tag-ant"
      : ic.includes("패시브") ? "sr-tag-passive" : "";
    if (invCls) tags.push({ text: ic, cls: invCls });
    const prev = ev.purpose_prev, cur = ev.purpose_current;
    const pl = purposeLevel(cur), pv = purposeLevel(prev);
    if (prev && cur && pl > pv) {
      tags.push(pl >= 3 ? { text: "★목적상향(경영권/13D)", cls: "sr-tag-purpose-critical" } : { text: "★목적상향(일반/13D)", cls: "sr-tag-purpose" });
    } else if (prev && cur && pl < pv) {
      tags.push({ text: "목적하향(이탈주의)", cls: "sr-tag-exit" });
    } else if (pl >= 3) {
      tags.push({ text: "경영권영향(13D) 유지", cls: "sr-tag-purpose-critical" });
    } else if (!prev && cur) {
      tags.push({ text: "신규 5% 진입", cls: "sr-tag-new" });
    } else if (pl === 2) {
      tags.push({ text: "일반투자(적극주주)", cls: "sr-tag-purpose" });
    }
    const accum = Number(ev.accumulation_count);
    if (Number.isFinite(accum) && accum >= 2) tags.push({ text: `★${accum}연속 매집`, cls: "sr-tag-streak" });
    const bd = Array.isArray(ev.score_breakdown) ? ev.score_breakdown : [];
    if (bd.some(b => String((b && b.strategy) || "").includes("전략 5") && Number(b.points) > 0)) {
      tags.push({ text: "10% 주요주주 돌파", cls: "sr-tag-milestone" });
    }
    const s7 = bd.filter(b => String((b && b.strategy) || "").includes("전략 7") && Number(b.points) < 0);
    if (s7.some(b => Number(b.points) <= -4)) tags.push({ text: "▼5% 미만 이탈(공시의무소멸)", cls: "sr-tag-exit-critical" });
    else if (s7.length) tags.push({ text: "지분 축소", cls: "sr-tag-exit" });
    const reasons = bd.map(b => String((b && b.reason) || "")).join(" ");
    if (/장내매수/.test(reasons)) tags.push({ text: "장내매수", cls: "sr-tag-openmarket" });
    if (/전환사채|메자닌/.test(reasons)) tags.push({ text: "CB/메자닌", cls: "sr-tag-mezzanine" });
    if (ev.price_gap_pct != null && Number.isFinite(Number(ev.price_gap_pct))) {
      const g = Number(ev.price_gap_pct);
      const srcTag = String(ev.price_source || "").startsWith("VWAP") ? " (VWAP추정)" : "";
      if (g <= -5) tags.push({ text: `★안전마진 ${fmtPct(g)}${srcTag}`, cls: "sr-tag-openmarket" });
      else if (g < 0) tags.push({ text: `평단하회 ${fmtPct(g)}${srcTag}`, cls: "sr-tag-openmarket" });
    }
    const tagsHtml = tags.length
      ? `<div class="sr-tags-wrap">${tags.map(t => `<span class="sr-tag ${t.cls}">${esc(t.text)}</span>`).join("")}</div>`
      : "";
    const summary = ev.insight && ev.insight.summary;
    const sub = summary ? `<div class="sr-reason-subtext" title="${esc(summary)}">${esc(summary)}</div>` : "";
    return tagsHtml + sub;
  }

  // Original formatPriceGapCell(): acquirer average vs current price.
  function fivePriceCellHtml(ev) {
    const esc = escapeHtml;
    if (ev.est_avg_price == null) {
      return `<div class="sr-price-gap-cell"><span class="sr-price-now">현재가: ${fmtMoney(ev.current_price)}</span><span class="sr-price-note">평단 미산출 (가격 데이터 필요)</span></div>`;
    }
    const isVwap = String(ev.price_source || "").startsWith("VWAP_ESTIMATE");
    const label = isVwap ? "추정VWAP" : "평단";
    if (ev.current_price == null) {
      return `<div class="sr-price-gap-cell"><div class="sr-price-avg">${label}: ${fmtMoney(ev.est_avg_price)}</div><div class="sr-price-src">${esc(ev.price_source || "")}</div></div>`;
    }
    let g = ev.price_gap_pct != null ? Number(ev.price_gap_pct)
      : (Number(ev.current_price) / Number(ev.est_avg_price) - 1) * 100;
    g = Math.round(g * 10) / 10;
    const badge = g <= -5
      ? `<span class="sr-gap-badge-safe">★ ${fmtPct(g)} (${isVwap ? "VWAP하회" : "안전마진!"})</span>`
      : g < 0
        ? `<span class="sr-gap-badge-safe">▼ ${fmtPct(g)} (평단하회)</span>`
        : `<span class="sr-gap-badge-above">▲ ${fmtPct(g)} (세력수익중)</span>`;
    return `<div class="sr-price-gap-cell">
      <div class="sr-price-main">${label} ${fmtMoney(ev.est_avg_price)} <span class="sr-price-cur">/ 현재 ${fmtMoney(ev.current_price)}</span></div>
      <div class="sr-price-badgerow">${badge}<span class="sr-price-src" title="${esc(ev.price_source || "")}">${esc(ev.price_source || "")}</span></div>
    </div>`;
  }

  // Original formatLatestBtCell(): filing date + freshness badge; returns
  // are not computed by this feed yet, so pills stay "도래전" and the
  // cumulative return "-", like the original before its backtest ran.
  function fiveLatestBtHtml(ev) {
    const esc = escapeHtml;
    const days = daysSince(ev.event_date);
    const dTxt = days === null ? "-" : days;
    const f = fiveFreshness(ev);
    let badge = "";
    if (f === "CURRENT") badge = `<span class="sr-fresh-badge sr-fresh-hot" title="공시 신선도: CURRENT (0~30일)">CURRENT · D-${dTxt}</span>`;
    else if (f === "RECENT") badge = `<span class="sr-fresh-badge sr-fresh-recent" title="공시 신선도: RECENT (31~90일)">RECENT · ${dTxt}일</span>`;
    else if (f === "AGING") badge = `<span class="sr-fresh-badge sr-fresh-aging" title="공시 신선도: AGING (91~180일)">AGING · ${dTxt}일</span>`;
    else if (f === "STALE") badge = `<span class="sr-fresh-badge sr-fresh-stale" title="STALE (181일↑): 장기 Ownership Context 전용 · 최근 매집 신호 비활성화">STALE · ${dTxt}일(장기맥락)</span>`;
    return `<div class="sr-bt-cell sr-bt-latest">
      <div class="sr-bt-row sr-bt-head"><strong>${esc(ev.event_date || "-")}</strong>${badge}</div>
      <div class="sr-bt-row"><span class="sr-bt-label">접수후 현재:</span><strong class="sr-bt-na">-</strong></div>
      <div class="sr-bt-row"><span class="sr-bt-wait">D+5 도래전</span><span class="sr-bt-wait">D+20 도래전</span></div>
    </div>`;
  }

  // Original formatFirstEntryBtCell(): first-entry placeholder when the
  // reporter has no previous filing; otherwise track-record pills pending.
  function fiveFirstBtHtml(ev) {
    const esc = escapeHtml;
    if (!ev.purpose_prev) {
      return `<div class="sr-bt-cell sr-bt-first">
        <div class="sr-bt-first-title">★ 금번이 최초 5% 진입</div>
        <div class="sr-bt-first-sub">과거 공시 이력 없음 (1회차)</div>
        <div class="sr-bt-first-note">향후 D+5 / D+20 추적 대상</div>
      </div>`;
    }
    return `<div class="sr-bt-cell sr-bt-first">
      <div class="sr-bt-row"><span class="sr-bt-first-date">최초진입: ${esc(ev.first_entry_dt || "-")}</span></div>
      <div class="sr-bt-row"><span class="sr-bt-wait-plain">D+5 도래전</span><span class="sr-bt-wait-plain">D+20 도래전</span></div>
      <div class="sr-bt-row"><span class="sr-bt-wait-plain">D+60 도래전</span></div>
    </div>`;
  }

  // Holdings ratio + change, as the original rendered it; "-" only when
  // the filing feed carries no ratio at all.
  function fiveHoldHtml(ev) {
    const esc = escapeHtml;
    if (ev.hold_stock_rt === null || ev.hold_stock_rt === undefined || ev.hold_stock_rt === "") {
      return `<div class="sr-hold">-</div>`;
    }
    const rt = Number(ev.hold_stock_rt);
    if (!Number.isFinite(rt)) return `<div class="sr-hold">${esc(ev.hold_stock_rt)}</div>`;
    let varHtml = "";
    if (ev.stk_rt_var !== null && ev.stk_rt_var !== undefined && ev.stk_rt_var !== "") {
      const v = Number(ev.stk_rt_var);
      if (Number.isFinite(v)) {
        varHtml = ` <span class="sr-hold-var">(${v >= 0 ? "+" : ""}${v.toFixed(2)}%p)</span>`;
      }
    }
    return `<div class="sr-hold">${rt.toFixed(2)}%${varHtml}</div>`;
  }

  function fiveSrRowHtml(ev) {
    const esc = escapeHtml;
    const s = fiveScore(ev);
    const sc = s === null ? 0 : s;
    const scoreCls = sc >= 8 ? "sr-score-ultra" : sc >= 5 ? "sr-score-high" : sc > 0 ? "sr-score-mid" : "sr-score-neg";
    const ticker = ev.ticker || ev.primary_ticker || "";
    const reporter = fiveReporter(ev);
    const prev = ev.purpose_prev, cur = ev.purpose_current;
    let purposeHtml = "-";
    if (cur) {
      const curSpan = `<span class="sr-purpose-curr-${purposeLevel(cur) || 1}">${esc(purposeDisplay(cur))}</span>`;
      purposeHtml = prev && prev !== cur
        ? `<div class="sr-purpose-box"><span class="sr-purpose-prev">${esc(purposeDisplay(prev))}</span> <span>➔</span> ${curSpan}</div>`
        : `<div class="sr-purpose-box">${curSpan}</div>`;
    }
    const accum = Number(ev.accumulation_count);
    const streak = Number.isFinite(accum) && accum >= 2 ? `<div class="sr-hold-streak">★ 연속 ${accum}회 확대</div>` : "";
    const dartLink = ev.source_url ? `<a class="sr-mini-link" href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer">📄 DART원문</a>` : "";
    const chartLink = ticker ? `<a class="sr-mini-link" href="https://finance.naver.com/item/main.naver?code=${encodeURIComponent(ticker)}" target="_blank" rel="noopener noreferrer">📈 네이버증권</a>` : "";
    const id = esc(ev.event_id || "");
    return `<tr>
      <td><span class="sr-score-badge ${scoreCls}" data-five-detail-btn="${id}" title="클릭하여 7대 전략 채점 근거 보기">${s === null ? "-" : fmtSigned(sc)}</span></td>
      <td><div class="sr-corp-cell"><div class="sr-corp-name-row"><span>${esc(ev.company || "")}</span>${ticker ? `<span class="sr-stock-code">${esc(ticker)}</span>` : ""}</div><div class="sr-mini-links">${dartLink}${chartLink}</div></div></td>
      <td><div class="sr-reporter">${esc(reporter || "-")}</div>${ev.investor_class ? `<div class="sr-investor-label">${esc(ev.investor_class)}</div>` : ""}</td>
      <td>${purposeHtml}</td>
      <td>${fiveHoldHtml(ev)}${streak}</td>
      <td>${fivePriceCellHtml(ev)}</td>
      <td>${fiveTagsHtml(ev)}</td>
      <td>${fiveLatestBtHtml(ev)}</td>
      <td>${fiveFirstBtHtml(ev)}</td>
      <td><button type="button" class="sr-btn sr-btn-sm" data-five-detail-btn="${id}">🔍 단가·시계열</button></td>
    </tr>`;
  }

  // Market switcher + backtest panel + KPI cards (original updateKpiCards
  // semantics), written into the dashboard overview area in 5pct mode.
  function renderFiveDashboard(events) {
    const container = document.getElementById("radarOverview");
    if (!container) return;
    const esc = escapeHtml;
    const rows = events || [];
    const isNoise = ev => String(ev.investor_class || "").includes("패시브");
    const nonNoise = rows.filter(ev => !isNoise(ev));
    const noiseCount = rows.length - nonNoise.length;
    const topCand = nonNoise.filter(ev => fiveFreshness(ev) !== "STALE" && (fiveScore(ev) || 0) > 0);
    const top = topCand.length ? topCand.reduce((a, b) => (fiveScore(b) > fiveScore(a) ? b : a)) : null;
    const safety = nonNoise.filter(ev => ev.price_gap_pct != null && Number(ev.price_gap_pct) < 0).length;
    const purposeUp = nonNoise.filter(ev => ev.purpose_prev && purposeLevel(ev.purpose_current) > purposeLevel(ev.purpose_prev)).length;
    const accumCnt = nonNoise.filter(ev => Number(ev.accumulation_count) >= 2).length;
    const exitCnt = nonNoise.filter(ev => (ev.score_breakdown || []).some(b => String((b && b.strategy) || "").includes("전략 7") && Number(b.points) < 0)).length;
    const topSub = top
      ? `${esc(fiveReporter(top))} · ${esc(top.purpose_current || "")} [${esc(fiveFreshness(top))}]`
      : "포착된 최근(CURRENT/RECENT) 양(+)의 시그널 없음";
    container.innerHTML = `
    <div class="sr-span sr-market-row">
      <div class="sr-market-switcher">
        <button type="button" class="sr-market-btn${fiveMarket === "KR" ? " active" : ""}" onclick="switchFiveMarket('KR')">🇰🇷 한국 DART (5% 공시)</button>
        <button type="button" class="sr-market-btn${fiveMarket === "US" ? " active" : ""}" onclick="switchFiveMarket('US')">🇺🇸 미국 SEC (13D / 13G)</button>
      </div>
      <span class="sr-market-note">DART &amp; SEC 5% Super Radar</span>
    </div>
    <div class="sr-span sr-backtest-panel">
      <div class="sr-bt-header"><div>
        <div class="sr-bt-title">📈 7대 전략 백테스팅 성과 검증 &amp; 3중 세력 매집단가 추적 엔진</div>
        <div class="sr-bt-desc">① DART 원문 제3절 단가표 가중평균 + ② SEC 13D Item 3 매수원가 + ③ 매집기간 일봉 거래량가중평균가(VWAP)로 세력 평단가를 산출하고, 공시 후 D+5/20/60 수익률을 검증합니다.</div>
      </div></div>
      <div class="sr-bt-metrics">
        <div class="sr-bt-metric-item"><span class="sr-bt-metric-label">고득점(+5점↑) D+20 승률</span><span class="sr-bt-metric-val" style="color:#34d399;">미실행</span></div>
        <div class="sr-bt-metric-item"><span class="sr-bt-metric-label">고득점 평균 D+5 / D+20 / D+60</span><span class="sr-bt-metric-val" style="color:#fca5a5;">-</span></div>
        <div class="sr-bt-metric-item"><span class="sr-bt-metric-label">고득점 평균 최고상승(Max Run-up)</span><span class="sr-bt-metric-val" style="color:#fbbf24;">-</span></div>
        <div class="sr-bt-metric-item"><span class="sr-bt-metric-label">★목적변경(13D) D+20 평균</span><span class="sr-bt-metric-val" style="color:#f87171;">-</span></div>
        <div class="sr-bt-metric-item"><span class="sr-bt-metric-label">⚠️이탈/마이너스스코어 D+20 평균</span><span class="sr-bt-metric-val" style="color:#93c5fd;">-</span></div>
      </div>
    </div>
    <div class="sr-span sr-kpi-grid">
      <div class="sr-kpi-card"><div class="sr-kpi-label">유효 신규 공시 (오래된 이력·노이즈 제외)</div><div class="sr-kpi-value">${nonNoise.length}건</div><div class="sr-kpi-sub">패시브/연기금 자동 필터링 ${noiseCount}건</div></div>
      <div class="sr-kpi-card"><div class="sr-kpi-label">최고 알파 스코어 종목</div><div class="sr-kpi-value" style="color:#ef4444;">${top ? `${esc(top.company || "")} (${fmtSigned(fiveScore(top))}점)` : "-"}</div><div class="sr-kpi-sub">${topSub}</div></div>
      <div class="sr-kpi-card"><div class="sr-kpi-label">🟢 세력 평단 하회 (안전마진 종목)</div><div class="sr-kpi-value" style="color:#34d399;">${safety}건</div><div class="sr-kpi-sub">현재가가 세력 매집단가보다 저렴한 구간</div></div>
      <div class="sr-kpi-card"><div class="sr-kpi-label">★ 목적 상향 &amp; 🔥 연속 매집</div><div class="sr-kpi-value" style="color:#f59e0b;">목적상향 ${purposeUp}건 / 연속매집 ${accumCnt}건</div><div class="sr-kpi-sub">단순→일반/경영권 · 2회+ 연속매집</div></div>
      <div class="sr-kpi-card"><div class="sr-kpi-label">⚠️ 대량 이탈 / 5% 미만 경보</div><div class="sr-kpi-value" style="color:#3b82f6;">${exitCnt}건</div><div class="sr-kpi-sub">지분 축소 및 공시의무 소멸 주의</div></div>
    </div>`;
  }

  function renderFiveTab(events, tbody) {
    const fiveEvents = (events || []).filter(isFive);
    fiveEvents.forEach(ev => { if (ev.event_id) fiveById.set(ev.event_id, ev); });
    const marketEvents = fiveEvents.filter(ev => String(ev.country || "KR").toUpperCase() === fiveMarket);
    renderFiveDashboard(marketEvents);
    if (!marketEvents.length) {
      const countryKnown = fiveRows.some(r => String((r && r.country) || "KR").toUpperCase() === fiveMarket);
      const msg = !countryKnown
        ? (fiveMarket === "US" ? "🇺🇸 미국 SEC (13D / 13G) 공시가 아직 수집되지 않았습니다." : "🇰🇷 한국 DART 5% 공시가 아직 수집되지 않았습니다.")
        : "조건에 부합하는 신규 5% 대량보유 공시가 없습니다.";
      tbody.innerHTML = `<tr><td colspan="10" class="sr-empty-state">${msg}</td></tr>`;
      return;
    }
    tbody.innerHTML = marketEvents.map(ev => {
      try { return fiveSrRowHtml(ev); }
      catch (err) { console.error("five row render failed", ev && ev.event_id, err); return errorRowHtml(ev, err); }
    }).join("");
  }

  // ---- detail modal (original dashboard's 상세 분석 모달) ----
  function ensureFiveModal() {
    if (document.getElementById("fiveDetailModal")) return;
    if (!document.body || !document.createElement) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `<div class="sr-modal-backdrop" id="fiveDetailModal">
      <div class="sr-modal-panel">
        <div class="sr-modal-header"><div><h2 id="fiveModalTitle">종목 상세 분석</h2><p id="fiveModalSubtitle"></p></div>
        <button type="button" class="sr-modal-close" data-five-modal-close>&times;</button></div>
        <div class="sr-modal-section"><h4>🎯 7대 전략 스코어링 산출 근거</h4><div class="sr-breakdown-list" id="fiveModalBreakdown"></div></div>
        <div class="sr-modal-section"><h4>💰 세력 취득단가 추적 &amp; 안전마진 (전략 6)</h4><div id="fiveModalPrice"></div></div>
        <div class="sr-modal-section"><h4>📋 공시 개요</h4><p id="fiveModalSummary"></p><p id="fiveModalLinkWrap"></p></div>
      </div></div>`;
    document.body.appendChild(wrap.firstElementChild);
    const bd = document.getElementById("fiveDetailModal");
    bd.addEventListener("click", e => {
      if (e.target === bd || (e.target.closest && e.target.closest("[data-five-modal-close]"))) bd.classList.remove("open");
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape") bd.classList.remove("open"); });
  }

  function openFiveDetail(id) {
    const ev = fiveById.get(id);
    if (!ev) return;
    ensureFiveModal();
    const bd = document.getElementById("fiveDetailModal");
    if (!bd) return;
    const esc = escapeHtml;
    const s = fiveScore(ev);
    document.getElementById("fiveModalTitle").textContent = `${ev.company || ""} 상세 분석`;
    document.getElementById("fiveModalSubtitle").textContent =
      `${ev.event_name || ""} · 접수 ${ev.event_date || "-"}${s !== null ? ` · 알파 ${fmtSigned(s)}점` : ""}`;
    const items = Array.isArray(ev.score_breakdown) ? ev.score_breakdown : [];
    document.getElementById("fiveModalBreakdown").innerHTML = items.length
      ? items.map(b => {
          const p = Number((b && b.points)) || 0;
          const tone = p > 0 ? "sr-pt-pos" : p < 0 ? "sr-pt-neg" : "sr-pt-zero";
          return `<div class="sr-breakdown-item"><span class="sr-bd-name">${esc((b && b.strategy) || "")}<small>${esc((b && b.reason) || "")}</small></span><strong class="${tone}">${fmtSigned(p)}</strong></div>`;
        }).join("") + `<div class="sr-breakdown-item sr-bd-total"><span class="sr-bd-name">총 알파 스코어</span><strong>${s !== null ? fmtSigned(s) : "-"}</strong></div>`
      : `<div class="sr-bd-empty">채점 근거 데이터가 없습니다.</div>`;
    document.getElementById("fiveModalPrice").innerHTML =
      ev.est_avg_price == null && ev.current_price == null
        ? `<p class="sr-modal-note">가격 데이터가 아직 산출되지 않았습니다. (전략 6 평단 안전마진: 미산출)</p>`
        : fivePriceCellHtml(ev);
    document.getElementById("fiveModalSummary").textContent = (ev.insight && ev.insight.summary) || "";
    document.getElementById("fiveModalLinkWrap").innerHTML = ev.source_url
      ? `<a class="sr-mini-link" href="${esc(ev.source_url)}" target="_blank" rel="noopener noreferrer">📄 DART 원문 보기 ↗</a>` : "";
    bd.classList.add("open");
  }

  document.addEventListener("click", e => {
    const t = e.target && e.target.closest ? e.target.closest("[data-five-detail-btn]") : null;
    if (t) openFiveDetail(t.getAttribute("data-five-detail-btn"));
  });

  function errorRowHtml(ev, err) {
    return `<tr><td colspan="10" style="color:#f87171;padding:10px;">표시 오류: ${escapeHtml(ev && ev.event_id)} (${escapeHtml(err && err.message)})</td></tr>`;
  }

  window.renderTable = function (events) {
    const tbody = document.getElementById("eventsTableBody");
    if (!tbody) return;
    const thead = document.querySelector(".radar-table thead");
    if (currentTab === "5pct") {
      if (thead && !thead.dataset.srSwapped) { thead.dataset.srSwapped = "1"; thead.innerHTML = FIVE_THEAD_HTML; }
      renderFiveTab(events, tbody);
      return;
    }
    if (thead && thead.dataset.srSwapped) {
      thead.innerHTML = defaultTheadHtml;
      delete thead.dataset.srSwapped;
    }
    const summary = () => {
      if (typeof renderDashboardSummary === "function") {
        try { renderDashboardSummary(events); } catch (e) { console.warn("summary", e); }
      }
    };
    if (!events.length) {
      summary();
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 32px; color:#94a3b8;">조건에 일치하는 일정이 없습니다.</td></tr>`;
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
