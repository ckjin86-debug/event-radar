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
      if (this.criteria.horizon !== "all") {
        const d = ev.d_day;
        if (this.criteria.horizon === "today" && d !== 0) return false;
        if (this.criteria.horizon === "7d" && (d < 0 || d > 7)) return false;
        if (this.criteria.horizon === "30d" && (d < 0 || d > 30)) return false;
        if (this.criteria.horizon === "90d" && (d < 0 || d > 90)) return false;
      }

      if (this.criteria.country !== "all" && ev.country !== this.criteria.country) {
        return false;
      }

      if (this.criteria.category !== "all") {
        const t = (ev.event_type || "").toUpperCase();
        const source = (ev.source_name || "").toUpperCase();
        const text = `${ev.company || ""} ${ev.event_name || ""}`.toLowerCase();
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
        if (cat === "원전" && !/(원전|원자력|nuclear|dukovany|barakah)/i.test(text)) return false;
        if (cat === "경영권" && t !== "CONTROL_DISPUTE") return false;
        if (cat === "정치" && t !== "ELECTION") return false;
      }

      if (this.criteria.grade !== "all" && ev.relation_grade !== this.criteria.grade) {
        return false;
      }

      if (this.criteria.status !== "all" && ev.status !== this.criteria.status) {
        return false;
      }

      if (this.criteria.search) {
        const q = this.criteria.search.toLowerCase().trim();
        const combined = `${ev.ticker} ${ev.company} ${ev.event_name} ${ev.event_type} ${ev.source_name}`.toLowerCase();
        if (!combined.includes(q)) return false;
      }

      return true;
    });

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
