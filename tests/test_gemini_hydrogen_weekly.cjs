'use strict';
// Offline mocks only: no Secret, no real network. Synthetic articles; the real W45 input is verified by the workflow dry run.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const P = require('../scripts/gemini_hydrogen_weekly.cjs');
const KEY = 'AIzaSyTEST-gemini-secret-NEVER-SAVE-0123';
const ENV = { GITHUB_EVENT_NAME: 'workflow_dispatch', GITHUB_REF: 'refs/heads/main', GITHUB_REPOSITORY: 'YanTKYS/ai-watch',
  GITHUB_RUN_ATTEMPT: '1', EXECUTE: 'true', SPEC_CONFIRMED: 'true',
  GITHUB_WORKFLOW_REF: 'YanTKYS/ai-watch/.github/workflows/gemini-hydrogen-weekly-poc.yml@refs/heads/main' };

// Synthetic daily log + derived index for the fixed week (+ one out-of-week article that must be ignored).
const ARTICLES = Array.from({ length: 6 }, (_, i) => ({ title: `（合成）機能${i}の公開`, url: `https://openai.com/index/synthetic-${i}`,
  feed: 'OpenAI News', source: 'openai.com', category: i % 2 ? 'AIモデル' : 'AIコーディング',
  published: `2026-11-0${i + 2}`, retrieved: `2026-11-0${i + 2}`,
  ...(i === 1 ? { notes: '新機能 2 / 修正 1', highlights: ['新機能（v1）: 合成の変更点'] } : {}) }));
const OUTSIDE = { title: '（合成）範囲外', url: 'https://openai.com/index/outside', feed: 'OpenAI News', source: 'openai.com',
  category: 'AIモデル', published: '2026-11-09', retrieved: '2026-11-09' };
function logText(list) {
  let text = '# 2026年11月\n';
  for (const a of list) {
    text += `\n## ${a.retrieved}\n\n### ${a.category}\n\n#### ${a.title}\n\n- URL: ${a.url}\n- Source: ${a.source}\n- Feed: ${a.feed}\n`;
    if (a.notes) text += `- Notes: ${a.notes}\n`;
    for (const h of a.highlights || []) text += `- Highlight: ${h}\n`;
    text += `- Published: ${a.published}\n- Retrieved: ${a.retrieved}\n`;
  }
  return text;
}
const files = (list = [...ARTICLES, OUTSIDE], extra = {}) => {
  const logBytes = Buffer.from(logText(list)), indexBytes = Buffer.from(JSON.stringify(list.map(({ highlights, notes, ...a }) => a)));
  const s = P.selectInput({ logBytes, indexBytes });
  const manifest = { week: P.WEEK.id, selection_sha256: s.snapshot.selection_sha256, articles: s.snapshot.articles };
  return { logBytes, indexBytes, manifestBytes: Buffer.from(JSON.stringify(manifest)), ...extra };
};
const FILES = files(), SELECTED = P.selectInput({ logBytes: FILES.logBytes, indexBytes: FILES.indexBytes }).articles;
const text = n => 'あ'.repeat(n).replace(/あ/g, (_, i) => '日本語の説明文です。'[i % 9]);
function candidateReport(input = SELECTED, patch = {}) {
  const first = input[0].id, second = input[1].id;
  return { overview: text(150), topics: [0, 1, 2].map(i => ({ title: `トピック${i + 1}の更新`, what_changed: text(120), impact: text(90),
    evidence: text(80), article_ids: [i === 1 ? second : first], limitation: i === 1 ? '抜粋のみで本文は未取得です。' : 'タイトルのみが根拠で、本文は未取得です。' })),
  practical_notes: [{ note: text(100), article_ids: [first, second] }], ...patch };
}
const envelope = (content = candidateReport(), over = {}) => ({ modelVersion: P.MODEL, responseId: 'resp-synthetic',
  candidates: [{ finishReason: 'STOP', content: { role: 'model', parts: [{ text: JSON.stringify(content) }] } }],
  usageMetadata: { promptTokenCount: 4000, candidatesTokenCount: 1500, thoughtsTokenCount: 6000, totalTokenCount: 11500, private: 'NOT SAVED' },
  ...over });
const ok = data => new Response(typeof data === 'string' ? data : JSON.stringify(data), { status: 200 });
async function live(data = envelope(), options = {}) {
  const calls = [];
  const report = await P.runPoc({ files: FILES, live: true, apiKey: KEY, env: ENV,
    fetchImpl: async (...args) => { calls.push(args); return typeof data === 'function' ? data() : ok(data); }, ...options });
  return { report, calls };
}
const realFetch = globalThis.fetch;
before(() => { globalThis.fetch = () => { throw Error('REAL NETWORK FORBIDDEN'); }; });
after(() => { globalThis.fetch = realFetch; });

test('input is the fixed week from the daily log, ordered, evidence-labelled and cross-checked with the index', () => {
  const s = P.selectInput({ logBytes: FILES.logBytes, indexBytes: FILES.indexBytes });
  assert.deepEqual(s.articles.map(a => a.id), ['a01', 'a02', 'a03', 'a04', 'a05', 'a06']);
  assert.ok(s.articles.every(a => a.retrieved >= P.WEEK.from && a.retrieved <= P.WEEK.to));
  assert.equal(s.articles[1].evidence_level, 'notes_highlights'); assert.equal(s.articles[0].evidence_level, 'title_metadata');
  assert.equal(s.articles[0].published, '2026-11-02'); assert.equal(s.articles[0].retrieved, '2026-11-02');
  assert.equal(s.snapshot.article_count, 6); assert.equal(s.snapshot.index_article_count, 6);
  assert.match(s.snapshot.selection_sha256, /^[a-f0-9]{64}$/); assert.match(s.snapshot.log_sha256, /^[a-f0-9]{64}$/);
  assert.ok(!JSON.stringify(s.articles).includes('https://')); // URLs stay local; references are attached from records
});
test('duplicate URLs are skipped once; index mismatch, unsupported feeds and over-budget fields stop instead of truncating', () => {
  const dup = [...ARTICLES, { ...ARTICLES[0], title: '重複', url: ARTICLES[0].url + '#x' }];
  const logBytes = Buffer.from(logText(dup));
  assert.equal(P.selectInput({ logBytes, indexBytes: FILES.indexBytes }).snapshot.duplicate_urls_skipped, 1);
  const stopCode = fn => assert.throws(fn, e => Boolean(e.code));
  assert.throws(() => P.selectInput({ logBytes: FILES.logBytes, indexBytes: Buffer.from(JSON.stringify(ARTICLES.slice(1))) }), { code: 'index_mismatch' });
  assert.throws(() => P.selectInput({ logBytes: Buffer.from(logText([{ ...ARTICLES[0], feed: 'Unknown Feed' }])), indexBytes: FILES.indexBytes }), { code: 'unsupported_article' });
  assert.throws(() => P.selectInput({ logBytes: Buffer.from(logText([{ ...ARTICLES[0], url: 'https://evil.example/x' }])), indexBytes: FILES.indexBytes }), { code: 'unsupported_article' });
  assert.throws(() => P.selectInput({ logBytes: Buffer.from(logText([{ ...ARTICLES[0], title: 'あ'.repeat(P.LIMITS.title + 1) }])), indexBytes: FILES.indexBytes }), { code: 'input_budget_exceeded' });
  assert.throws(() => P.selectInput({ logBytes: Buffer.from(logText([OUTSIDE])), indexBytes: FILES.indexBytes }), { code: 'no_eligible_articles' });
  stopCode(() => P.selectInput({ logBytes: Buffer.from([0xff, 0xfe]), indexBytes: FILES.indexBytes }));
});
test('a changed input no longer matches the pinned manifest and stops before any request', async () => {
  const changed = files([{ ...ARTICLES[0], title: '（合成）別の題名' }, ...ARTICLES.slice(1)]);
  const calls = [];
  const report = await P.runPoc({ files: { ...changed, manifestBytes: FILES.manifestBytes }, live: true, apiKey: KEY, env: ENV,
    fetchImpl: async (...a) => { calls.push(a); return ok(envelope()); } });
  assert.equal(report.reason, 'input_changed'); assert.equal(report.requests_sent, 0); assert.equal(calls.length, 0);
});
test('dry run needs no key or network, shows the exact request and sends nothing', async () => {
  const report = await P.runPoc({ files: FILES });
  assert.equal(report.status, 'plan_only'); assert.equal(report.requests_sent, 0); assert.equal(report.output, null);
  assert.equal(report.snapshot.pinned_manifest, 'matched'); assert.equal(report.request.generationConfig.thinkingConfig.thinkingLevel, 'HIGH');
});
test('only reviewed main dispatch with execute + spec confirmation on the first attempt can send; a missing key sends nothing', async () => {
  for (const patch of [{ GITHUB_REF: 'refs/heads/feature' }, { GITHUB_EVENT_NAME: 'push' }, { GITHUB_RUN_ATTEMPT: '2' },
    { GITHUB_REPOSITORY: 'YanTKYS/news-watch' }, { EXECUTE: 'false' }, { SPEC_CONFIRMED: 'false' }, { SPEC_CONFIRMED: undefined },
    { GITHUB_WORKFLOW_REF: 'YanTKYS/ai-watch/.github/workflows/gemini-hydrogen-weekly-poc.yml@refs/pull/1/merge' }]) {
    const { report, calls } = await live(envelope(), { env: { ...ENV, ...patch } });
    assert.equal(report.reason, 'live_not_authorized', JSON.stringify(patch)); assert.equal(calls.length, 0); assert.equal(report.requests_sent, 0);
  }
  for (const apiKey of ['', 'has space', 'x'.repeat(513), undefined]) {
    const { report, calls } = await live(envelope(), { apiKey }); assert.equal(report.reason, 'missing_or_invalid_key'); assert.equal(calls.length, 0);
  }
  assert.equal((await live(envelope(), { timeoutMs: P.LIMITS.timeoutMs + 1 })).report.reason, 'invalid_timeout');
});
test('exactly one POST: fixed model, thinkingLevel without thinkingBudget, JSON schema, no tools or grounding', async () => {
  const { report, calls } = await live();
  assert.equal(calls.length, 1); assert.equal(report.requests_sent, 1);
  const [url, init] = calls[0], body = JSON.parse(init.body);
  assert.equal(url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent');
  assert.equal(init.method, 'POST'); assert.equal(init.redirect, 'error'); assert.equal(init.credentials, 'omit');
  assert.equal(init.headers['x-goog-api-key'], KEY); assert.ok(!url.includes(KEY) && !init.body.includes(KEY));
  assert.deepEqual(Object.keys(body).sort(), ['contents', 'generationConfig', 'systemInstruction']);
  const g = body.generationConfig;
  assert.deepEqual(g.thinkingConfig, { thinkingLevel: 'HIGH' }); assert.ok(!('thinkingBudget' in g.thinkingConfig));
  assert.equal(g.responseMimeType, 'application/json'); assert.equal(g.maxOutputTokens, P.LIMITS.maxOutputTokens);
  assert.deepEqual(g.responseJsonSchema, P.SCHEMA);
  assert.ok(!/tools|googleSearch|urlContext|google_search/i.test(init.body));
  const prompt = body.contents[0].parts[0].text;
  assert.ok(prompt.includes('<UNTRUSTED_NEWS_JSON>'));
  for (const a of SELECTED) assert.ok(prompt.includes(a.id) && prompt.includes(a.title));
  assert.equal(report.status, 'schema_valid_unverified'); assert.equal(report.validation.facts_and_value, 'human_review_required');
});
test('a valid candidate keeps full text and attaches URLs only from verified local records; reasoning parts are dropped', async () => {
  const data = envelope(); data.candidates[0].content.parts = [{ thought: true, text: 'PRIVATE REASONING NOT SAVED' },
    { text: data.candidates[0].content.parts[0].text, thoughtSignature: 'opaque' }];
  const { report } = await live(data);
  assert.equal(report.status, 'schema_valid_unverified'); assert.equal(report.output.topics.length, 3);
  assert.equal(report.output.topics[0].references[0].url, ARTICLES[0].url); assert.equal(report.output.topics[0].references[0].evidence_level, 'title_metadata');
  assert.equal(report.output.topics[1].references[0].evidence_level, 'notes_highlights');
  assert.equal(report.response_model, P.MODEL); assert.equal(report.usage.thoughtsTokenCount, 6000);
  const json = JSON.stringify(report); assert.ok(!json.includes('PRIVATE REASONING') && !json.includes('opaque') && !json.includes('private') && !json.includes(KEY));
  const md = P.renderMarkdown(report);
  assert.ok(md.includes('候補レポート（未検証）') && md.includes(report.output.overview) && md.includes(ARTICLES[0].url));
  assert.ok(md.includes('news-watch側の実測') && !md.includes(KEY));
});
test('structure failures are strict: unknown IDs, extra keys, bad counts, missing title-only limitation, URLs and markup', async () => {
  const bad = patch => async () => { const { report } = await live(envelope(candidateReport(SELECTED, patch))); return report; };
  const topics = candidateReport().topics;
  const cases = [
    [{ topics: topics.slice(0, 2) }, 'invalid_output_schema'], [{ topics: [...topics, ...topics, ...topics].slice(0, 7) }, 'invalid_output_schema'],
    [{ topics: [{ ...topics[0], article_ids: ['a99'] }, topics[1], topics[2]] }, 'invalid_output_schema'],
    [{ topics: [{ ...topics[0], article_ids: ['a01', 'a01'] }, topics[1], topics[2]] }, 'invalid_output_schema'],
    [{ topics: [{ ...topics[0], extra: 'x' }, topics[1], topics[2]] }, 'invalid_output_schema'],
    [{ topics: [{ ...topics[0], limitation: '本文は未取得です。' }, topics[1], topics[2]] }, 'invalid_output_schema'],
    [{ topics: [topics[0], { ...topics[1], title: topics[0].title }, topics[2]] }, 'invalid_output_schema'],
    [{ overview: text(150) + ' https://example.com/x' }, 'unsafe_output'], [{ overview: text(150) + ' <b>強調</b>' }, 'unsafe_output'],
    [{ overview: text(150) + ' **強調**' }, 'unsafe_output'], [{ overview: text(150) + ' [link](x)' }, 'unsafe_output'],
    [{ overview: 'English only report without Japanese '.repeat(5) }, 'unsafe_output'], [{ overview: text(150) + ' ' + KEY }, 'unsafe_output'],
    [{ overview: text(20) }, 'unsafe_output'], [{ practical_notes: [] }, 'invalid_output_schema'],
  ];
  for (const [patch, reason] of cases) { const r = await bad(patch)(); assert.equal(r.status, 'failed', JSON.stringify(patch).slice(0, 80)); assert.equal(r.reason, reason); assert.equal(r.output, null); }
  const short = await live(envelope(candidateReport(SELECTED, { overview: text(100), topics: topics.map(t => ({ ...t, what_changed: text(30), impact: text(20), evidence: text(20) })), practical_notes: [{ note: text(20), article_ids: ['a01'] }] })));
  assert.equal(short.report.reason, 'invalid_output_length');
  for (const raw of ['{"overview":"x"', '```json\n{}\n```', JSON.stringify(candidateReport()).replace('"overview"', '"overview":"a","overview"'), 'null']) {
    const data = envelope(); data.candidates[0].content.parts = [{ text: raw }]; // raw model text, not re-encoded
    const { report } = await live(data);
    assert.equal(report.status, 'failed', raw); assert.match(report.reason, /^invalid_output_(json|schema)$/); assert.equal(report.output, null);
  }
});
test('envelope failures cannot pass: truncation, filters, tool parts, wrong model, blocked prompt, error body', async () => {
  const mk = over => envelope(candidateReport(), over);
  const cases = [
    [mk({ candidates: [{ finishReason: 'MAX_TOKENS', content: { parts: [{ text: '{"overview":"途中' }] } }] }), 'incomplete_answer'],
    [mk({ candidates: [{ finishReason: 'SAFETY' }] }), 'incomplete_answer'],
    [mk({ candidates: [{ finishReason: 'STOP', content: { parts: [{ functionCall: { name: 'x', args: {} } }] } }] }), 'invalid_response'],
    [mk({ candidates: [{ finishReason: 'STOP', content: { parts: [] } }] }), 'invalid_response'],
    [mk({ candidates: [] }), 'invalid_response'], [mk({ modelVersion: 'gemini-3-pro' }), 'model_mismatch'], [mk({ modelVersion: undefined }), 'model_mismatch'],
    [mk({ promptFeedback: { blockReason: 'SAFETY' } }), 'prompt_blocked'], [{ error: { message: 'RAW ERROR BODY NOT SAVED', code: 500 } }, 'invalid_response'], ['[]', 'invalid_response'], ['not json', 'invalid_json'],
  ];
  for (const [data, reason] of cases) {
    const { report, calls } = await live(data); assert.equal(report.reason, reason, reason); assert.equal(calls.length, 1); assert.equal(report.output, null);
    assert.ok(!JSON.stringify(report).includes('RAW ERROR BODY') && !JSON.stringify(report).includes('途中'));
  }
  const truncated = await live(mk({ candidates: [{ finishReason: 'MAX_TOKENS', content: { parts: [{ text: '{"overview":"途中' }] } }], usageMetadata: { thoughtsTokenCount: 32000, totalTokenCount: 32768 } }));
  assert.equal(truncated.report.finish_reason, 'MAX_TOKENS'); assert.equal(truncated.report.usage.thoughtsTokenCount, 32000);
});
test('HTTP failures (400, 429, 503, redirects) stop after one request: no retry, fallback model or stored error body', async () => {
  for (const [status, reason] of [[400, 'bad_request'], [401, 'unauthorized'], [403, 'forbidden'], [429, 'rate_limited'], [503, 'unavailable'], [500, 'http_error'], [302, 'http_error']]) {
    const { report, calls } = await live(() => new Response('RAW ERROR BODY ' + KEY, { status }));
    assert.equal(report.reason, reason); assert.equal(report.http_status, status); assert.equal(calls.length, 1); assert.equal(report.requests_sent, 1);
    assert.ok(!JSON.stringify(report).includes('RAW ERROR BODY') && !JSON.stringify(report).includes(KEY));
  }
  const net = await live(() => { throw new TypeError('connect failed ' + KEY); });
  assert.equal(net.report.reason, 'network_error'); assert.equal(net.calls.length, 1); assert.ok(!JSON.stringify(net.report).includes(KEY));
});
test('deadline, oversized and invalid responses are bounded and never stored', async () => {
  const slow = await live(() => new Promise(() => {}), { timeoutMs: 30 });
  assert.equal(slow.report.reason, 'timeout'); assert.equal(slow.calls.length, 1); assert.equal(slow.report.output, null);
  const stalled = await live(() => new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{"candidates":')); } }), { status: 200 }), { timeoutMs: 30 });
  assert.equal(stalled.report.reason, 'timeout');
  const big = await live('x'.repeat(P.LIMITS.responseBytes + 1)); assert.equal(big.report.reason, 'response_too_large');
  const utf = await live(() => new Response(new Uint8Array([0xff, 0xfe, 0xfd]), { status: 200 })); assert.equal(utf.report.reason, 'invalid_json');
  const bogus = await live(envelope(candidateReport(), { responseId: 'bad id with spaces ' + KEY, usageMetadata: { promptTokenCount: -1, thoughtsTokenCount: 1.5, totalTokenCount: '9' } }));
  assert.equal(bogus.report.response_id, null); assert.equal(bogus.report.usage.promptTokenCount, null); assert.equal(bogus.report.usage.thoughtsTokenCount, null);
});
test('renderer escapes untrusted input without executing HTML or Markdown', async () => {
  const report = await P.runPoc({ files: FILES });
  report.input[0].title = '<img src=x onerror=alert(1)> **bold**';
  const md = P.renderMarkdown(report);
  assert.ok(!md.includes('<img') && md.includes('&lt;img'));
});
test('output preflight refuses production directories before any request', () => {
  assert.throws(() => P.openReports(path.join(P.WEEK.log, '..')), { code: 'invalid_output_directory' });
  for (const dir of ['logs', 'data', 'imports', 'experiments/gemini-hydrogen-weekly', '/']) {
    assert.throws(() => P.openReports(path.resolve(__dirname, '..', dir)), e => e.code === 'invalid_output_directory', dir);
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gemini-weekly-test-'));
  const fds = P.openReports(dir); fds.forEach(fd => fs.closeSync(fd));
  fs.symlinkSync('/etc/hosts', path.join(dir, 'link')); fs.rmSync(path.join(dir, 'report.json')); fs.symlinkSync('/etc/hosts', path.join(dir, 'report.json'));
  assert.throws(() => P.openReports(dir)); fs.rmSync(dir, { recursive: true, force: true });
});
test('CLI: default is a no-network dry run on the real fixed input; --live without authorization or key sends nothing', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gemini-weekly-cli-'));
  const lines = []; const log = console.log; console.log = (...a) => lines.push(a.join(' '));
  try {
    assert.equal(await P.main(['--output-dir', dir], {}), 0);
    const plan = JSON.parse(fs.readFileSync(path.join(dir, 'report.json'), 'utf8'));
    assert.equal(plan.status, 'plan_only'); assert.equal(plan.requests_sent, 0); assert.equal(plan.snapshot.pinned_manifest, 'matched');
    assert.equal(await P.main(['--live', '--output-dir', dir], { GEMINI_API_KEY: KEY }), 1);
    const refused = JSON.parse(fs.readFileSync(path.join(dir, 'report.json'), 'utf8'));
    assert.equal(refused.reason, 'live_not_authorized'); assert.equal(refused.requests_sent, 0);
    assert.equal(await P.main(['--live', '--output-dir', dir, '--bogus'], {}), 2);
    assert.ok(!lines.join('\n').includes(KEY) && !fs.readFileSync(path.join(dir, 'report.md'), 'utf8').includes(KEY));
  } finally { console.log = log; fs.rmSync(dir, { recursive: true, force: true }); }
});
