const { test: base, expect } = require('@playwright/test');

// テスト中は自分のローカルサーバー以外へ出ない。製品の通信処理には変更を加えない。
const test = base.extend({
  runtimeChecks: [async ({ page, context, baseURL }, use) => {
    const blocked = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== new URL(baseURL).origin) {
        blocked.push(route.request().url());
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    await use();
    expect.soft(blocked, '外部へのリクエストがない').toEqual([]);
    expect.soft(errors, '未処理のページ例外がない').toEqual([]);
  }, { auto: true }],
});

async function tabTo(page, target, backward = false) {
  // 追加表示後の記事リンクも通れる上限を定め、タイムアウトまで回り続けない。
  for (let i = 0; i < 300; i++) {
    if (await target.evaluateAll(nodes => nodes.includes(document.activeElement))) return;
    await page.keyboard.press(backward ? 'Shift+Tab' : 'Tab');
  }
  await expect(target, 'Tabで対象へ到達できる').toBeFocused();
}

async function noOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

const results = Array.from({ length: 120 }, (_, i) => ({
  title: `（E2E合成）Alpha ${String(i).padStart(3, '0')}`,
  url: `https://news.example.com/e2e/${i}`,
  retrieved: '2026-10-24', category: 'AIコーディング', feed: 'E2E Feed',
}));

test('desktop sample: skip, daily headings, date toggle, month and order by keyboard', async ({ page }) => {
  const statusRequests = [];
  page.on('request', request => {
    if (request.url().endsWith('/data/collection-status.json')) statusRequests.push(request.url());
  });
  await page.goto('/?sample');
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await expect(page.locator('#collection-health')).toBeHidden();
  await expect(page.locator('.day[open]')).toHaveCount(1);
  await expect(page.locator('.day-summary').first().locator('h3')).toContainText('2026年10月17日');
  await expect(page.locator('.day[open] .category-title').first()).toHaveJSProperty('tagName', 'H4');
  await expect(page.locator('.day[open] .card-title').first()).toHaveJSProperty('tagName', 'H5');

  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: '本文へ移動' });
  await expect(skip).toBeFocused();
  expect((await skip.boundingBox()).y).toBeGreaterThanOrEqual(0);
  await page.keyboard.press('Enter');
  await expect(page.locator('main')).toBeFocused();
  const summary = page.locator('.day-summary').first();
  await tabTo(page, summary);
  await page.keyboard.press('Enter');
  await expect(page.locator('.day').first()).toHaveJSProperty('open', false);
  await page.keyboard.press('Space');
  await expect(page.locator('.day').first()).toHaveJSProperty('open', true);
  await expect(summary).toBeFocused();

  const month = page.getByRole('combobox', { name: '表示する月' });
  await tabTo(page, month, true);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  await expect(month).toBeFocused();
  const order = page.getByRole('combobox', { name: '並び順' });
  await tabTo(page, order);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(order).toHaveValue('asc');
  await expect(order).toBeFocused();
  await expect(page.locator('.day-summary').first()).toContainText('2026年9月10日');
  await expect(page.locator('#view-announcement')).toContainText('古い順');
  await noOverflow(page);
  expect(statusRequests, 'sampleでは本番状態を取得しない').toEqual([]);
});

test('320px search: zero, 50/100/120, final focus and clear to daily', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.route('**/samples/data/search-index.json', route => route.fulfill({ json: results }));
  await page.goto('/?sample');
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  const input = page.getByRole('searchbox');
  await tabTo(page, input);
  await input.pressSequentially('NoMatch');
  await input.press('Enter');
  await expect(page.locator('.search-empty')).toBeVisible();
  await expect(page.locator('#view-announcement')).toContainText('検索結果: 0件');
  await expect(input).toBeFocused();
  await input.press('ControlOrMeta+A');
  await input.pressSequentially('Alpha');
  await input.press('Enter');
  const cards = page.locator('.search-results .card');
  await expect(cards).toHaveCount(50);
  await expect(page.locator('#content h2')).toHaveText('検索結果');
  await expect(page.locator('#content h3')).toHaveCount(50);
  await expect(page.locator('#content h5')).toHaveCount(0);
  await expect(page.locator('#view-announcement')).toContainText('120件。50件');
  await expect(input).toBeFocused();
  await noOverflow(page);

  const more = page.getByRole('button', { name: /さらに表示/ });
  await tabTo(page, more);
  await page.keyboard.press('Enter');
  await expect(cards).toHaveCount(100);
  await expect(more).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(cards).toHaveCount(120);
  await expect(more).toBeHidden();
  const firstAdded = cards.nth(100).getByRole('heading', { level: 3 });
  await expect(firstAdded).toBeFocused();
  await expect(firstAdded).toContainText('Alpha 100');
  await expect(page.locator('#view-announcement')).toHaveText('120件中120件を表示しました。');
  await page.keyboard.press('Tab');
  await expect(firstAdded.getByRole('link')).toBeFocused();
  await expect(firstAdded.getByRole('link')).toHaveAttribute('aria-describedby', 'new-tab-hint');
  await noOverflow(page);

  const clear = page.getByRole('button', { name: 'クリア' });
  await tabTo(page, clear, true);
  await page.keyboard.press('Enter');
  await expect(input).toBeFocused();
  await expect(input).toHaveValue('');
  await expect(clear).toBeDisabled();
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await expect(page.locator('#view-announcement')).toContainText('日刊: 2026年10月');
});

test('retry: button survives pending/failure and success focuses recovered month', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  let attempts = 0, pendingRetry;
  await page.route('**/samples/logs/2026/2026-10.md', async route => {
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 503, body: 'unavailable' });
    if (attempts === 2) return new Promise(resolve => { pendingRetry = { route, resolve }; });
    return route.continue(); // 3回目は実sampleを読み、ファイルを書き換えない
  });
  await page.goto('/?sample');
  const retry = page.getByRole('button', { name: '再試行' });
  await expect(retry).toBeVisible();
  await expect(page.locator('#status')).toContainText('取得できません');
  await tabTo(page, retry);
  await page.keyboard.press('Enter');
  await expect(retry).toHaveAttribute('aria-disabled', 'true');
  await expect(retry).toBeFocused();
  await expect.poll(() => Boolean(pendingRetry)).toBe(true);
  // 待機中の連打を検証し、時間ではなく保持した応答で進める。
  await page.keyboard.press('Enter');
  await pendingRetry.route.fulfill({ status: 503, body: 'still unavailable' });
  pendingRetry.resolve();
  await expect(retry).toHaveAttribute('aria-disabled', 'false');
  await expect(retry).toBeFocused();
  await expect(page.locator('#view-announcement')).toContainText('取得できません');
  expect(attempts).toBe(2);
  await page.keyboard.press('Enter');
  await expect(page.locator('#view-heading')).toBeFocused();
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await expect(retry).toBeHidden();
  await expect(page.locator('.card:visible').first()).toBeVisible();
  expect(attempts).toBe(3);
  await noOverflow(page);
});

test('production health snapshot: success/partial/404/broken remain independent of articles', async ({ page }) => {
  // 本番モードのファイル要求も、内容は既存sampleへのローカル応答差し替えだけで用意する。
  await page.route(/\/(data\/(months|search-index)\.json|logs\/\d{4}\/\d{4}-\d{2}\.md)$/, route => {
    const url = new URL(route.request().url());
    return route.continue({ url: `${url.origin}/samples${url.pathname}` });
  });
  let mode = 'success';
  await page.route('**/data/collection-status.json', route => {
    if (mode === '404') return route.fulfill({ status: 404, body: 'not found' });
    if (mode === 'broken') return route.fulfill({ contentType: 'application/json', body: '{broken' });
    const stamp = new Date().toISOString(); // 鮮度判定に依存する過去の固定日時を使わない
    return route.fulfill({ json: {
      schema_version: 1,
      collection: { attempted_at: stamp, completed_at: stamp, last_all_success_at: mode === 'success' ? stamp : null,
        result: mode, new_articles: 0, feeds: [
          { name: 'Feed A', status: 'success', candidates: 0, adopted: 0 },
          { name: 'Feed B', status: mode === 'success' ? 'success' : 'failed',
            candidates: mode === 'success' ? 0 : null, adopted: mode === 'success' ? 0 : null },
        ] },
      index: { checked_at: stamp, result: 'success', last_success_at: stamp, for_collection: stamp },
    } });
  });
  for (const [value, label] of [['success', '正常・新着なし'], ['partial', '一部取得失敗'], ['404', '状態不明'], ['broken', '状態不明']]) {
    mode = value;
    const response = page.waitForResponse('**/data/collection-status.json');
    await page.goto('/');
    await (await response).finished();
    await expect(page.locator('#view-heading')).toHaveText('2026年10月');
    await expect(page.locator('#collection-summary')).toContainText(label);
    await expect(page.locator('.card:visible').first()).toBeVisible();
    const input = page.getByRole('searchbox');
    await input.fill('サンプル');
    await input.press('Enter');
    await expect(page.locator('.search-results .card')).toHaveCount(50);
    await expect(page.locator('#view-announcement')).toContainText('検索結果:');
    await expect(page.locator('#collection-summary')).toContainText(label);
    await expect(page.locator('#load-retry')).toBeHidden();
  }
});
