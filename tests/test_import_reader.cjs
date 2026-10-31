const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const C = require('../import-catalog.js');
const M = require('../import-markdown.js');
const fixture = name => fs.readFileSync(`${__dirname}/fixtures/imports/${name}.md`, 'utf8');
const row = (path, type = 'file') => ({ name: path.split('/').pop(), path, type, download_url: 'https://evil.example/', html_url: 'javascript:alert(1)' });
const response = (body, status = 200) => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });

// Only text nodes and explicitly-created safe elements exist in this DOM model.
class Node {
  constructor(tag = '') { this.tag = tag; this.children = []; this.attributes = {}; this.text = ''; }
  set textContent(t) { this.text = t; this.children = []; }
  get textContent() { return this.text + this.children.map(n => n.textContent).join(''); }
  appendChild(n) { this.children.push(n); return n; }
  setAttribute(k, v) { this.attributes[k] = v; }
}
const doc = { createElement: tag => new Node(tag), createTextNode: text => { const n = new Node(); n.text = text; return n; }, createDocumentFragment: () => new Node() };
const walk = n => [n, ...n.children.flatMap(walk)];

test('calendar dates and ISO week years reject invalid names', () => {
  assert(C.validDate('2028-02-29')); assert(!C.validDate('2027-02-29')); assert(!C.validDate('2026-04-31'));
  assert(C.validWeek('2026-W53')); assert(!C.validWeek('2027-W53')); assert(!C.validWeek('2026-W00'));
  assert.equal(C.entry('x', '../2026-10-30'), null); assert.equal(C.entry('p', '2026-W44.md'), null);
});
test('only exact paths, files and matching years enter the catalogue', () => {
  const rows = [row('imports/x/2027/x-20270102.md'), row('imports/x/2027/x-20270101.md'), row('imports/x/2027/x-20270230.md'), row('imports/x/2026/x-20261030.md'), row('imports/x/2027/x-20270103.md', 'symlink'), row('../x-20270104.md')];
  assert.deepEqual(C.entries('x', rows, '2027').map(e => e.id), ['2027-01-02', '2027-01-01']);
  assert.equal(C.entries('p', [row('imports/p/2026-W44.md')])[0].original, C.REPO + 'blob/main/imports/p/2026-W44.md');
  assert.throws(() => C.entries('p', {})); assert.throws(() => C.entries('p', Array(1000).fill(null)));
});
test('routes retain official filters and isolate sample, invalid source and entry', () => {
  const url = 'https://site.example/ai-watch/?q=Codex&category=AI&month=2026-10#article-a';
  const next = C.routeURL(url, 'p', '2026-W44');
  assert.equal(C.route('https://site.example' + next).id, '2026-W44'); assert(next.includes('q=Codex'));
  assert.equal(C.routeURL('https://site.example' + next, 'official'), '/ai-watch/?q=Codex&category=AI&month=2026-10#article-a');
  assert.equal(C.route(url + '&source=evil').source, 'official');
  assert.equal(C.route('https://site.example/?sample&source=p&entry=2026-W44').source, 'official');
  assert(!C.routeURL('https://site.example/?sample', 'p', '2026-W44').includes('source'));
});
test('discovery spans new years, caches and refreshes without trusting remote URLs', async () => {
  const calls = []; let added = false;
  const client = C.create(async (url, options) => {
    calls.push([url, options]);
    if (url.endsWith('/x?ref=main')) return response([row('imports/x/2027', 'dir'), row('imports/x/2026', 'dir'), row('evil', 'dir')]);
    if (url.endsWith('/2027?ref=main')) return response([row('imports/x/2027/x-20270101.md'), ...(added ? [row('imports/x/2027/x-20270102.md')] : [])]);
    if (url.endsWith('/2026?ref=main')) return response([row('imports/x/2026/x-20261030.md')]);
    assert.equal(url, 'imports/x/2027/x-20270102.md'); return response(fixture('grok'));
  });
  assert.equal((await client.discover('x'))[0].id, '2027-01-01');
  await client.discover('x'); assert.equal(calls.length, 3);
  added = true; const files = await client.discover('x', true); assert.equal(files[0].id, '2027-01-02');
  assert.match(await client.body(files[0]), /収集日時/);
  assert(calls.every(([, o]) => o.credentials === 'omit' && o.redirect === 'error' && !o.headers?.Authorization));
  await assert.rejects(client.body({ id: '2027-01-02', path: 'https://evil.example/' }));
});
test('API errors and malformed/partial catalogues are not empty successes; retries work', async () => {
  let failures = true;
  const client = C.create(async () => failures ? response('', 429) : response([]));
  await assert.rejects(client.discover('p'), /制限/); failures = false;
  assert.deepEqual(await client.discover('p'), []);
  const invalid = C.create(async () => response({ message: 'bad' }));
  await assert.rejects(invalid.discover('p'), /形式/);
  const partial = C.create(async url => url.endsWith('/x?ref=main') ? response([row('imports/x/2027', 'dir')]) : response('', 500));
  await assert.rejects(partial.discover('x'), /一覧/);
});
test('Pages 404 and oversized responses retry without negative caching', async () => {
  let missing = true;
  const client = C.create(async () => missing ? response('', 404) : response('delivered'));
  const file = C.entry('p', '2026-W44');
  await assert.rejects(client.body(file), /まだPages/); missing = false;
  assert.equal(await client.body(file), 'delivered');
  await assert.rejects(C.readResponse(response('long'), 3), /上限/);
});
test('Grok parses provenance, observation window and all candidate fields separately', () => {
  const parsed = M.grok(fixture('grok'));
  assert.match(parsed.title, /2027-01-02/); assert.match(parsed.meta['収集日時'], /00:17/);
  assert.match(parsed.meta['対象期間'], /2027-01-01/); assert.equal(parsed.items.length, 2);
  assert.equal(parsed.items[0].fields['情報の確度'], '公式発表');
  assert.equal(parsed.items[0].fields['投稿者'], '@example');
});
test('Markdown renders report structure, Japanese, tables and strong text safely', () => {
  const rendered = M.render(doc, fixture('perplexity')); const nodes = walk(rendered);
  for (const tag of ['h3', 'h4', 'h5', 'table', 'th', 'td', 'ul', 'ol', 'strong', 'em', 'pre', 'code']) assert(nodes.some(n => n.tag === tag), tag);
  assert.match(rendered.textContent, /調査日: 2026-10-31/); assert.match(rendered.textContent, /🧪/);
  assert(!nodes.some(n => ['script', 'img', 'iframe', 'style'].includes(n.tag)));
  assert(nodes.filter(n => n.tag === 'a').every(n => /^https?:/.test(n.href) && n.rel === 'noopener noreferrer'));
  assert.deepEqual(M.cells('| `a|b` | a\\|b |'), ['`a|b`', 'a|b']);
});
test('dangerous schemes, credentials, control characters and images never create executable DOM', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,x', '//evil.example', 'https://user:pass@example.com', 'https://example.com/\n']) assert.equal(M.safeLink(value), '');
  const n = doc.createElement('p'); M.inline(doc, n, '[bad](javascript:alert(1)) ![pixel](https://evil.example/a) <svg onload=alert(1)>');
  assert(!walk(n).some(x => x.tag === 'a' || x.tag === 'img' || x.tag === 'svg'));
  const valid = doc.createElement('p'); M.inline(doc, valid, '[parentheses](https://example.com/foo(bar))');
  assert.equal(valid.children.find(n => n.tag === 'a').href, 'https://example.com/foo(bar)');
});
test('malformed Markdown remains readable and headings cannot skip levels', () => {
  const rendered = M.render(doc, '###### jump\n\n[broken](\n\n| incomplete | table\n\n```\n<script>x</script>');
  assert.equal(rendered.children[0].tag, 'h3'); assert.match(rendered.textContent, /broken/);
  assert.match(rendered.textContent, /<script>x<\/script>/);
});
