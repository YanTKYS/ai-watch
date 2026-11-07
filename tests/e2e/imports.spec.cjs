const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const M = require('../../import-markdown.js');
const fixture = name => fs.readFileSync(path.join(root, 'tests/fixtures/imports', name + '.md'), 'utf8');
const row = (p, type = 'file') => ({ name: p.split('/').pop(), path: p, type, download_url: 'https://evil.example/ignored' });
const test = base.extend({
  mock: async ({ page, context, baseURL }, use) => {
    const state = { fail: false, empty: false, malformed: false, added: false, missing: false, real: false, grokText: null, museText: null, slow: null, slowP: null, slowM: null, calls: [], unexpected: [], errors: [] };
    page.on('pageerror', e => state.errors.push(e.message));
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.origin === 'https://api.github.com' && u.pathname.startsWith('/repos/YanTKYS/ai-watch/contents/')) {
        state.calls.push(u.href);
        if (state.fail) return route.fulfill({ status: 403, json: { message: 'rate limit' } });
        if (state.malformed) return route.fulfill({ json: { message: 'not a listing' } });
        const relative = u.pathname.split('/contents/')[1];
        const data = state.empty ? [] : {
          'imports/x': [row('imports/x/2027', 'dir'), row('imports/x/2026', 'dir')],
          'imports/x/2026': [row('imports/x/2026/x-20261030.md'), row('imports/x/2026/x-20261029.md'), row('imports/x/2026/x-20260230.md')],
          'imports/x/2027': state.added ? [row('imports/x/2027/x-20270102.md')] : [],
          'imports/p': [row('imports/p/2026-W44.md'), ...(state.added ? [row('imports/p/2026-W45.md')] : [])],
          'imports/m': [row('imports/m/muse-20261102.md'), row('imports/m/muse-20261103.md'),
            row('imports/m/muse-20260230.md'), row('imports/m/muse-20261104.md', 'symlink'),
            { name: 'muse-20261105.md', path: 'imports/m/../m/muse-20261105.md', type: 'file' },
            ...(state.added ? [row('imports/m/muse-20270101.md')] : [])],
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
        if (state.slowM && pathname.includes('/m/')) await state.slowM;
        if (state.missing) return route.fulfill({ status: 404, body: 'not deployed' });
        const text = state.real ? fs.readFileSync(path.join(root, pathname), 'utf8')
          : pathname.includes('/m/') ? state.museText ?? fixture('muse')
          : pathname.includes('/x/') ? (state.grokText || fixture('grok')).replaceAll('2027-01-02', pathname.includes('2027') ? '2027-01-02' : '2026-10-30') : fixture('perplexity');
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

for (const source of ['x', 'p', 'm']) test(`sample with ${source} route never reads production imports or the public API`, async ({ page, mock }) => {
  await page.goto(`/?sample&source=${source}&entry=2026-11-03`);
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await expect(page.locator('#source-navigation')).toBeHidden(); await expect(page.locator('#import-view')).toBeHidden();
  expect(mock.calls).toEqual([]);
  expect(new URL(page.url()).searchParams.has('source')).toBe(false);
});

for (const width of [1280, 375]) for (const colorScheme of ['light', 'dark']) {
  test(`Muse ${width}px ${colorScheme}: both real days, full content, one column and keyboard details`, async ({ page, mock }) => {
    mock.real = true;
    await page.setViewportSize({ width, height: 900 }); await page.emulateMedia({ colorScheme });
    await page.goto('/?source=m');
    await expect(page.locator('#import-select option')).toHaveText(['2026-11-03', '2026-11-02']);
    await expect(page.locator('#import-select')).toHaveValue('2026-11-03');
    await expect(page.locator('#import-status')).toContainText('2026-11-03の原記録');
    await expect(page.getByRole('link', { name: 'Muse（業務活用）', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('#import-disclaimer')).toContainText('未検証の収集・業務活用候補');
    await expect(page.locator('#official-controls')).toBeHidden();
    await expect(page.locator('#collection-health')).toBeHidden();
    const cards = page.locator('.muse-card');
    const [first, second] = await Promise.all([cards.nth(0).boundingBox(), cards.nth(1).boundingBox()]);
    expect(first.x).toBe(second.x); expect(second.y).toBeGreaterThanOrEqual(first.y + first.height);
    expect(first.width).toBeLessThanOrEqual(864); expect(first.y).toBeLessThan(800);
    const summary = cards.first().locator('summary');
    await summary.focus(); await page.keyboard.press('Enter');
    await expect(cards.first().locator('details')).toHaveAttribute('open', '');
    await page.keyboard.press('Space'); await expect(cards.first().locator('details')).not.toHaveAttribute('open');
    for (const day of ['20261103', '20261102']) {
      const id = `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
      if (day === '20261102') await page.locator('#import-select').selectOption(id);
      await expect(page.locator('#import-status')).toContainText(`${id}の原記録`);
      const text = fs.readFileSync(path.join(root, `imports/m/muse-${day}.md`), 'utf8'), parsed = M.muse(text);
      await expect(cards).toHaveCount(10);
      await expect(page.locator('#import-heading')).toHaveText(parsed.title);
      await expect(page.locator('#import-metadata')).toContainText(`収集日 ${id}`);
      await expect(page.locator('#import-metadata')).toContainText('件数 10件');
      await expect(page.locator('#import-metadata')).toContainText('収集元 Muse');
      for (let i = 0; i < parsed.items.length; i++) {
        const item = parsed.items[i], card = cards.nth(i);
        await expect(card.locator('h3')).toHaveText(item.title);
        await expect(card.locator('.muse-category')).toContainText(item.fields['分野']);
        await expect(card.locator('.muse-field').first()).toContainText(item.fields['何を楽にするのか']);
        await expect(card.locator('details')).toContainText(item.fields['再現の仕組み']);
        if (item.fields['何が新しくなったか']) await expect(card.locator('details')).toContainText(item.fields['何が新しくなったか']);
        const link = card.locator('.muse-source a');
        await expect(link).toHaveAttribute('href', item.fields['出典リンク']);
        await expect(link).toHaveAttribute('target', '_blank'); await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      }
      await page.locator('.muse-original summary').click();
      expect(await page.locator('.muse-original pre').textContent()).toBe(text);
      await noOverflow(page); await page.locator('.muse-original summary').click();
      if (day === '20261103' && process.env.IMPORT_READER_PREVIEW_DIR) {
        await cards.first().locator('summary').click();
        await page.screenshot({ path: `${process.env.IMPORT_READER_PREVIEW_DIR}/muse-${width}-${colorScheme}.png`, fullPage: true });
        await cards.first().locator('summary').click();
      }
    }
    await page.goBack(); await expect(page.locator('#import-select')).toHaveValue('2026-11-03');
    await page.goForward(); await expect(page.locator('#import-select')).toHaveValue('2026-11-02');
    await page.reload(); await expect(page.locator('#import-select')).toHaveValue('2026-11-02');
  });
}

test('Muse discovers a new year by refresh, caches, shares project URLs and preserves official filters', async ({ page, context, mock }) => {
  await page.goto('/ai-watch/?q=Codex&category=AIコーディング');
  await expect(page.locator('#view-heading')).toHaveText('絞り込み結果');
  await page.getByRole('link', { name: 'Muse（業務活用）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-11-03の原記録');
  const before = mock.calls.length;
  await page.locator('#import-select').selectOption('2026-11-02');
  await expect(page.locator('#import-status')).toContainText('2026-11-02の原記録');
  await page.locator('#import-select').selectOption('2026-11-03');
  await expect(page.locator('#import-status')).toContainText('2026-11-03の原記録');
  expect(mock.calls.length).toBe(before + 1);
  mock.added = true; await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('#import-select option').first()).toHaveAttribute('value', '2027-01-01');
  await expect(page.locator('#import-select')).toHaveValue('2026-11-03');
  await page.locator('#import-select').selectOption('2027-01-01');
  await expect(page.locator('#import-status')).toContainText('2027-01-01の原記録');
  await expect(page.locator('#import-original')).toHaveAttribute('href', 'https://github.com/YanTKYS/ai-watch/blob/main/imports/m/muse-20270101.md');
  const shared = await context.newPage();
  await shared.goto(page.url()); await expect(shared.locator('#import-select')).toHaveValue('2027-01-01'); await shared.close();
  expect(mock.calls).toContain('/imports/m/muse-20270101.md');
  await page.getByRole('link', { name: '公式ニュース', exact: true }).click();
  await expect(page.getByRole('searchbox')).toHaveValue('Codex');
  expect(new URL(page.url()).searchParams.get('category')).toBe('AIコーディング');
  await page.goBack(); await expect(page.locator('#import-select')).toHaveValue('2027-01-01');
  await page.getByRole('link', { name: 'Grok（X）', exact: true }).click();
  await expect(page.locator('.grok-card')).toHaveCount(2);
  await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
  await expect(page.locator('#import-content table')).toHaveCount(1);
});

test('Muse handles missing fields, unknown long labels, multiline Markdown, injection and full fallback', async ({ page, mock }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto('/?source=m'); await expect(page.locator('.muse-card')).toHaveCount(2);
  const cards = page.locator('.muse-card');
  await expect(cards.first().locator('h3 strong')).toHaveText('固定');
  await expect(cards.nth(1).locator('h3')).toHaveText('（タイトルなし）');
  await expect(cards.nth(1).locator('.muse-category')).toContainText('（記載なし）');
  await expect(cards.nth(1).locator('.muse-field').first()).toContainText('（記載なし）');
  await expect(page.locator('#import-metadata')).toContainText('未知の共通欄');
  await cards.first().locator('summary').click();
  await expect(cards.first().locator('ol li')).toHaveCount(2);
  await expect(cards.first().locator('pre code')).toContainText('## コード内の見出し');
  await expect(cards.first().locator('details')).toContainText('再現方法の末尾');
  await expect(cards.first().locator('details')).toContainText('未知の長いフィールド名も欠落させずに表示する');
  await expect(cards.first().locator('details')).toContainText('二番目の値');
  await expect(cards.first().getByRole('link', { name: '補足', exact: true })).toHaveAttribute('href', 'https://example.com/reference');
  await cards.nth(1).locator('summary').click();
  await expect(cards.nth(1).locator('.muse-source')).toContainText('javascript:alert(1)');
  await expect(cards.nth(1).locator('.muse-source a')).toHaveCount(0);
  await expect(page.locator('#import-content img, #import-content script, #import-content iframe, #import-content svg')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined(); await noOverflow(page);
  mock.museText = '# 形式違い\n\n本文を残す。<script>window.injected=true</script>';
  await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('.muse-fallback')).toContainText('本文を残す。');
  await page.locator('.muse-original summary').click();
  expect(await page.locator('.muse-original pre').textContent()).toBe(mock.museText);
  await noOverflow(page);
});

test('Muse API, malformed catalogue, empty text and deployment errors retry; invalid selection fetches no body', async ({ page, mock }) => {
  mock.fail = true; await page.goto('/?source=m');
  await expect(page.locator('#import-status')).toContainText('制限');
  mock.fail = false; mock.malformed = true;
  await page.getByRole('button', { name: '原記録を再試行' }).click();
  await expect(page.locator('#import-status')).toContainText('形式');
  mock.malformed = false; mock.empty = true;
  await page.getByRole('button', { name: '原記録を再試行' }).click();
  await expect(page.locator('#import-status')).toContainText('まだありません');
  mock.empty = false; mock.missing = true;
  await page.getByRole('button', { name: '一覧を更新', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('まだPagesへ配信');
  mock.missing = false; mock.museText = ' ';
  await page.getByRole('button', { name: '原記録を再試行' }).click();
  await expect(page.locator('#import-status')).toContainText('本文が空');
  mock.museText = null; const retry = page.getByRole('button', { name: '原記録を再試行' });
  await retry.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#import-status')).toContainText('表示しました');
  await expect(page.locator('#import-heading')).toBeFocused();
  const before = mock.calls.filter(c => c.startsWith('/imports/')).length;
  for (const id of ['2026-02-30', '../../evil', '2026-11-04', '2026-11-05', '2099-01-01']) {
    await page.goto(`/?source=m&entry=${encodeURIComponent(id)}`);
    await expect(page.locator('#import-status')).toContainText('一覧にありません');
    await expect(page.locator('#import-content')).toBeEmpty();
  }
  expect(mock.calls.filter(c => c.startsWith('/imports/')).length).toBe(before);
});

test('late Muse response cannot replace another source', async ({ page, mock }) => {
  let release; mock.slowM = new Promise(resolve => { release = resolve; });
  await page.goto('/?source=m'); await expect(page.locator('#import-status')).toContainText('本文を読み込み中');
  await page.getByRole('link', { name: 'Perplexity（週次）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-W44の原記録');
  const response = page.waitForResponse(r => new URL(r.url()).pathname.includes('/imports/m/'));
  release(); await response;
  await expect(page.locator('#import-content table')).toHaveCount(1);
  await expect(page.locator('.muse-card')).toHaveCount(0);
  await page.getByRole('link', { name: 'Muse（業務活用）', exact: true }).click();
  await expect(page.locator('#import-status')).toContainText('2026-11-03の原記録');
  await expect(page.locator('.muse-card')).toHaveCount(2);
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
  mock.grokText = fixture('grok-incomplete').replace('## （空見出し用の合成マーカー）', '## ');
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

test('#54: source links carry current filters, reading state survives a source round trip, 320px card meta is not truncated', async ({ page, context, mock }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/ai-watch/?month=2026-10');
  const grok = page.getByRole('link', { name: 'Grok（X）', exact: true });
  // 過去日を開いて往復すると、最新日だけでなく開いた日も復元される。
  const days = page.locator('details.day');
  await expect(days.first()).toHaveAttribute('open', '');
  const older = days.nth(1); await older.locator('summary').click(); await expect(older).toHaveAttribute('open', '');
  const openedBefore = await days.evaluateAll(ds => ds.filter(d => d.open).length);
  await grok.click(); await expect(page.locator('.grok-card')).toHaveCount(2);
  await page.goBack(); await expect(page.locator('#view-heading')).toBeVisible();
  expect(await days.evaluateAll(ds => ds.filter(d => d.open).length)).toBe(openedBefore);
  await expect(older).toHaveAttribute('open', '');
  // 検索後のhrefは現在条件を持ち、新しいタブで開いて公式へ戻っても検索語が残る。
  const input = page.getByRole('searchbox'); await input.fill('Codex'); await input.press('Enter');
  await expect(page.locator('#view-heading')).toHaveText('検索結果');
  await expect(grok).toHaveAttribute('href', /q=Codex.*source=x|source=x.*q=Codex/);
  const tab = await context.newPage();
  await tab.goto(new URL(await grok.getAttribute('href'), page.url()).href);
  await expect(tab.locator('.grok-card')).toHaveCount(2);
  await tab.getByRole('link', { name: '公式ニュース', exact: true }).click({ modifiers: [] });
  await expect(tab.getByRole('searchbox')).toHaveValue('Codex'); await tab.close();
  // 320pxでも取得日・カテゴリを省略しない。
  const foot = page.locator('.search-results .card .foot').first();
  await expect(foot).toContainText('カテゴリ:');
  expect(await foot.evaluate(n => n.scrollWidth <= n.clientWidth && getComputedStyle(n).textOverflow !== 'ellipsis')).toBe(true);
  // 条件を解除したら古い検索語はhrefに残らない。
  await page.getByRole('button', { name: '検索語をクリア' }).click();
  await expect(grok).not.toHaveAttribute('href', /q=/);
  await noOverflow(page);
});
