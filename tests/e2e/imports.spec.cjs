const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const fixture = name => fs.readFileSync(path.join(root, 'tests/fixtures/imports', name + '.md'), 'utf8');
const row = (p, type = 'file') => ({ name: p.split('/').pop(), path: p, type, download_url: 'https://evil.example/ignored' });
const test = base.extend({
  mock: async ({ page, context, baseURL }, use) => {
    const state = { fail: false, empty: false, added: false, missing: false, real: false, grokText: null, slow: null, slowP: null, calls: [], unexpected: [], errors: [] };
    page.on('pageerror', e => state.errors.push(e.message));
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.origin === 'https://api.github.com' && u.pathname.startsWith('/repos/YanTKYS/ai-watch/contents/')) {
        state.calls.push(u.href);
        if (state.fail) return route.fulfill({ status: 403, json: { message: 'rate limit' } });
        const relative = u.pathname.split('/contents/')[1];
        const data = state.empty ? [] : {
          'imports/x': [row('imports/x/2027', 'dir'), row('imports/x/2026', 'dir')],
          'imports/x/2026': [row('imports/x/2026/x-20261030.md'), row('imports/x/2026/x-20261029.md'), row('imports/x/2026/x-20260230.md')],
          'imports/x/2027': state.added ? [row('imports/x/2027/x-20270102.md')] : [],
          'imports/p': [row('imports/p/2026-W44.md'), ...(state.added ? [row('imports/p/2026-W45.md')] : [])],
        }[relative];
        if (!data) state.unexpected.push(u.href);
        return route.fulfill({ json: data || [] });
      }
      if (u.origin !== new URL(baseURL).origin) { state.unexpected.push(u.href); return route.abort(); }
      const pathname = u.pathname.replace(/^\/ai-watch(?=\/)/, '');
      if (pathname.startsWith('/imports/')) {
        state.calls.push(pathname);
        if (state.slow && pathname.includes('/x/')) await state.slow;
        if (state.slowP && pathname.includes('/p/')) await state.slowP;
        if (state.missing) return route.fulfill({ status: 404, body: 'not deployed' });
        const text = state.real ? fs.readFileSync(path.join(root, pathname), 'utf8') : pathname.includes('/x/') ? (state.grokText || fixture('grok')).replaceAll('2027-01-02', pathname.includes('2027') ? '2027-01-02' : '2026-10-30') : fixture('perplexity');
        return route.fulfill({ contentType: 'text/markdown', body: text });
      }
      if (u.pathname.startsWith('/ai-watch/')) {
        const file = path.join(root, pathname === '/' ? 'index.html' : pathname);
        return route.fulfill({ path: file });
      }
      return route.continue();
    });
    await use(state);
    expect(state.unexpected, 'fixture以外の外部通信・APIパスがない').toEqual([]);
    expect(state.errors, '未処理のページ例外がない').toEqual([]);
  },
});
async function noOverflow(page) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); }

for (const width of [1280, 375]) for (const colorScheme of ['light', 'dark']) {
  test(`${width}px ${colorScheme}: sources, report structure, safe rendering and official history`, async ({ page, mock }) => {
    await page.setViewportSize({ width, height: 900 }); await page.emulateMedia({ colorScheme });
    await page.goto('/?q=Codex');
    await expect(page.locator('#view-heading')).toHaveText('検索結果');
    await expect(page.locator('#content')).toContainText('Codex');
    const grok = page.getByRole('link', { name: 'Grok（X）', exact: true });
    await grok.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('#import-status')).toContainText('2026-10-30の原記録');
    await expect(page.locator('#official-controls')).toBeHidden(); await expect(page.locator('#collection-health')).toBeHidden();
    await expect(page.locator('#import-disclaimer')).toContainText('未検証');
    await expect(page.locator('#import-content')).toContainText('原記録の確度（未検証）');
    await expect(page.locator('#import-metadata')).toContainText('収集日時');
    await expect(page.locator('#import-metadata')).toContainText('対象期間');
    await expect(page.locator('#import-content img, #import-content script')).toHaveCount(0);
    await expect(page.locator('#import-content a[href^="javascript:"]')).toHaveCount(0);
    const cards = page.locator('.grok-card');
    await expect(cards).toHaveCount(2);
    await expect(cards.first().locator('h3')).toHaveText('1. （合成）モデルの更新');
    await expect(cards.first().locator('.grok-overview')).toHaveText('日本語・絵文字🧪・強調を含む未検証の候補。');
    await expect(cards.first().locator('.grok-point')).toContainText('元出典を確認。');
    await expect(cards.first().locator('.grok-card-meta')).toContainText('AIモデル');
    await expect(cards.first().locator('.grok-card-meta')).toContainText('@example');
    await expect(cards.first().locator('.grok-card-meta')).toContainText('2027-01-01 23:21 JST');
    await expect(cards.first().locator('.grok-confidence')).toContainText('公式発表');
    await expect(cards.first().getByRole('link', {name:'元投稿を開く'})).toHaveAttribute('href', 'https://x.com/example/status/123456');
    const [first, second] = await Promise.all([cards.nth(0).boundingBox(), cards.nth(1).boundingBox()]);
    if (width >= 1000) {
      expect(Math.abs(first.y - second.y)).toBeLessThan(2);
      expect(second.x).toBeGreaterThan(first.x + first.width);
      expect(first.width).toBeGreaterThan(500);
      expect(first.y).toBeLessThan(550);
    } else {
      expect(first.x).toBe(second.x); expect(second.y).toBeGreaterThan(first.y + first.height);
      expect(first.y).toBeLessThan(800);
    }
    // Success stays available to assistive technology without taking layout space.
    await expect(page.locator('#import-status')).toHaveClass('visually-hidden');
    await expect(page.locator('#import-status')).toHaveAttribute('aria-live', 'polite');
    await expect(page.locator('#import-heading')).toHaveText('X生成AIニュース — 2026-10-30');
    await expect(page.locator('#import-content h2')).toHaveCount(0);
    await expect(grok).toHaveAttribute('aria-current', 'page');
    await expect(grok).toHaveCSS('text-decoration-line', 'none');
    expect(await page.evaluate(() => window.injected)).toBeUndefined();
    await noOverflow(page);
    if (process.env.IMPORT_READER_PREVIEW_DIR) await page.screenshot({ path: `${process.env.IMPORT_READER_PREVIEW_DIR}/grok-${width}-${colorScheme}.png`, fullPage: true });
    await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
    await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
    await expect(page.locator('#import-metadata')).toContainText('調査日: 2026-10-31');
    await expect(page.locator('#import-metadata')).toContainText('2026-10-26〜2026-11-01');
    await expect(page.locator('#import-content table')).toHaveCount(1);
    await expect(page.locator('#import-content strong').first()).toHaveText('太字');
    await expect(page.locator('#import-content iframe, #import-content img, #import-content script')).toHaveCount(0);
    await expect(page.locator('#import-content a').first()).toHaveAttribute('href', 'https://github.com/example/tool');
    await expect(page.locator('#import-content a').first()).toHaveAttribute('rel', 'noopener noreferrer');
    await noOverflow(page);
    if (process.env.IMPORT_READER_PREVIEW_DIR) await page.screenshot({ path: `${process.env.IMPORT_READER_PREVIEW_DIR}/perplexity-${width}-${colorScheme}.png`, fullPage: true });
    await page.reload(); await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
    // After reloading, return through source links and verify both kinds of history.
    await page.getByRole('link', { name: '公式ニュース', exact: true }).click();
    await expect(page.locator('#view-heading')).toHaveText('検索結果');
    await expect(page.locator('#content')).toContainText('Codex');
    await expect(page.getByRole('searchbox')).toHaveValue('Codex');
    await page.goBack(); await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
    await page.goForward(); await expect(page.locator('#import-view')).toBeHidden();
  });
}

test('new filenames in a new year and week appear after refresh; project subpath and deep links work', async ({ page, mock }) => {
  await page.goto('/ai-watch/?source=x');
  await expect(page.locator('#import-select')).toHaveValue('2026-10-30');
  mock.added = true; await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('#import-select option').first()).toHaveAttribute('value', '2027-01-02');
  await page.locator('#import-select').selectOption('2027-01-02');
  await expect(page.locator('#import-status')).toContainText('2027-01-02の原記録');
  expect(new URL(page.url()).searchParams.get('entry')).toBe('2027-01-02');
  await page.goBack(); await expect(page.locator('#import-select')).toHaveValue('2026-10-30');
  await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
  await expect(page.locator('#import-select option').first()).toHaveAttribute('value', '2026-W45');
  await page.goto('/ai-watch/?source=p&entry=2026-W44');
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  await expect(page.locator('#import-original')).toHaveAttribute('href', 'https://github.com/YanTKYS/ai-watch/blob/main/imports/p/2026-W44.md');
});

test('API error, empty catalogue and deployment 404 are distinct and recover by keyboard retry', async ({ page, mock }) => {
  mock.fail = true; await page.goto('/?source=p');
  await expect(page.locator('#import-status')).toContainText('制限');
  await expect(page.locator('#import-original')).toHaveAttribute('href', /tree\/main\/imports\/p$/);
  mock.fail = false; mock.empty = true;
  await page.getByRole('button', { name: '原記録を再試行' }).click();
  await expect(page.locator('#import-status')).toContainText('まだありません');
  mock.empty = false; mock.missing = true;
  await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('まだPagesへ配信');
  mock.missing = false;
  const retry = page.getByRole('button', { name: '原記録を再試行' });
  await retry.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  await expect(page.locator('#import-heading')).toBeFocused();
  // Returning to the same source while an older retry is pending must not
  // let that retry hide a newer error or steal focus from navigation.
  mock.missing = true; await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('まだPagesへ配信');
  let release; mock.slowP = new Promise(resolve => { release = resolve; }); mock.missing = false;
  await retry.click(); await expect(page.locator('#import-status')).toContainText('本文を読み込み中');
  await page.getByRole('link', { name: 'Grok（X）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-10-30の原記録');
  const weekly = page.getByRole('link', { name: 'Perplexity（週次）', exact: true });
  await weekly.click(); release();
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  await expect(retry).toBeHidden(); await expect(weekly).toBeFocused();
});

test('late source responses cannot overwrite a different source; invalid entry never constructs a body URL', async ({ page, mock }) => {
  let release; mock.slow = new Promise(resolve => { release = resolve; });
  await page.goto('/?source=x');
  await expect(page.locator('#import-status')).toContainText('本文を読み込み中');
  await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  release(); await expect(page.locator('#import-content')).toContainText('週次');
  await page.goto('/?source=x&entry=../../evil');
  await expect(page.locator('#import-status')).toContainText('一覧にありません');
  await expect(page.locator('#import-content')).toBeEmpty();
  expect(mock.calls.some(u => u.includes('/evil'))).toBe(false);
});

test('sample with import route never reads production imports or the public API', async ({ page, mock }) => {
  await page.goto('/?sample&source=p&entry=2026-W44');
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await expect(page.locator('#source-navigation')).toBeHidden(); await expect(page.locator('#import-view')).toBeHidden();
  expect(mock.calls).toEqual([]);
  expect(new URL(page.url()).searchParams.has('source')).toBe(false);
});


test('existing Grok daily and full Perplexity report render without rewriting their records', async ({ page, mock }) => {
  mock.real = true;
  await page.goto('/?source=x&entry=2026-10-30');
  await expect(page.locator('#import-status')).toContainText('2026-10-30の原記録');
  await expect(page.locator('.grok-card')).toHaveCount(4);
  await expect(page.locator('#import-metadata')).toContainText('2026-10-29 00:17');
  await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  await expect(page.locator('#import-metadata')).toContainText('2026-10-31');
  await expect(page.locator('#import-content')).toContainText('ollama/ollama');
  await expect(page.locator('#import-content a[href="https://github.com/ollama/ollama"]').first()).toBeVisible();
  expect(await page.locator('#import-content table').count()).toBeGreaterThan(5);
  await noOverflow(page);
});


test('Grok preserves unknown fields, missing values, long text and safe malformed fallback', async ({ page, mock }) => {
  mock.grokText = fixture('grok-incomplete');
  await page.setViewportSize({width:375,height:900});
  await page.goto('/?source=x&entry=2026-10-30');
  await expect(page.locator('#import-status')).toContainText('表示しました');
  const cards = page.locator('.grok-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.first().locator('h3')).toHaveText('（タイトルなし）');
  await expect(cards.first().locator('.grok-overview')).toContainText('長い概要の先頭');
  await expect(cards.first().locator('.grok-overview')).toContainText('長い概要の末尾');
  await expect(cards.first().locator('.grok-point')).toContainText('注目点の末尾');
  await expect(cards.first().locator('.grok-overview')).toHaveCSS('overflow', 'visible');
  await expect(cards.first().locator('.grok-extra')).toContainText('新しい欄');
  await expect(cards.first().locator('.grok-extra')).toContainText('<img src=x');
  await expect(cards.first().locator('.grok-source')).toHaveText('元投稿（リンク無効）: javascript:alert(1)');
  await expect(cards.nth(1).locator('.grok-overview')).toHaveText('（概要の記載なし）');
  await expect(cards.nth(1).locator('.grok-source')).toHaveText('元投稿URLの記載なし');
  await expect(cards.nth(1).locator('.grok-extra a')).toHaveAttribute('href', 'https://example.com/reference');
  await expect(page.locator('#import-metadata')).toContainText('新しい共通フィールド');
  await expect(page.locator('#import-metadata')).toContainText('表示件数 2件');
  await expect(page.locator('#import-content img, #import-content script')).toHaveCount(0);
  expect(await page.evaluate(()=>window.injected)).toBeUndefined(); await noOverflow(page);
  await page.setViewportSize({width:900,height:900});
  const [a, b] = await Promise.all([cards.nth(0).boundingBox(), cards.nth(1).boundingBox()]);
  expect(a.x).toBe(b.x); expect(b.y).toBeGreaterThan(a.y + a.height); await noOverflow(page);
  mock.grokText = '# 形式が異なる原記録\n\n本文は残します。<script>window.injected=true</script>';
  await page.getByRole('button', {name:'一覧を更新',exact:true}).click();
  await expect(page.locator('.grok-fallback')).toContainText('本文は残します。');
  await expect(page.locator('.grok-fallback script')).toHaveCount(0);
  await noOverflow(page);
});
