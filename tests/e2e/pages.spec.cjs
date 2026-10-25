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
  for (let i = 0; i < 450; i++) {
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

const filterResults = [
  ...results.map(item => ({...item, retrieved:'2026-10-02',feed:'Claude Code Releases'})),
  {title:'Alpha boundary',url:'https://news.example.com/boundary',category:'AIコーディング',feed:'Claude Code Releases',retrieved:'2026-09-30'},
  {title:'Alpha model',url:'https://news.example.com/model',category:'AIモデル',feed:'OpenAI News',retrieved:'2026-10-01'},
  {title:'Legacy metadata',url:'https://news.example.com/legacy'},
];

test('320px filters: queryless combination, three clears and return to selected daily month/order', async ({ page }) => {
  await page.setViewportSize({width:320,height:800});
  let indexRequests=0;
  await page.route('**/samples/data/search-index.json',route=>{
    indexRequests++;
    return route.fulfill({json:filterResults});
  });
  await page.goto('/?sample');
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  const month=page.getByRole('combobox',{name:'表示する月'});
  const order=page.getByRole('combobox',{name:'並び順'});
  await month.selectOption('2026-09'); await order.selectOption('asc');
  await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  const toggle=page.locator('#filter-toggle');
  await tabTo(page,toggle); await page.keyboard.press('Enter');
  const category=page.getByRole('checkbox',{name:'AIコーディング',exact:true});
  await expect(category).toBeVisible(); await tabTo(page,category); await page.keyboard.press('Space');
  await expect(category).toBeFocused();
  const feed=page.getByRole('checkbox',{name:'Claude Code Releases',exact:true});
  await tabTo(page,feed); await page.keyboard.press('Space');
  await expect(page.locator('#view-announcement')).toContainText('絞り込み結果: 121件');
  await page.locator('#filter-from').fill('2026-10-02');
  await page.locator('#filter-to').fill('2026-10-02');
  await expect(page.locator('#view-announcement')).toContainText('絞り込み結果: 120件');
  await expect(page.locator('#view-heading')).toHaveText('絞り込み結果');
  await expect(month).toBeDisabled(); await expect(order).toBeDisabled();
  await expect(page.getByRole('checkbox',{name:'OpenAI News',exact:true})).toBeVisible();
  await expect(page.getByRole('searchbox')).toHaveValue('');
  const filteredCards=page.locator('.search-results .card');
  await expect(filteredCards).toHaveCount(50);
  const filteredMore=page.getByRole('button',{name:/さらに表示/});
  await filteredMore.click(); await expect(filteredCards).toHaveCount(100);
  await filteredMore.press('Enter'); await expect(filteredCards).toHaveCount(120);
  await expect(filteredMore).toBeHidden();
  await expect(filteredCards.nth(100).getByRole('heading',{level:3})).toBeFocused();
  await noOverflow(page);

  const input=page.getByRole('searchbox');
  await input.fill('NoMatch'); await input.press('Enter');
  await expect(page.locator('.search-empty')).toContainText('条件に一致する記事はありません');
  await expect(page.locator('#active-conditions')).toContainText('Claude Code Releases');
  await expect(page.locator('#active-conditions')).toContainText('2026-10-02');
  const clearQuery=page.getByRole('button',{name:'検索語をクリア',exact:true});
  await tabTo(page,clearQuery); await page.keyboard.press('Enter');
  await expect(input).toBeFocused(); await expect(category).toBeChecked();
  await expect(page.locator('#view-heading')).toHaveText('絞り込み結果');
  await expect(page.locator('#view-announcement')).toContainText('絞り込み結果: 120件');

  await input.fill('Alpha'); await input.press('Enter');
  const clearFilters=page.getByRole('button',{name:'フィルターだけ解除'});
  await tabTo(page,clearFilters); await page.keyboard.press('Enter');
  await expect(toggle).toBeFocused(); await expect(category).not.toBeChecked();
  await expect(input).toHaveValue('Alpha');
  await expect(page.locator('#view-heading')).toHaveText('検索結果');
  await expect(page.locator('#view-announcement')).toContainText('122件');
  const clearAll=page.getByRole('button',{name:'すべての条件を解除'});
  await tabTo(page,clearAll); await page.keyboard.press('Enter');
  await expect(input).toBeFocused(); await expect(input).toHaveValue('');
  await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  await expect(month).toHaveValue('2026-09'); await expect(order).toHaveValue('asc');
  await expect(month).toBeEnabled(); await expect(page.locator('#active-conditions')).toBeHidden();
  expect(indexRequests).toBe(1);
  await noOverflow(page);
});

test('filter fetch failures keep daily, F05 retry keeps dates, invalid range is not zero results', async ({page})=>{
  let indexRequests=0;
  await page.route('**/samples/data/search-index.json',route=>{
    indexRequests++;
    return indexRequests<3 ? route.fulfill({status:503,body:'unavailable'}) : route.fulfill({json:filterResults});
  });
  await page.goto('/?sample'); await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await page.locator('#filter-toggle').click();
  await expect(page.getByRole('button',{name:'候補を再試行'})).toBeVisible();
  await expect(page.locator('.day[open] .card').first()).toBeVisible();
  await page.locator('#filter-from').fill('2026-10-02');
  const retry=page.getByRole('button',{name:'再試行',exact:true});
  await expect(retry).toBeVisible();
  await tabTo(page,retry); await page.keyboard.press('Enter');
  await expect(page.locator('#view-heading')).toHaveText('絞り込み結果');
  await expect(page.locator('#view-heading')).toBeFocused();
  await expect(page.locator('#filter-from')).toHaveValue('2026-10-02');
  await expect(page.locator('#view-announcement')).toContainText('120件');
  await expect(page.getByRole('button',{name:'候補を再試行'})).toBeHidden();
  await page.locator('#filter-to').fill('2026-10-01');
  await expect(page.locator('#status')).toContainText('開始日は終了日以前');
  await expect(page.locator('#filter-to')).toHaveAttribute('aria-invalid','true');
  await expect(page.locator('#content')).toBeEmpty();
  await expect(page.locator('#view-announcement')).not.toContainText('0件');
  await expect(retry).toBeHidden();
  await page.locator('#filter-to').fill('2026-10-02');
  await expect(page.locator('#view-announcement')).toContainText('120件');
  await expect(page.locator('#filter-to')).toBeFocused();
  expect(indexRequests).toBe(3);
  await page.getByRole('button',{name:'すべての条件を解除'}).click();
  await expect(page.locator('#view-heading')).toHaveText('2026年10月');
});


test('shared filters: reload/new tab restores multiple choices and an article beyond page 50 at 320px', async ({page,context})=>{
  await page.setViewportSize({width:320,height:800});
  await context.route('**/samples/data/search-index.json',route=>route.fulfill({json:filterResults}));
  await page.goto('/?sample&month=2026-09&order=asc&q=Alpha&category=AIモデル&category=AIコーディング&category=AIモデル&feed=OpenAI+News&feed=Claude+Code+Releases&from=2026-09-30&to=2026-10-02');
  await expect(page.locator('#view-announcement')).toContainText('122件');
  await expect(page.locator('#month-select')).toHaveValue('2026-09');
  await expect(page.locator('#order-select')).toHaveValue('asc');
  expect(new URL(page.url()).searchParams.getAll('category')).toEqual(['AIコーディング','AIモデル']);
  const restored=page.url(); await page.reload();
  await expect(page.locator('#view-announcement')).toContainText('122件');
  expect(page.url()).toBe(restored);
  await page.locator('#filter-toggle').click();
  for(const name of ['AIコーディング','AIモデル','OpenAI News','Claude Code Releases']) {
    await expect(page.getByRole('checkbox',{name,exact:true})).toBeChecked();
  }
  await expect(page.locator('#filter-from')).toHaveValue('2026-09-30');
  await expect(page.locator('#filter-to')).toHaveValue('2026-10-02');
  await page.getByRole('button',{name:/さらに表示/}).click();
  await page.getByRole('button',{name:/さらに表示/}).click();
  const share=await page.locator('.card').nth(110).getByRole('link',{name:'このサイト内で共有'}).getAttribute('href');
  const copy=await context.newPage(), errors=[];copy.on('pageerror',e=>errors.push(e.message));
  await copy.setViewportSize({width:320,height:800});await copy.goto(share);
  await expect(copy.locator('.search-results .card')).toHaveCount(122);
  await expect(copy.getByRole('heading',{name:'（E2E合成）Alpha 110',exact:true})).toBeFocused();
  await expect(copy.locator('#view-announcement')).toContainText('共有記事へ移動');
  await expect(copy.locator('#collection-health')).toBeHidden();await noOverflow(copy);
  await copy.reload();await expect(copy.getByRole('heading',{name:'（E2E合成）Alpha 110',exact:true})).toBeFocused();
  await copy.getByRole('button',{name:'検索語をクリア',exact:true}).click();
  expect(new URL(copy.url()).searchParams.has('q')).toBe(false);
  expect(new URL(copy.url()).searchParams.getAll('category')).toHaveLength(2);
  await copy.getByRole('button',{name:'すべての条件を解除'}).click();
  await expect(copy.locator('#view-heading')).toHaveText('2026年9月');
  await expect(copy.locator('#order-select')).toHaveValue('asc');
  expect(new URL(copy.url()).searchParams.has('category')).toBe(false);
  expect(errors).toEqual([]);await copy.close();
});

test('history: debounced typing has one boundary, confirmed filters restore with Back and Forward',async({page})=>{
  await page.route('**/samples/data/search-index.json',route=>route.fulfill({json:filterResults}));
  await page.goto('/?sample&month=2026-09&order=asc');await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  const before=await page.evaluate(()=>history.length),input=page.getByRole('searchbox');
  for(const word of ['A','Al','Alpha']) {
    await input.fill(word);
    await expect.poll(()=>new URL(page.url()).searchParams.get('q')).toBe(word);
  }
  expect(await page.evaluate(()=>history.length)).toBe(before+1);
  await input.press('Enter');
  await page.locator('#filter-toggle').click();
  await page.getByRole('checkbox',{name:'AIモデル',exact:true}).check();
  await expect(page.locator('#view-announcement')).toContainText('絞り込み結果: 1件');
  await page.goBack();await expect(page.locator('#view-heading')).toHaveText('検索結果');
  await expect(input).toHaveValue('Alpha');expect(new URL(page.url()).searchParams.has('category')).toBe(false);
  await page.goBack();await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  await expect(input).toHaveValue('');await expect(page.locator('#order-select')).toHaveValue('asc');
  await page.goForward();await expect(page.locator('#view-heading')).toHaveText('検索結果');
  await page.goForward();await expect(page.locator('#view-announcement')).toContainText('絞り込み結果: 1件');
  await expect(page.getByRole('checkbox',{name:'AIモデル',exact:true})).toBeChecked();
  expect(await page.evaluate(()=>history.length)).toBe(before+2);
});

test('project-page article URL opens a closed daily date and supports a keyboard share link',async({page,context})=>{
  // Serve the same files under a synthetic GitHub Pages project prefix without editing fixtures.
  await context.route('**/ai-watch/**',route=>{
    const url=new URL(route.request().url());url.pathname=url.pathname.replace(/^\/ai-watch/,'');
    return route.continue({url:url.href});
  });
  await page.goto('/ai-watch/?sample&month=2026-09&order=asc');
  await expect(page.locator('#view-heading')).toHaveText('2026年9月');
  const day=page.locator('.day').first();
  await expect(day).toHaveJSProperty('open',false);
  const share=day.locator('.share').first(),href=await share.getAttribute('href');
  const title=await day.locator('.card-title').first().textContent();
  expect(href).toMatch(/^\/ai-watch\/\?sample=/);
  const copy=await context.newPage(),errors=[];copy.on('pageerror',e=>errors.push(e.message));
  await copy.goto(href);await expect(copy.locator('.card-title').filter({hasText:title})).toBeFocused();
  const target=copy.locator('article').filter({has:copy.locator('.card-title').filter({hasText:title})});
  await expect(target).toBeVisible();
  expect(await target.evaluate(card=>card.closest('details').open)).toBe(true);
  await expect(copy.locator('#view-announcement')).toContainText('共有記事へ移動');
  await day.locator('summary').click();await share.focus();await page.keyboard.press('Enter');
  await expect(page.locator('.card-title').filter({hasText:title})).toBeFocused();
  expect(new URL(page.url()).hash).toBe(new URL(href,'https://local.example').hash);
  await noOverflow(page);expect(errors).toEqual([]);await copy.close();
});

test('restoration cancels IME and old fetches; invalid/missing links return to the current list',async({page})=>{
  let pending;
  await page.route('**/samples/data/search-index.json',route=>new Promise(resolve=>{pending={route,resolve};}));
  await page.goto('/?sample');await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  const input=page.getByRole('searchbox');await input.fill('Alpha');await input.press('Enter');
  await expect.poll(()=>Boolean(pending)).toBe(true);
  await input.dispatchEvent('compositionstart');await input.fill('変換中');
  await page.goBack();await expect(page.locator('#view-heading')).toHaveText('2026年10月');
  await pending.route.fulfill({json:filterResults});pending.resolve();
  await expect(input).toHaveValue('');await expect(page.locator('#view-announcement')).toContainText('日刊:');
  expect(new URL(page.url()).searchParams.has('q')).toBe(false);
  await page.goForward();await expect(page.locator('#view-heading')).toHaveText('検索結果');
  await expect(input).toHaveValue('Alpha');
  await page.unroute('**/samples/data/search-index.json');
  await page.route('**/samples/data/search-index.json',route=>route.fulfill({json:filterResults}));
  await page.goto('/?sample&month=bad&order=bad&q=Alpha&category=Unknown&from=2026-02-30#article-missing');
  await expect(page.locator('.search-results .card')).toHaveCount(50);
  await expect(page.locator('#url-notice')).toContainText('現在の一覧にありません');
  expect(new URL(page.url()).hash).toBe('');
  expect(new URL(page.url()).searchParams.get('q')).toBe('Alpha');
  expect(new URL(page.url()).searchParams.has('category')).toBe(false);
  await expect(page.locator('#load-retry')).toBeHidden();
});
