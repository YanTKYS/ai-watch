// 実app.jsを通信・タイマー待ちなしで実行し、遅延応答の順番も制御する。
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag, text = '') {
    this.tag = tag; this.text = text; this.childNodes = []; this.listeners = {};
    this.hidden = false; this.disabled = false; this.selectedValue = null;
  }
  set textContent(value) { this.text = String(value); this.childNodes = []; }
  get textContent() { return this.text + this.childNodes.map(n => n.textContent).join(''); }
  get options() { return this.childNodes; }
  get value() { return this.selectedValue ?? (this.tag === 'select' ? this.options[0]?.value ?? '' : ''); }
  set value(value) { this.selectedValue = value; }
  appendChild(node) {
    this.childNodes.push(...(node.tag === '#fragment' ? node.childNodes : [node]));
    return node;
  }
  replaceChildren(...nodes) { this.childNodes = []; nodes.forEach(n => this.appendChild(n)); }
  addEventListener(name, fn) { (this.listeners[name] ??= []).push(fn); }
  emit(name, event = {}) { for (const fn of this.listeners[name] ?? []) fn(event); }
  focus() {}
}

function harness() {
  const nodes = {};
  const requests = [];
  const context = vm.createContext({
    URL, URLSearchParams, location: { search: '' },
    // 検索はEnterで確定し、debounceの実時間待ちは不要。
    setTimeout: () => 1, clearTimeout: () => {},
    document: {
      getElementById: id => nodes[id] ??= new Element(id.endsWith('-select') ? 'select' : 'div'),
      createElement: tag => new Element(tag), createTextNode: text => new Element('#text', text),
      createDocumentFragment: () => new Element('#fragment'),
    },
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
  });
  const root = path.join(__dirname, '..');
  vm.runInContext(fs.readFileSync(path.join(root, 'parser.js'), 'utf8') + '\n' +
                  fs.readFileSync(path.join(root, 'app.js'), 'utf8'), context);
  return {
    nodes, requests, get: expression => vm.runInContext(expression, context),
    respond(i, text, ok = true) { requests[i].resolve({ ok, status: ok ? 200 : 503, text: async () => text }); },
    fail(i) { requests[i].reject(new Error('offline')); },
    search(query) { nodes['search-input'].value = query; nodes['search-input'].emit('keydown', { key: 'Enter' }); },
    retry() { nodes['load-retry'].emit('click'); },
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const log = (title = 'Daily', ym = '2026-10') => `# Month\n## ${ym}-02\n### Coding\n#### ${title}\n- URL: https://a.example/${title}\n`;
const entries = Array.from({ length: 60 }, (_, i) => ({ title: `Alpha ${i}`, url: `https://a.example/${i}` }));
const walk = node => [node, ...node.childNodes.flatMap(walk)];
async function ready() {
  const h = harness();
  h.respond(0, '["2026-10","2026-09"]'); await settle();
  h.respond(1, log()); await settle();
  return h;
}

test('month list: offline -> retry only months once -> daily, preserving order', async () => {
  const h = harness();
  h.fail(0); await settle();
  assert.match(h.nodes.status.textContent, /取得できません/);
  assert.equal(h.nodes['load-retry'].hidden, false);
  h.nodes['order-select'].value = 'asc'; h.nodes['order-select'].emit('change');
  h.retry(); h.retry();
  assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1].url, 'data/months.json');
  assert.equal(h.nodes['load-retry'].hidden, true);
  h.respond(1, '["2026-10"]'); await settle(); h.respond(2, log()); await settle();
  assert.equal(h.get('sortOrder'), 'asc');
  assert.equal(h.get('current.ym'), '2026-10');
  assert.equal(h.nodes.status.hidden, true);
});

test('invalid month list is retryable; empty list is normal', async () => {
  for (const invalid of ['{broken', '{}', '["2026-99"]']) {
    const h = harness(); h.respond(0, invalid); await settle();
    assert.match(h.nodes.status.textContent, /データ形式/);
    h.retry(); h.respond(1, '[]'); await settle();
    assert.equal(h.nodes['load-retry'].hidden, true);
    assert.match(h.nodes.status.textContent, /まだありません/);
    assert.equal(h.requests.length, 2);
  }
});

test('month log: HTTP failure -> retry only selected month, keeping ascending order', async () => {
  const h = await ready();
  h.nodes['month-select'].value = '2026-09'; h.nodes['month-select'].emit('change');
  h.respond(2, '', false); await settle();
  h.nodes['order-select'].value = 'asc'; h.nodes['order-select'].emit('change');
  h.retry(); h.retry();
  assert.equal(h.requests.length, 4);
  assert.equal(h.requests[3].url, 'logs/2026/2026-09.md');
  h.respond(3, log('September', '2026-09') + '## 2026-09-01\n### Coding\n#### First\n- URL: https://a.example/first');
  await settle();
  assert.equal(h.nodes['month-select'].value, '2026-09');
  assert.equal(h.get('sortOrder'), 'asc');
  const days = walk(h.nodes.content).filter(n => n.className === 'day');
  assert.match(days[0].textContent, /9月1日/);
  assert.equal(days[1].open, true); // 並び順にかかわらず最新日だけ展開
  assert.equal(h.nodes['load-retry'].hidden, true);
});

test('HTML response and parser exception are errors; blank/header-only logs are normal', async () => {
  for (const throwParser of [false, true]) {
    const h = harness(); h.respond(0, '["2026-10"]'); await settle();
    if (throwParser) h.get('parseLog = () => { throw new Error("invalid"); }');
    h.respond(1, throwParser ? log() : '<html>not a log</html>'); await settle();
    assert.match(h.nodes.status.textContent, /データ形式/);
    assert.equal(h.nodes['load-retry'].hidden, false);
  }
  for (const empty of ['', '# 2026年10月\n']) {
    const h = harness(); h.respond(0, '["2026-10"]'); await settle();
    h.respond(1, '<html>error</html>'); await settle();
    h.retry(); h.respond(2, empty); await settle();
    assert.match(h.nodes.status.textContent, /記事がありません/);
    assert.equal(h.nodes['load-retry'].hidden, true);
  }
});

test('search: retry same query once, keep controls, paginate 50 then 60, reuse cache', async () => {
  const h = await ready();
  h.nodes['order-select'].value = 'asc'; h.nodes['order-select'].emit('change');
  h.search('Alpha'); h.fail(2); await settle();
  h.retry(); h.retry();
  assert.equal(h.requests.length, 4);
  assert.equal(h.requests[3].url, 'data/search-index.json');
  h.respond(3, JSON.stringify(entries)); await settle();
  assert.equal(h.nodes['search-input'].value, 'Alpha');
  assert.equal(h.get('sortOrder'), 'asc');
  assert.equal(h.nodes['month-select'].disabled, true);
  const cards = () => walk(h.nodes.content).filter(n => n.className === 'card');
  assert.equal(cards().length, 50);
  const more = walk(h.nodes.content).find(n => n.className === 'more');
  more.emit('click'); assert.equal(cards().length, 60); assert.equal(more.hidden, true);
  h.nodes['search-clear'].emit('click');
  assert.equal(h.get('searchQuery'), ''); assert.equal(h.get('current.ym'), '2026-10');
  h.search('Alpha 1'); await settle();
  assert.equal(h.requests.length, 4); assert.equal(h.nodes['load-retry'].hidden, true);
});

test('invalid search data retries; valid empty array/zero matches do not show retry', async () => {
  for (const invalid of ['not JSON', '{}', '[{}]']) {
    const h = await ready(); h.search('Alpha'); h.respond(2, invalid); await settle();
    assert.match(h.nodes.status.textContent, /データ形式/);
    h.retry(); h.respond(3, '[]'); await settle();
    assert.match(h.nodes.content.textContent, /該当する記事はありません/);
    assert.equal(h.nodes['load-retry'].hidden, true);
  }
});

test('slow old month retry success/failure cannot overwrite newer month', async () => {
  for (const failOld of [false, true]) {
    const h = await ready();
    h.get('showMonth("2026-10")'); h.fail(2); await settle(); h.retry();
    h.nodes['month-select'].value = '2026-09'; h.nodes['month-select'].emit('change');
    h.respond(4, log('Newer', '2026-09')); await settle();
    if (failOld) h.fail(3); else h.respond(3, log('Stale'));
    await settle();
    assert.equal(h.get('current.ym'), '2026-09');
    assert.doesNotMatch(h.nodes.content.textContent, /Stale/);
    assert.equal(h.nodes.status.hidden, true); assert.equal(h.nodes['load-retry'].hidden, true);
  }
});

test('query changes share pending retry but render latest query; clearing ignores old responses', async () => {
  for (const [clear, failOld] of [[false, false], [true, false], [true, true]]) {
    const h = await ready(); h.search('Alpha'); h.fail(2); await settle(); h.retry();
    if (clear) h.nodes['search-clear'].emit('click'); else h.search('Beta');
    assert.equal(h.requests.length, 4);
    if (failOld) h.fail(3);
    else h.respond(3, JSON.stringify([...entries, { title: 'Beta only', url: 'https://a.example/beta' }]));
    await settle();
    assert.equal(h.nodes['load-retry'].hidden, true);
    if (clear) assert.match(h.nodes.content.textContent, /Daily/);
    else {
      assert.match(h.nodes.content.textContent, /「Beta」/);
      assert.doesNotMatch(h.nodes.content.textContent, /Alpha/);
    }
  }
});

test('late list response cannot override search; clear safely reloads missing months', async () => {
  const h = harness(); h.fail(0); await settle(); h.retry();
  h.search('Alpha'); h.respond(2, JSON.stringify(entries)); await settle();
  h.respond(1, '["2026-09"]'); await settle();
  assert.match(h.nodes.content.textContent, /検索結果/);
  assert.equal(h.nodes['month-select'].options.length, 0);
  h.nodes['search-clear'].emit('click');
  assert.equal(h.requests[3].url, 'data/months.json');
  h.respond(3, '["2026-10"]'); await settle(); h.respond(4, log()); await settle();
  assert.equal(h.get('current.ym'), '2026-10');
  // 古い月の成功応答も、最新の検索エラーと再試行操作を消してはいけない。
  const other = await ready();
  other.get('showMonth("2026-10")'); other.search('Alpha'); other.fail(3); await settle();
  other.respond(2, log('Old')); await settle();
  assert.match(other.nodes.status.textContent, /検索データ/);
  assert.equal(other.nodes['load-retry'].hidden, false);
  other.retry(); assert.equal(other.requests[4].url, 'data/search-index.json');
  other.respond(4, '[]'); await settle();
  assert.equal(other.nodes['load-retry'].hidden, true);
});
