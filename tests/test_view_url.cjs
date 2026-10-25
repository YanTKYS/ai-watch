const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readViewURL, writeViewURL, articleId } = require('../view-url.js');
const { harness, ready, settle, log, entries, walk } = require('./app_harness.cjs');
const state = patch => ({month:'2026-09',order:'asc',query:'',categories:[],feeds:[],from:'',to:'',invalidDateInput:false,...patch});
const params = h => new URLSearchParams(h.location.search);
const cards = h => walk(h.nodes.content).filter(n=>n.tag==='article');
async function fromURL(query, data = entries) {
  const h=harness(query); h.respond(0,'["2026-10","2026-09"]'); await settle();
  h.respond(1,JSON.stringify(data)); await settle(); return h;
}

test('URL roundtrip preserves project path/sample and canonicalizes repeated selections without comma ambiguity',()=>{
  const original=state({query:'Ｃｏｄｅｘ 日本語 & +',categories:['B','A, B','B'],feeds:['Y','X'],from:'2026-09-30',to:'2026-10-02'});
  const value=writeViewURL('https://example.com/ai-watch/?sample&unused=x',original,articleId('https://a.example/1'));
  assert.ok(value.startsWith('/ai-watch/?sample=&month=2026-09&order=asc&'));
  const parsed=readViewURL('https://example.com'+value);
  assert.deepEqual(parsed.state,{...original,categories:['A, B','B'],feeds:['X','Y']});
  assert.equal(parsed.sample,true); assert.ok(parsed.article.startsWith('article-'));
  assert.equal(writeViewURL('https://example.com'+value,parsed.state,parsed.article),value);
});

test('invalid/missing/duplicate/oversized values have bounded deterministic corrections',()=>{
  const p=readViewURL('https://x/?month=0000-03&month=2026-10&order=oops&q='+ 'a'.repeat(700)+'&category='+ 'b'.repeat(201)+'&from=2026-02-29&to=bad#article-%3Cscript%3E');
  assert.equal(p.state.month,'');assert.equal(p.state.order,'desc');assert.equal(p.state.query.length,500);
  assert.deepEqual(p.state.categories,[]);assert.equal(p.article,'');assert.equal(p.state.from,'');
  assert.ok(p.warnings.length>=6);
  const unicode=readViewURL('https://x/?q='+encodeURIComponent('a'.repeat(499)+'😀'));
  assert.equal(unicode.state.query,'a'.repeat(499));
  assert.deepEqual(readViewURL('https://x/?from=2026-10-02&to=2026-09-30').state,state({month:'',order:'desc'}));
  assert.equal(readViewURL('https://x/?from=2024-02-29').state.from,'2024-02-29');
  const many=readViewURL('https://x/?'+Array.from({length:60},(_,i)=>'feed='+i).join('&'));
  assert.equal(many.state.feeds.length,50);
  const known=readViewURL('https://x/?category=Gone&feed=Good',{categories:[],feeds:['Good']});
  assert.deepEqual(known.state.categories,[]);assert.deepEqual(known.state.feeds,['Good']);
});

test('article identity preserves complete canonical validated URLs and cannot hash-collide',()=>{
  assert.equal(articleId(' HTTPS://A.EXAMPLE:443/path '),articleId('https://a.example/path'));
  const values=['https://a.example/a','https://a.example/a?q=1','https://a.example/a?q=2','https://a.example/a#x','https://a.example/日本語'];
  assert.equal(new Set(values.map(articleId)).size,values.length);
  for(const v of values) assert.match(articleId(v),/^article-[A-Za-z0-9_-]+$/);
  assert.equal(articleId('javascript:alert(1)'),'');assert.equal(articleId('https://a.example/'+'x'.repeat(8192)),'');
  const temporary=writeViewURL('https://x/',state({from:'2026-10-01',invalidDateInput:true}));
  assert.ok(!temporary.includes('from='));assert.ok(!temporary.includes('invalidDateInput'));
});

test('fresh URL restores all controls, queryless OR/AND filters and three clears retain daily month/order',async()=>{
  const data=[{title:'Alpha',url:'https://a.example/1',category:'A',feed:'One',retrieved:'2026-10-01'},
    {title:'Alpha second',url:'https://a.example/2',category:'B',feed:'Two',retrieved:'2026-09-30'}];
  const url='?sample&month=2026-09&order=asc&q=Alpha&category=B&category=A&category=A&feed=Two&feed=One&from=2026-09-30&to=2026-10-01';
  const h=await fromURL(url,data);
  assert.equal(cards(h).length,2);assert.equal(h.nodes['month-select'].value,'2026-09');assert.equal(h.nodes['order-select'].value,'asc');
  assert.equal(h.nodes['search-input'].value,'Alpha');assert.equal(h.nodes['filter-from'].value,'2026-09-30');
  assert.equal(params(h).getAll('category').join(','),'A,B');
  assert.ok(h.requests.every(r=>r.url.startsWith('samples/')));
  h.nodes['search-clear'].emit('click'); assert.equal(params(h).has('q'),false);assert.equal(cards(h).length,2);
  h.search('Alpha');h.nodes['filters-clear'].emit('click');assert.equal(params(h).get('q'),'Alpha');assert.equal(params(h).has('category'),false);
  h.nodes['conditions-clear'].emit('click');h.respond(2,log('September','2026-09'));await settle();
  assert.match(h.nodes.content.textContent,/September/);assert.equal(params(h).get('month'),'2026-09');assert.equal(params(h).get('order'),'asc');
});

test('typing sessions keep one undo boundary, Enter commits, and popstate does not append history',async()=>{
  const h=await ready();h.input('A');h.flushTimers();h.respond(2,JSON.stringify(entries));await settle();
  h.input('Al');h.flushTimers();h.input('Alpha');h.flushTimers();
  assert.equal(h.historyURLs.length,2);assert.equal(params(h).get('q'),'Alpha');
  h.nodes['search-input'].emit('keydown',{key:'Enter'});
  h.input('Beta');h.flushTimers();assert.equal(h.historyURLs.length,3);
  h.history.go(-1);await settle();assert.equal(h.nodes['search-input'].value,'Alpha');assert.equal(cards(h).length,50);
  h.history.go(-1);await settle();assert.match(h.nodes.content.textContent,/Daily/);
  h.history.go(1);await settle();assert.equal(params(h).get('q'),'Alpha');assert.equal(h.historyURLs.length,3);
});

test('Back cancels debounce/IME and delayed success/failure cannot replace restored URL or announcements',async()=>{
  for(const fails of [false,true]) {
    const h=await ready();h.search('Alpha');
    h.nodes['search-input'].emit('compositionstart');h.input('変換中',{isComposing:true});
    h.history.go(-1);const before=h.announcements.length, url=h.location.href;
    if(fails)h.fail(2);else h.respond(2,JSON.stringify(entries));await settle();h.flushTimers();
    assert.equal(h.location.href,url);assert.equal(h.announcements.length,before);assert.match(h.nodes.content.textContent,/Daily/);
    assert.equal(h.nodes['search-input'].value,'');assert.equal(h.get('composing'),false);
  }
});

test('pending month from before Back cannot replace restored daily state',async()=>{
  const h=await ready();h.nodes['month-select'].value='2026-09';h.nodes['month-select'].emit('change');
  h.history.go(-1);h.respond(3,log('Restored'));await settle();h.respond(2,log('Stale','2026-09'));await settle();
  assert.equal(params(h).get('month'),'2026-10');assert.match(h.nodes.content.textContent,/Restored/);assert.doesNotMatch(h.nodes.content.textContent,/Stale/);
});

test('daily article target opens collapsed date, focuses/announces, and duplicates retain unique IDs on reorder',async()=>{
  const id=articleId('https://a.example/Old');
  const h=harness('?month=2026-09#'+id);h.respond(0,'["2026-10","2026-09"]');await settle();
  h.respond(1,log('New','2026-09')+'## 2026-09-01\n### Coding\n#### Old\n- URL: https://a.example/Old\n#### Repeated\n- URL: https://a.example/Old\n');await settle();
  const target=cards(h).find(c=>c.id===id);assert.equal(target.closest('details').open,true);assert.equal(h.document.activeElement,target.firstChild);
  assert.match(h.nodes['view-announcement'].textContent,/共有記事へ移動.*Old/);assert.equal(target.scrolled,true);
  const ids=cards(h).map(c=>c.id).sort();assert.equal(new Set(ids).size,3);
  h.nodes['order-select'].value='asc';h.nodes['order-select'].emit('change');assert.deepEqual(cards(h).map(c=>c.id).sort(),ids);
});

test('search article beyond page 50 is loaded before focus; share anchor remains directly usable',async()=>{
  const id=articleId(entries[110].url), h=await fromURL('?sample&month=2026-09&order=asc&q=Alpha#'+id);
  assert.equal(cards(h).length,120);assert.equal(h.document.activeElement.textContent,'Alpha 110');
  const share=walk(cards(h)[110]).find(n=>n.className==='share');
  assert.equal(share.target,undefined);assert.ok(share.href.startsWith('/project/?sample='));assert.ok(share.href.endsWith('#'+id));
  let prevented=false;share.emit('click',{button:0,preventDefault(){prevented=true;}});assert.equal(prevented,true);
});

test('missing/filtered/index-absent targets keep the normal list and conditions, then remove stale fragment',async()=>{
  for(const query of ['Alpha','NoMatch']) {
    const h=await fromURL('?q='+query+'#article-missing');
    assert.ok(h.nodes.content.textContent.includes(query));assert.equal(params(h).get('q'),query);assert.equal(h.location.hash,'');
    assert.match(h.nodes['url-notice'].textContent,/現在の一覧にありません/);assert.equal(h.nodes['load-retry'].hidden,true);
  }
});

test('unknown choices and nonexistent month normalize once; fetch failures preserve target for retry',async()=>{
  const h=await fromURL('?month=2026-01&q=Alpha&category=Gone');
  assert.equal(params(h).get('month'),'2026-10');assert.equal(params(h).has('category'),false);assert.equal(cards(h).length,50);
  assert.match(h.nodes['url-notice'].textContent,/ないカテゴリ/);assert.equal(h.historyURLs.length,1);
  const id=articleId('https://a.example/Daily'), retry=harness('?#'+id);
  retry.respond(0,'["2026-10"]');await settle();retry.fail(1);await settle();assert.equal(retry.location.hash,'#'+id);
  retry.retry();retry.respond(2,log());await settle();assert.equal(retry.document.activeElement.textContent,'Daily');
});
