/**
 * Multi-criteria filter engine for Event Radar.
 */

class EventFilter {
  constructor(events) {
    this.allEvents = events || [];
    this.criteria = {
      horizon: "all",
      country: "all",
      category: "all",
      grade: "all",
      status: "all",
      search: "",
      sort: "score_desc",
    };
  }

  setCriterion(key, value) {
    this.criteria[key] = value;
  }

  apply() {
    let result = this.allEvents.filter(ev => {
      // 1. Horizon filter (based on event_date / window_start d_day)
      if (this.criteria.horizon !== "all") {
        const d = ev.d_day;
        if (this.criteria.horizon === "today" && d !== 0) return false;
        if (this.criteria.horizon === "7d" && (d < 0 || d > 7)) return false;
        if (this.criteria.horizon === "30d" && (d < 0 || d > 30)) return false;
        if (this.criteria.horizon === "90d" && (d < 0 || d > 90)) return false;
      }

      // 2. Country filter
      if (this.criteria.country !== "all" && ev.country !== this.criteria.country) {
        return false;
      }

      // 3. Category / Event Type filter
      if (this.criteria.category !== "all") {
        const t = (ev.event_type || "").toUpperCase();
        const source = (ev.source_name || "").toUpperCase();
        const cat = this.criteria.category;
        if (cat === "증자" && !t.includes("ISSUE")) return false;
        if (cat === "분할" && !t.includes("SPLIT")) return false;
        if (cat === "락업" && !t.includes("LOCKUP")) return false;
        if (cat === "실적" && !t.includes("EARNINGS")) return false;
        if (cat === "FDA" && !t.includes("FDA") && !t.includes("CLINICAL")) return false;
        if (cat === "지수" && !t.includes("INDEX")) return false;
        if (cat === "엔터" && !t.includes("ENTERTAINMENT")) return false;
        if (cat === "게임" && !t.includes("GAME")) return false;
        if (cat === "IPO" && !t.startsWith("IPO_")) return false;
        if (cat === "FOMC" && !t.includes("FOMC")) return false;
        if (cat === "뉴스촉매" && source !== "NEWS_FUTURE") return false;
        if (cat === "CAPEX" && !t.includes("CAPEX")) return false;
      }

      // 4. Relation Grade filter
      if (this.criteria.grade !== "all" && ev.relation_grade !== this.criteria.grade) {
        return false;
      }

      // 5. Status filter
      if (this.criteria.status !== "all" && ev.status !== this.criteria.status) {
        return false;
      }

      // 6. Search query
      if (this.criteria.search) {
        const q = this.criteria.search.toLowerCase().trim();
        const combined = `${ev.ticker} ${ev.company} ${ev.event_name} ${ev.event_type} ${ev.source_name}`.toLowerCase();
        if (!combined.includes(q)) return false;
      }

      return true;
    });

    // 7. Sort
    result.sort((a, b) => {
      if (this.criteria.sort === "score_desc") {
        return b.event_score - a.event_score;
      }
      if (this.criteria.sort === "dday_asc") {
        return a.d_day - b.d_day;
      }
      return 0;
    });

    return result;
  }
}
