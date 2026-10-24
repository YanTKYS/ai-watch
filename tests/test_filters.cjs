const { test } = require('node:test');
const assert = require('node:assert/strict');
const p = require('../parser.js');
const { harness, ready, settle, log, walk } = require('./app_harness.cjs');

const raw = [
  {title:'Alpha CLI',url:'https://a.example/1',category:'AIコーディング',feed:'Claude Code Releases',retrieved:'2026-09-30',published:'2026-01-01'},
  {title:'Alpha API',url:'https://a.example/2',category:'AIモデル',feed:'OpenAI News',retrieved:'2026-10-01',published:'2026-09-30'},
  {title:'Beta CLI',url:'https://a.example/3',category:'AIコーディング',feed:'Claude Code Releases',retrieved:'2026-10-02'},
  {title:'Alpha old format',url:'https://a.example/4',published:'2026-10-01'},
  {title:'Alpha bad date',url:'https://a.example/5',category:' ',feed:'',retrieved:'2026-02-30'},
];
const state = patch => ({query:'',categories:[],feeds:[],from:'',to:'',invalidDateInput:false,...patch});
const urls = list => list.map(e=>e.url);
const filter = patch => p.filterArticles(p.buildSearchEntries(raw),state(patch));
const choose = (h, key, value, checked=true) => {
  const checkbox=walk(h.nodes[key === 'categories' ? 'filter-categories' : 'filter-feeds']).find(n=>n.tag==='input' && n.value===value);
  assert.ok(checkbox, value); checkbox.focus(); checkbox.checked=checked; checkbox.emit('change');
  return checkbox;
};
function dates(h, from='', to='', bad=false) {
  h.nodes['filter-from'].value=from; h.nodes['filter-to'].value=to;
  h.nodes['filter-from'].validity={badInput:bad};
  h.nodes['filter-from'].emit('input');
}
async function options(h) {
  h.nodes['filter-panel'].open=true; h.nodes['filter-panel'].emit('toggle');
  h.respond(h.requests.length-1,JSON.stringify(raw)); await settle();
}

test('options derive from index, trim/deduplicate, omit missing metadata, never infer fixed labels', () => {
  const entries=p.buildSearchEntries([...raw,{title:'copy',url:'https://a.example/6',category:' AIモデル ',feed:'OpenAI News'}]);
  const options=p.articleFilterOptions(entries);
  assert.deepEqual(new Set(options.categories),new Set(['AIコーディング','AIモデル']));
  assert.deepEqual(new Set(options.feeds),new Set(['Claude Code Releases','OpenAI News']));
  assert.deepEqual(p.articleFilterOptions([]),{categories:[],feeds:[]});
});

test('OR within categories/feeds, AND across fields/keywords, NFKC and stable order are preserved', () => {
  assert.equal(filter({categories:['AIコーディング'],feeds:['Claude Code Releases']}).length,2);
  assert.equal(filter({categories:['AIモデル','AIコーディング'],feeds:['OpenAI News','Claude Code Releases']}).length,3);
  assert.deepEqual(urls(filter({query:'ＡＬＰＨＡ cli',categories:['AIモデル','AIコーディング'],feeds:['Claude Code Releases']})),['https://a.example/1']);
  assert.equal(filter({categories:['AIモデル'],feeds:['Claude Code Releases']}).length,0);
  const entries=p.buildSearchEntries(raw), before=JSON.stringify(entries), s=state({query:'Alpha'}), copy=JSON.stringify(s);
  assert.deepEqual(p.filterArticles(entries,s),p.searchArticles(entries,'Alpha'));
  assert.equal(JSON.stringify(entries),before); assert.equal(JSON.stringify(s),copy);
});

test('retrieval dates are inclusive, span months, allow one side and never substitute published', () => {
  assert.deepEqual(urls(filter({from:'2026-09-30',to:'2026-10-01'})),['https://a.example/2','https://a.example/1']);
  assert.deepEqual(urls(filter({from:'2026-10-02'})),['https://a.example/3']);
  assert.deepEqual(urls(filter({to:'2026-09-30'})),['https://a.example/1']);
  assert.deepEqual(urls(filter({from:'2026-01-01',to:'2026-01-01'})),[]);
  assert.equal(filter({}).length,5); // 欠損/不正な取得日も、期間制限がなければ従来どおり読める
});

test('invalid/reversed/native partial dates are errors, leap years and missing limits are valid', () => {
  for (const value of ['2026-02-29','2026-02-30','2026-13-01','2026-00-01','2026-01-00','2026-1-01','0000-01-01','bad']) {
    assert.equal(p.validFilterDate(value),false,value);
    assert.throws(()=>filter({from:value}),RangeError);
  }
  assert.equal(p.validFilterDate('2024-02-29'),true);
  assert.throws(()=>filter({from:'2026-10-02',to:'2026-10-01'}),/開始日/);
  assert.throws(()=>filter({invalidDateInput:true}),/すべて入力/);
  assert.equal(p.validateFilterDates(state()),'');
  assert.equal(p.hasArticleFilters(state()),false);
  assert.equal(p.hasArticleFilters(state({from:'2026-10-01'})),true);
  assert.deepEqual(p.searchArticles(p.buildSearchEntries(raw),''),[]); // 既存の検索APIは互換
});

test('opening filters fetches once, keeps daily/focus and offers full-index choices without unsafe HTML', async () => {
  const h=await ready('?sample'); h.nodes['filter-toggle'].focus();
  h.nodes['filter-panel'].open=true; h.nodes['filter-panel'].emit('toggle'); h.nodes['filter-panel'].emit('toggle');
  assert.equal(h.requests.length,3); assert.equal(h.requests[2].url,'samples/data/search-index.json');
  assert.match(h.nodes.content.textContent,/Daily/);
  h.respond(2,JSON.stringify([...raw,{title:'safe',url:'https://a.example/html',category:'<img onerror=bad>',feed:'<script>'}])); await settle();
  assert.equal(h.document.activeElement,h.nodes['filter-toggle']);
  assert.ok(walk(h.nodes['filter-categories']).some(n=>n.textContent==='<img onerror=bad>' && n.childNodes.length===0));
  const checkbox=choose(h,'categories','AIコーディング');
  assert.equal(h.document.activeElement,checkbox);
  assert.match(h.nodes.content.textContent,/絞り込み結果2件/);
  assert.ok(walk(h.nodes['filter-feeds']).some(n=>n.textContent==='OpenAI News'));
  h.nodes['filter-panel'].emit('toggle'); assert.equal(h.requests.length,3);
});

test('queryless filters combine with query; three clear actions keep their distinct meaning and restore month/order', async () => {
  const h=await ready();
  h.nodes['month-select'].value='2026-09'; h.nodes['month-select'].emit('change'); h.respond(2,log('September','2026-09')); await settle();
  h.nodes['order-select'].value='asc'; h.nodes['order-select'].emit('change'); await options(h);
  choose(h,'categories','AIコーディング'); choose(h,'feeds','Claude Code Releases'); dates(h,'2026-09-30','2026-10-01');
  assert.match(h.nodes.content.textContent,/絞り込み結果1件/);
  assert.equal(h.nodes['month-select'].disabled,true);
  assert.match(h.nodes['active-conditions'].textContent,/Claude Code Releases.*2026-09-30/);
  h.search('Alpha'); assert.match(h.nodes.content.textContent,/絞り込み結果1件/);
  h.nodes['search-clear'].emit('click');
  assert.equal(h.get('viewState.query'),''); assert.equal(h.get('viewState.feeds.length'),1);
  assert.match(h.nodes.content.textContent,/絞り込み結果1件/);
  h.search('Alpha'); h.nodes['filters-clear'].emit('click');
  assert.equal(h.get('viewState.query'),'Alpha'); assert.equal(h.get('viewState.feeds.length'),0);
  assert.match(h.nodes.content.textContent,/検索結果4件/);
  assert.equal(h.document.activeElement,h.nodes['filter-toggle']);
  h.nodes['conditions-clear'].emit('click');
  assert.match(h.nodes.content.textContent,/September/); assert.equal(h.get('current.ym'),'2026-09'); assert.equal(h.get('sortOrder'),'asc');
  assert.equal(h.nodes['month-select'].disabled,false); assert.equal(h.nodes['conditions-clear'].hidden,true);
  assert.equal(h.document.activeElement,h.nodes['search-input']);
});

test('zero results retain visible conditions and clearing works; invalid dates are never announced as zero', async () => {
  const h=await ready(); await options(h);
  choose(h,'categories','AIモデル'); choose(h,'feeds','Claude Code Releases');
  assert.match(h.nodes.content.textContent,/条件に一致する記事はありません/);
  assert.match(h.nodes['active-conditions'].textContent,/AIモデル.*Claude Code Releases/);
  assert.match(h.nodes['view-announcement'].textContent,/0件/);
  dates(h,'2026-10-02','2026-10-01');
  assert.match(h.nodes.status.textContent,/開始日/); assert.equal(h.nodes.content.textContent,'');
  assert.doesNotMatch(h.nodes['view-announcement'].textContent,/0件/);
  assert.equal(h.nodes['filter-from'].getAttribute('aria-invalid'),'true');
  dates(h,'','',true); assert.match(h.nodes.status.textContent,/すべて入力/);
  h.nodes['conditions-clear'].emit('click'); assert.match(h.nodes.content.textContent,/Daily/);
  assert.equal(h.get('viewState.invalidDateInput'),false);
});

test('candidate failure leaves daily usable, retry remains focused and success supplies choices', async () => {
  const h=await ready(); h.nodes['filter-panel'].open=true; h.nodes['filter-panel'].emit('toggle');
  h.fail(2); await settle();
  assert.match(h.nodes.content.textContent,/Daily/); assert.equal(h.nodes['load-retry'].hidden,true);
  assert.equal(h.nodes['filter-options-retry'].hidden,false);
  h.nodes['filter-options-retry'].focus(); h.nodes['filter-options-retry'].emit('click'); h.nodes['filter-options-retry'].emit('click');
  assert.equal(h.requests.length,4); assert.equal(h.nodes['filter-options-retry'].getAttribute('aria-disabled'),'true');
  h.respond(3,JSON.stringify(raw)); await settle();
  assert.equal(h.document.activeElement.tag,'input'); assert.equal(h.nodes['filter-options-retry'].hidden,true);
  assert.match(h.nodes.content.textContent,/Daily/);
});

test('date-only loading failure uses F05 retry and preserves latest conditions when a shared request finishes', async () => {
  const h=await ready(); dates(h,'2026-09-30','2026-10-01'); h.fail(2); await settle();
  assert.equal(h.nodes['load-retry'].hidden,false); h.nodes['load-retry'].focus(); h.retry();
  dates(h,'2026-10-02','2026-10-02');
  h.respond(3,JSON.stringify(raw)); await settle();
  assert.equal(h.requests.length,4); assert.match(h.nodes.content.textContent,/Beta CLI/);
  assert.doesNotMatch(h.nodes.content.textContent,/Alpha API/); assert.match(h.nodes['active-conditions'].textContent,/2026-10-02/);
});

test('late monthly responses cannot overwrite filters; clearing while index is pending protects daily notifications', async () => {
  for (const fails of [false,true]) {
    const h=await ready(); h.get('showMonth("2026-09")'); dates(h,'2026-10-01');
    h.respond(3,JSON.stringify(raw)); await settle(); const before=h.announcements.length;
    if (fails) h.fail(2); else h.respond(2,log('Old','2026-09'));
    await settle(); assert.equal(h.announcements.length,before); assert.match(h.nodes.content.textContent,/絞り込み結果/);
    const other=await ready(); other.nodes['filter-panel'].open=true; other.nodes['filter-panel'].emit('toggle'); dates(other,'2026-10-01');
    other.nodes['conditions-clear'].emit('click'); const n=other.announcements.length;
    if (fails) other.fail(2); else other.respond(2,JSON.stringify(raw));
    await settle(); assert.match(other.nodes.content.textContent,/Daily/); assert.equal(other.announcements.length,n);
  }
});

test('IME/debounce with filter changes applies the confirmed current query, not an intermediate result', async () => {
  const h=await ready(); await options(h);
  h.input('Al'); choose(h,'categories','AIコーディング');
  assert.equal(h.get('viewState.query'),'Al'); assert.match(h.nodes.content.textContent,/Alpha CLI/);
  h.nodes['search-input'].emit('compositionstart'); h.input('変換中',{isComposing:true});
  choose(h,'feeds','Claude Code Releases'); const before=h.announcements.length;
  h.flushTimers(); assert.equal(h.announcements.length,before);
  h.nodes['search-input'].value='Beta'; h.nodes['search-input'].emit('compositionend'); h.flushTimers();
  assert.equal(h.get('viewState.query'),'Beta'); assert.match(h.nodes.content.textContent,/Beta CLI/);
  assert.doesNotMatch(h.nodes.content.textContent,/Alpha CLI/);
});
