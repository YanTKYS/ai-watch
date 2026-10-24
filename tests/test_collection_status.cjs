const { test } = require('node:test');
const assert = require('node:assert/strict');
const health = require('../collection-status.js');

const T = '2026-10-24T09:00:00+09:00';
const OLD = '2026-10-23T09:00:00+09:00';
const NOW = Date.parse(T);
function state(result = 'success', n = 0) {
  const statuses = result === 'partial' ? ['success', 'failed'] : result === 'failed' ? ['failed', 'failed'] : ['success', 'success'];
  return { schema_version: 1, collection: { attempted_at: T, completed_at: T, last_all_success_at: result === 'success' ? T : OLD,
    result, new_articles: n, feeds: statuses.map((s, i) => ({ name: `Feed ${i}`, status: s,
      candidates: s === 'success' ? n : null, adopted: s === 'success' ? n : null })) },
    index: { checked_at: T, result: 'success', last_success_at: T, for_collection: T } };
}

test('successful collection distinguishes new articles from normal zero', () => {
  assert.match(health.summarize(state(), NOW).summary, /正常・新着なし/);
  assert.match(health.summarize(state('success', 2), NOW).summary, /新着2件/);
  assert.match(health.summarize(state(), NOW).detail, /2026\/10\/24 9:00 JST/);
});
test('partial and total failure are not normal zero', () => {
  const partial = health.summarize(state('partial'), NOW);
  assert.match(partial.summary, /一部取得失敗/);
  assert.doesNotMatch(partial.summary, /新着なし/);
  assert.match(partial.feeds[1], /取得失敗/);
  assert.match(health.summarize(state('failed'), NOW).summary, /取得失敗/);
});
test('stale status changes at viewer time and threshold is configurable', () => {
  assert.match(health.summarize(state(), NOW + 35 * 3600000).summary, /正常/);
  const stale = health.summarize(state(), NOW + 37 * 3600000);
  assert.match(stale.summary, /更新遅延/);
  assert.match(stale.detail, /前回の結果: 正常/);
  assert.match(stale.detail, /配信失敗/);
  assert.match(health.summarize(state(), NOW + 13 * 3600000, 12).summary, /更新遅延/);
});
test('index failure and old generation are independent of collection success', () => {
  const data = state();
  data.index = { checked_at: T, result: 'failed', last_success_at: OLD, for_collection: T };
  let view = health.summarize(data, NOW);
  assert.match(view.summary, /正常/);
  assert.match(view.index, /生成失敗/);
  assert.match(view.index, /2026\/10\/23/);
  data.index.for_collection = OLD;
  view = health.summarize(data, NOW);
  assert.match(view.index, /今回の生成は未確認/);
  data.index = null;
  assert.match(health.summarize(data, NOW).index, /状態不明/);
});
test('running, absent, broken, contradictory and future timestamps are unknown', () => {
  for (const data of [null, {}, [], {schema_version: 1, collection: null, index: null}]) {
    assert.match(health.summarize(data, NOW).summary, /状態不明/);
  }
  const running = state(); running.collection.result = 'running'; running.collection.new_articles = null;
  assert.match(health.summarize(running, NOW).summary, /未完了/);
  for (const mutate of [d => d.collection.feeds.push(null), d => d.collection.new_articles = -1,
                       d => d.collection.result = 'partial', d => d.collection.attempted_at = '2026-10-24T09:00:00',
                       d => d.collection.attempted_at = '2099-01-01T00:00:00Z',
                       d => d.collection.last_all_success_at = '2099-01-01T00:00:00Z']) {
    const data = state(); mutate(data);
    assert.match(health.summarize(data, NOW).summary, /状態不明/);
  }
});

class Node {
  constructor() { this.text = ''; this.childNodes = []; this.hidden = false; }
  get textContent() { return this.text + this.childNodes.map(n => n.textContent).join(''); }
  set textContent(s) { this.text = s; this.childNodes = []; }
  replaceChildren(...nodes) { this.text = ''; this.childNodes = nodes; }
}
function documentMock() {
  const nodes = {};
  return { nodes, getElementById: id => nodes[id] ??= new Node(), createElement: () => new Node() };
}
test('status loading and safe rendering never alter article errors or retry controls', async () => {
  const doc = documentMock();
  doc.getElementById('status').textContent = 'article error';
  doc.getElementById('load-retry').hidden = false;
  const data = state('partial'); data.collection.feeds[0].name = '<img src=x onerror=bad>';
  const calls = [];
  let resolve;
  const pending = health.start(doc, url => { calls.push(url); return new Promise(r => resolve = r); }, {search: ''}, () => NOW);
  assert.match(doc.getElementById('collection-summary').textContent, /状態不明/);
  assert.equal(doc.getElementById('status').textContent, 'article error');
  resolve({ok: true, json: async () => data}); await pending;
  assert.match(doc.getElementById('collection-feeds').textContent, /<img src=x onerror=bad>/);
  assert.equal(doc.getElementById('collection-feeds').childNodes[0].childNodes.length, 0);
  assert.equal(doc.getElementById('status').textContent, 'article error');
  assert.equal(doc.getElementById('load-retry').hidden, false);
  assert.deepEqual(calls, ['data/collection-status.json']);
});
test('404, invalid JSON and rejected fetch retain unknown status without throwing', async () => {
  for (const fetch of [async () => ({ok: false}), async () => ({ok: true, json: async () => { throw new Error('bad'); }}),
                       async () => { throw new Error('offline'); }]) {
    const doc = documentMock();
    await health.start(doc, fetch, {search: ''}, () => NOW);
    assert.match(doc.getElementById('collection-summary').textContent, /状態不明/);
    assert.equal(doc.getElementById('collection-feed-details').hidden, true);
  }
});
test('sample mode hides health panel and does not request production status', async () => {
  const doc = documentMock();
  await health.start(doc, () => { throw new Error('must not fetch'); }, {search: '?sample'}, () => NOW);
  assert.equal(doc.getElementById('collection-health').hidden, true);
});
test('cached display ages without a network polling loop', async () => {
  const doc = documentMock(); let now = NOW, calls = 0;
  const render = await health.start(doc, async () => { calls++; return {ok: true, json: async () => state()}; }, {search: ''}, () => now);
  assert.match(doc.getElementById('collection-summary').textContent, /正常/);
  now += 37 * 3600000; render();
  assert.match(doc.getElementById('collection-summary').textContent, /更新遅延/);
  assert.equal(calls, 1);
});
