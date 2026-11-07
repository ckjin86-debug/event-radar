const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Behavioural check for the 5pct tab's Super Radar reproduction:
// original table columns, KPI cards, market switcher (KR/US) and the
// thead swap/restore cycle, driven through the real filter engine.
test('5pct tab reproduces the Super Radar dashboard and market switcher', async () => {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' });
  const five = [
    {
      event_id: 'F1', event_type: '5PCT_OWNERSHIP', source_name: 'DART_5PCT',
      source_url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261107000123',
      category: '지분공시', country: 'KR', company: '테스트전자', ticker: '005930',
      event_name: '주식등의대량보유상황보고서(약식) (대표보고자: 대주주 홍길동)',
      event_date: today, d_day: 0, status: 'CONFIRMED',
      alpha_score: 9, event_score: 9,
      score_breakdown: [
        { strategy: '전략 1 (보고 주체 가중치)', reason: '슈퍼개미/개인 투자자', points: 2 },
        { strategy: '전략 2 (연속 매집)', reason: '2회 연속 순매수 확대', points: 3 },
      ],
      investor_class: '슈퍼개미/개인', purpose_prev: '단순투자', purpose_current: '일반투자',
      accumulation_count: 2, freshness: 'CURRENT',
      insight: { tier: 'HIGH', label: '지분공시', summary: '슈퍼개미의 경영참여성 매집', score: 9 },
      related_securities: [{ ticker: '005930', name: '테스트전자', relation_grade: 'DIRECT' }],
    },
    {
      event_id: 'F2', event_type: '5PCT_OWNERSHIP', source_name: 'DART_5PCT',
      source_url: '', category: '지분공시', country: 'KR', company: '신규진입주', ticker: '000660',
      event_name: '주식등의대량보유상황보고서(일반) (대표보고자: 국민연금공단)',
      event_date: today, d_day: 0, status: 'CONFIRMED',
      alpha_score: -3, event_score: -3,
      score_breakdown: [{ strategy: '전략 7 (지분 축소)', reason: '지분율 -1.2%p 축소', points: -1 }],
      investor_class: '일반법인/기타', purpose_prev: null, purpose_current: '단순투자',
      accumulation_count: 0, freshness: 'RECENT',
      insight: { tier: 'RISK', label: '지분공시', summary: '지분 축소', score: -3 },
      related_securities: [{ ticker: '000660', name: '신규진입주', relation_grade: 'DIRECT' }],
    },
  ];

  const makeEl = () => ({
    innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, setAttribute() {}, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [], appendChild() {},
  });
  const elements = {};
  const thead = makeEl();
  thead.innerHTML = '<tr><th>D-Day</th></tr>';
  const documentStub = {
    getElementById: id => elements[id] || (elements[id] = makeEl()),
    querySelector: sel => (sel === '.radar-table thead' ? thead : null),
    querySelectorAll: () => [],
    addEventListener() {},
    createElement: () => { const el = makeEl(); el.firstElementChild = makeEl(); return el; },
    body: makeEl(),
  };
  const ctx = vm.createContext({
    document: documentStub,
    location: { search: '' },
    console,
    addEventListener() {},
    fetch: url => (String(url).includes('five_pct')
      ? Promise.resolve({ ok: true, json: async () => five })
      : String(url).includes('events.json')
        ? Promise.resolve({ ok: true, json: async () => [] })
        : Promise.resolve({ ok: false })),
  });
  ctx.window = ctx;
  vm.runInContext(fs.readFileSync('site/js/filters.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync('site/js/app.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync('site/js/radar-tabs.js', 'utf8'), ctx);
  // app.js creates the shared filterEngine inside initDashboard().
  vm.runInContext(`initDashboard()`, ctx);
  await new Promise(r => setTimeout(r, 30));

  const tbody = elements.eventsTableBody;
  vm.runInContext(`switchRadarTab('5pct')`, ctx);
  const overview = elements.radarOverview;

  // Original table header and row layout.
  assert.match(thead.innerHTML, /스코어/);
  assert.match(thead.innerHTML, /① 신규접수일 대비/);
  assert.match(thead.innerHTML, /② 최초 5% 공시일 대비/);
  assert.match(tbody.innerHTML, /sr-score-badge/);
  assert.match(tbody.innerHTML, /\+9/);
  assert.match(tbody.innerHTML, /대주주 홍길동/);
  assert.match(tbody.innerHTML, /슈퍼개미\/개인/);
  assert.match(tbody.innerHTML, /★목적상향\(일반\/13D\)/);
  assert.match(tbody.innerHTML, /★2연속 매집/);
  assert.match(tbody.innerHTML, /CURRENT · D-0/);
  assert.match(tbody.innerHTML, /D\+5 도래전/);
  assert.match(tbody.innerHTML, /★ 금번이 최초 5% 진입/); // F2: no previous filing
  assert.doesNotMatch(tbody.innerHTML, /점수 미산정/);

  // KPI cards + market switcher in the overview area.
  assert.match(overview.innerHTML, /sr-market-switcher/);
  assert.match(overview.innerHTML, /한국 DART \(5% 공시\)/);
  assert.match(overview.innerHTML, /미국 SEC \(13D \/ 13G\)/);
  assert.match(overview.innerHTML, /유효 신규 공시/);
  assert.match(overview.innerHTML, /최고 알파 스코어 종목/);
  assert.match(overview.innerHTML, /테스트전자 \(\+9점\)/);

  // US market: no rows yet -> dedicated empty state.
  vm.runInContext(`switchFiveMarket('US')`, ctx);
  assert.match(tbody.innerHTML, /미국 SEC \(13D \/ 13G\) 공시가 아직 수집되지 않았습니다/);
  assert.match(overview.innerHTML, /sr-market-btn active" onclick="switchFiveMarket\('US'\)/);

  // Back to KR, then leave the tab: header is restored, other tabs unchanged.
  vm.runInContext(`switchFiveMarket('KR')`, ctx);
  assert.match(tbody.innerHTML, /테스트전자/);
  vm.runInContext(`switchRadarTab('all')`, ctx);
  assert.equal(thead.innerHTML, '<tr><th>D-Day</th></tr>');
  assert.match(tbody.innerHTML, /five-score/);
  assert.doesNotMatch(tbody.innerHTML, /sr-score-badge/);
});
