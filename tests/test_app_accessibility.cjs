const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { harness, ready, settle, log, entries, walk } = require('./app_harness.cjs');
const headings = node => walk(node).filter(n => /^h[1-6]$/.test(n.tag));
const moreButton = h => walk(h.nodes.content).find(n => n.className === 'more');

test('daily heading hierarchy and shared new-tab description survive sample mode', async () => {
  for (const search of ['', '?sample']) {
    const h = await ready(search);
    assert.deepEqual(headings(h.nodes.content).map(n => n.tag), ['h2', 'h3', 'h4', 'h5']);
    const day = walk(h.nodes.content).find(n => n.tag === 'summary');
    assert.equal(day.firstChild.tag, 'h3');
    assert.match(day.textContent, /10月2日/);
    for (const a of walk(h.nodes.content).filter(n => n.tag === 'a' && n.className !== 'share')) {
      assert.equal(a.target, '_blank');
      assert.equal(a.rel, 'noopener noreferrer');
      assert.equal(a.getAttribute('aria-describedby'), 'new-tab-hint');
    }
    const releaseCard = h.get('renderCard({title:"Group",url:"https://a.example/group",releases:[{label:"v1",url:"https://a.example/v1"}]}, true)');
    const links = walk(releaseCard).filter(n => n.tag === 'a' && n.className !== 'share');
    assert.equal(links.length, 3);
    assert.ok(links.every(a => a.getAttribute('aria-describedby') === 'new-tab-hint'));
    if (search) assert.ok(h.requests.every(r => r.url.startsWith('samples/')));
    assert.equal(h.document.activeElement, h.document.body); // 初期表示はフォーカスを奪わない
  }
});

test('skip link is first, target focusable; app has one atomic completion region separate from collection', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.match(html, /<body>\s*<a class="skip-link" href="#main-content">本文へ移動<\/a>/);
  assert.match(html, /<main id="main-content"[^>]*tabindex="-1"/);
  assert.match(html, /id="new-tab-hint"[^>]*>.*新しいタブ/);
  assert.match(html, /id="view-announcement"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/);
  assert.doesNotMatch(html, /id="status"[^>]*(role="status"|aria-live)/);
  assert.equal((html.match(/role="status"/g) || []).length, 3); // F04・公式記事操作・別ソース操作。非表示の経路は通知しない
  assert.match(html, /id="import-status"[^>]*role="status"/);
  assert.match(html, /id="import-view"[^>]*hidden/);
});

test('search announces final total including zero and uses h2 -> h3 without stealing typing focus', async () => {
  const h = await ready();
  h.nodes['search-input'].focus();
  h.search('Alpha'); h.respond(2, JSON.stringify(entries)); await settle();
  assert.equal(headings(h.nodes.content)[0].tag, 'h2');
  assert.ok(headings(h.nodes.content).slice(1).every(n => n.tag === 'h3'));
  assert.match(h.nodes['view-announcement'].textContent, /120件。50件/);
  assert.equal(h.document.activeElement, h.nodes['search-input']);
  const before = h.announcements.length;
  h.input('  Alpha  '); h.flushTimers(); await settle();
  assert.equal(h.announcements.length, before); // 正規化して同じ語なら再通知しない
  h.search('no-match'); await settle();
  assert.match(h.nodes['view-announcement'].textContent, /0件/);
  assert.match(h.nodes.content.textContent, /該当する記事はありません/);
});

test('pending old search cannot render or announce within debounce; latest query shares fetch', async () => {
  for (const fails of [false, true]) {
    const h = await ready();
    h.search('Alpha'); h.input('Beta');
    const changed = h.announcements.length;
    if (fails) h.fail(2);
    else h.respond(2, JSON.stringify([...entries, {title: 'Beta result', url: 'https://a.example/b'}]));
    await settle();
    assert.equal(h.announcements.length, changed);
    assert.doesNotMatch(h.nodes.content.textContent, /Alpha|取得できません/);
    h.flushTimers();
    if (fails) h.respond(3, JSON.stringify([{title: 'Beta result', url: 'https://a.example/b'}]));
    await settle();
    assert.match(h.nodes['view-announcement'].textContent, /「Beta」の検索結果: 1件/);
    assert.equal(h.nodes['load-retry'].hidden, true);
  }
});

test('IME cancels pre-composition timer and old response, waits for confirmed input', async () => {
  const h = await ready();
  h.input('Al');
  h.nodes['search-input'].emit('compositionstart');
  h.input('変換中', {isComposing: true});
  h.flushTimers(); h.nodes['search-input'].emit('keydown', {key: 'Enter', isComposing: true});
  assert.equal(h.requests.length, 2);
  h.nodes['search-input'].value = 'Alpha'; h.nodes['search-input'].emit('compositionend');
  h.flushTimers();
  h.nodes['search-input'].emit('compositionstart');
  const before = h.announcements.length;
  h.respond(2, JSON.stringify(entries)); await settle();
  assert.equal(h.announcements.length, before);
  h.nodes['search-input'].emit('compositionend'); h.flushTimers(); await settle();
  assert.match(h.nodes['view-announcement'].textContent, /Alpha.*120件/);
  assert.equal(h.requests.length, 3); // 同じ確定語でも抑止した結果をキャッシュから復帰
});

test('returning to original query resumes a result suppressed during debounce', async () => {
  const h = await ready(); h.search('Alpha'); h.input('Beta');
  h.respond(2, JSON.stringify(entries)); await settle();
  h.input('Alpha'); h.flushTimers(); await settle();
  assert.match(h.nodes['view-announcement'].textContent, /Alpha.*120件/);
  assert.equal(h.requests.length, 3);
});

test('more keeps focus on intermediate page; final page focuses first newly added article before hiding', async () => {
  const h = await ready(); h.search('Alpha'); h.respond(2, JSON.stringify(entries)); await settle();
  const more = moreButton(h); more.focus(); more.emit('click');
  assert.equal(h.document.activeElement, more);
  assert.equal(more.hidden, false);
  assert.match(h.nodes['view-announcement'].textContent, /120件中100件/);
  more.emit('click');
  assert.equal(more.hidden, true);
  assert.equal(h.document.activeElement.tag, 'h3');
  assert.match(h.document.activeElement.textContent, /Alpha 100/);
  assert.equal(h.document.activeElement.tabIndex, -1);
  assert.match(h.nodes['view-announcement'].textContent, /120件中120件/);
  more.emit('click'); // 最終操作の連打は何も変更しない
  assert.match(h.document.activeElement.textContent, /Alpha 100/);
  const other = await ready(); other.search('Alpha'); other.respond(2, JSON.stringify(entries)); await settle();
  const oldMore = moreButton(other);
  other.input('Beta');
  const before = other.announcements.length;
  oldMore.emit('click');
  assert.equal(other.announcements.length, before); // debounce待ちでも旧結果の追加通知をしない
  assert.equal(walk(other.nodes.content).filter(n => n.className === 'card').length, 50);
});

test('retry keeps button focused through failure and nested months -> daily success, ignoring repeated clicks', async () => {
  const h = harness(); h.fail(0); await settle();
  const retry = h.nodes['load-retry']; retry.focus(); h.retry(); h.retry();
  assert.equal(h.requests.length, 2);
  assert.equal(retry.hidden, false);
  assert.equal(retry.getAttribute('aria-disabled'), 'true');
  h.fail(1); await settle();
  assert.equal(h.document.activeElement, retry);
  assert.equal(retry.getAttribute('aria-disabled'), 'false');
  assert.match(h.nodes['view-announcement'].textContent, /取得できません/);
  h.retry(); h.respond(2, '["2026-10"]'); await settle();
  assert.equal(retry.hidden, false);
  h.respond(3, log()); await settle();
  assert.equal(retry.hidden, true);
  assert.equal(h.document.activeElement.id, 'view-heading');
  assert.match(h.document.activeElement.textContent, /2026年10月/);
});

test('search and month retry focus result heading; empty retry focuses message, no missing target', async () => {
  for (const mode of ['search', 'month', 'empty']) {
    const h = await ready();
    if (mode === 'search') h.search('Alpha');
    else { h.nodes['month-select'].value = '2026-09'; h.nodes['month-select'].emit('change'); }
    h.fail(2); await settle();
    h.nodes['load-retry'].focus(); h.retry();
    h.respond(3, mode === 'search' ? '[]' : mode === 'empty' ? '' : log('Other', '2026-09'));
    await settle();
    assert.equal(h.nodes['load-retry'].hidden, true);
    assert.equal(h.document.activeElement, mode === 'empty' ? h.nodes.status : h.document.getElementById('view-heading'));
    assert.ok(!h.document.activeElement.hidden);
  }
});

test('retry never steals focus when user leaves button; late retry cannot move focus or announce over new search', async () => {
  for (const newQuery of [false, true]) {
    const h = await ready();
    h.nodes['month-select'].value = '2026-09'; h.nodes['month-select'].emit('change');
    h.fail(2); await settle(); h.nodes['load-retry'].focus(); h.retry();
    h.nodes['search-input'].focus();
    if (newQuery) h.search('Alpha');
    h.respond(3, log('Retry', '2026-09')); await settle();
    assert.equal(h.document.activeElement, h.nodes['search-input']);
    if (newQuery) {
      assert.doesNotMatch(h.nodes.content.textContent, /Retry/);
      h.respond(4, JSON.stringify(entries)); await settle();
      assert.match(h.nodes['view-announcement'].textContent, /Alpha.*120件/);
    }
  }
});

test('clear restores daily announcement and input focus; month/sort changes keep their own focus', async () => {
  const h = await ready(); h.search('Alpha'); h.respond(2, JSON.stringify(entries)); await settle();
  h.nodes['search-clear'].focus(); h.nodes['search-clear'].emit('click');
  assert.equal(h.document.activeElement, h.nodes['search-input']);
  assert.equal(h.nodes['search-clear'].disabled, true);
  assert.match(h.nodes['view-announcement'].textContent, /日刊: 2026年10月、1件/);
  const order = h.nodes['order-select']; order.focus(); order.value = 'asc'; order.emit('change');
  assert.equal(h.document.activeElement, order);
  assert.match(h.nodes['view-announcement'].textContent, /古い順/);
  const select = h.nodes['month-select']; select.focus(); select.value = '2026-09'; select.emit('change');
  h.respond(3, log('September', '2026-09')); await settle();
  assert.equal(h.document.activeElement, select);
  assert.match(h.nodes['view-announcement'].textContent, /日刊: 2026年9月/);
  h.input('   '); h.nodes['search-clear'].emit('click');
  assert.equal(h.nodes['search-clear'].disabled, true);
});

test('stale monthly success and failure cannot override current result announcement', async () => {
  for (const fails of [false, true]) {
    const h = await ready(); h.nodes['month-select'].value = '2026-09'; h.nodes['month-select'].emit('change');
    h.search('Alpha'); h.respond(3, JSON.stringify(entries)); await settle();
    const before = h.announcements.length;
    if (fails) h.fail(2); else h.respond(2, log('Old', '2026-09'));
    await settle();
    assert.equal(h.announcements.length, before);
    assert.match(h.nodes['view-announcement'].textContent, /Alpha.*120件/);
  }
});
