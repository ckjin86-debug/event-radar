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
