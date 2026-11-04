const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('search resolves all related tickers and source company names', () => {
  const ctx = vm.createContext({});
  vm.runInContext(fs.readFileSync('site/js/filters.js', 'utf8'), ctx);
  const count = vm.runInContext(`(() => {
    const engine = new EventFilter([{ticker:'', company:'체코 원전', event_name:'입찰',
      related_securities:[{ticker:'034020', from_entity:'두산에너빌리티'}, {ticker:'052690'}]}]);
    engine.setCriterion('search', '052690');
    return engine.apply().length;
  })()`, ctx);
  assert.equal(count, 1);
});

test('dashboard shows related tickers rather than blank primary and counts down future dates', () => {
  const body = {innerHTML:''};
  const ctx = vm.createContext({document:{getElementById:()=>body, addEventListener:()=>{}}});
  vm.runInContext(fs.readFileSync('site/js/app.js', 'utf8'), ctx);
  vm.runInContext(`renderTable([{event_id:'E', ticker:'', country:'KR', company:'원전',
    event_name:'입찰', event_date:'2026-12-01', d_day:28,
    related_securities:[{ticker:'034020', relation_grade:'B'}, {ticker:'052690', relation_grade:'B'}]}])`, ctx);
  assert.match(body.innerHTML, /034020/);
  assert.match(body.innerHTML, /052690/);
  assert.match(body.innerHTML, /D-28/);
});

test('zero-sample strategies display missing data instead of zero-percent returns', () => {
  const elements = {};
  const ctx = vm.createContext({document:{getElementById:id => elements[id] ||= {innerHTML:'', textContent:''}, addEventListener:()=>{}}});
  vm.runInContext(fs.readFileSync('site/js/event-detail.js', 'utf8'), ctx);
  vm.runInContext(`renderDetail({company:'test', related_securities:[], strategy_summary:[{name:'D0 -> D+5', sample_n:0, mean_return:0, mean_abnormal_return:0}]})`, ctx);
  // Inspect only the strategy table: other empty-state sections have no percentages.
  assert.doesNotMatch(elements.strategiesTableBody.innerHTML, /0\.0%/);
  assert.match(elements.strategiesTableBody.innerHTML, /데이터 없음/);
});

test('upcoming and evidence filters retain period windows and inspect every relation', () => {
  const ctx = vm.createContext({});
  vm.runInContext(fs.readFileSync('site/js/filters.js', 'utf8'), ctx);
  const ids = vm.runInContext(`(() => {
    const engine = new EventFilter([
      {event_id:'past',d_day:-5,window_end:'2026-10-01',insight:{tier:'PAST',coverage:{complete_events:3}}},
      {event_id:'period',d_day:-2,window_end:'2099-12-31',relation_grade:'A',related_securities:[{relation_grade:'B',ticker:'052690'}],insight:{tier:'WATCH',coverage:{complete_events:2}}}
    ]);
    engine.setCriterion('horizon','upcoming'); engine.setCriterion('grade','B');
    return engine.apply().map(e=>e.event_id).join(',');
  })()`, ctx);
  assert.equal(ids, 'period');
});

test('priority cell explains missing evidence and does not present a buy signal', () => {
  const ctx = vm.createContext({document:{getElementById:()=>null,addEventListener:()=>{}},escapeHtml:s=>String(s||'')});
  vm.runInContext(fs.readFileSync('site/js/insight-ui.js', 'utf8'), ctx);
  const html = vm.runInContext(`renderPriorityCell({insight:{score:44,tier:'WATCH',label:'일정 관찰',reasons:['공식 일정'],missing:['과거 사건 표본']}})`, ctx);
  assert.match(html, /일정 관찰/);
  assert.match(html, /과거 사건 표본/);
  assert.doesNotMatch(html, /매수 신호/);
});

test('macro proxy statistics show market returns rather than zero excess returns', () => {
  const el = {innerHTML:''};
  const ctx = vm.createContext({document:{getElementById:()=>el,addEventListener:()=>{}}});
  vm.runInContext(fs.readFileSync('site/js/event-detail.js', 'utf8'), ctx);
  vm.runInContext(`renderBacktestStats({market_proxy_study:true,peer_sample_n:10,d5_sample_n:10,backtest_summary:{mean_return:.1,mean_abnormal_return:0,win_rate:0,absolute_win_rate:1}})`,ctx);
  assert.match(el.innerHTML,/시장 절대수익률/);
  assert.match(el.innerHTML,/10\.0%/);
});
