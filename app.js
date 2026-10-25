"use strict";
// 閲覧UI（news-watch の日刊表示を流用）。data/months.json と logs/YYYY/YYYY-MM.md を相対パスで読み取るだけ。
// 横断検索は data/search-index.json を初回検索時に1回だけ読み、ブラウザ内で絞り込む（外部APIは使わない）。
// 外部由来の文字列は textContent と検証済みURLのhref設定のみで描画する（innerHTML は使わない）。
// ?sample を付けると samples/ 以下のサンプルデータ（架空の記事）を表示する。

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const BASE = new URLSearchParams(location.search).has("sample") ? "samples/" : "";
const select = document.getElementById("month-select");
const orderSelect = document.getElementById("order-select");
const searchInput = document.getElementById("search-input");
const searchClear = document.getElementById("search-clear");
const notice = document.getElementById("notice");
const statusEl = document.getElementById("status");
const announcement = document.getElementById("view-announcement");
const retryButton = document.getElementById("load-retry");
const content = document.getElementById("content");
const filterPanel = document.getElementById("filter-panel");
const filterToggle = document.getElementById("filter-toggle");
const filterFrom = document.getElementById("filter-from");
const filterTo = document.getElementById("filter-to");
const filtersClear = document.getElementById("filters-clear");
const conditionsClear = document.getElementById("conditions-clear");
const optionsStatus = document.getElementById("filter-options-status");
const optionsRetry = document.getElementById("filter-options-retry");
const filterCheckboxes = { categories: [], feeds: [] };
let filterOptionsLoading = false;
let loadToken = 0; // 連続切替時に古い応答で上書きしない
let sortOrder = "desc"; // viewState.orderと同期する日刊の並び順
let current = null; // 表示中の月 { ym, days }。並び順変更時の再描画に使う
const SEARCH_PAGE_SIZE = 50; // 検索結果は50件ずつ表示する（「さらに表示」で追加）
const SEARCH_DELAY_MS = 250; // 入力が止まってから検索する（入力途中の再描画を抑える）
// URLで復元する閲覧条件。invalidDateInputだけは一時的な入力状態。
let viewState = { month: "", order: "desc", query: "", categories: [], feeds: [], from: "", to: "", invalidDateInput: false };
let articleTarget = "";
let editSession = "";
let searchEntries = null; // buildSearchEntries の結果（初回検索時に読み込み、以後は再利用）
let searchLoading = null; // 読み込み中の Promise（同時に複数回取得しない）
let searchTimer = 0;
let retryAction = null;
let activeRetry = null;
let composing = false;
let inputPending = false;

class DataError extends Error {}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== "") node.textContent = text;
  return node;
}

function setStatus(message, isError, retry = null) {
  statusEl.textContent = message;
  statusEl.className = isError ? "error" : "";
  statusEl.hidden = !message;
  retryAction = retry;
  retryButton.hidden = !retry && !activeRetry;
  retryButton.disabled = false;
  retryButton.setAttribute("aria-disabled", activeRetry ? "true" : "false");
  announce(message);
}

function announce(message) {
  if (announcement.textContent !== message) announcement.textContent = message;
}

function beginView(retry = null) {
  if (activeRetry !== retry) activeRetry = null;
  return ++loadToken;
}

function viewHeading(text) {
  const heading = el("h2", "", text);
  heading.id = "view-heading";
  heading.tabIndex = -1;
  return heading;
}

function loadError(label, error, retry) {
  const message = error instanceof DataError ? `${label}のデータ形式が不正です。再試行してください。`
    : `${label}を取得できませんでした。接続を確認して再試行してください。`;
  setStatus(message, true, retry);
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new DataError("invalid JSON");
  }
}

async function fetchText(path) {
  const res = await fetch(BASE + path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

function externalLink(text, url, className) {
  const a = el("a", className, text);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.setAttribute("aria-describedby", "new-tab-hint");
  return a;
}

function renderCard(item, withCategory, id = articleId(item.url)) {
  const card = el("article", "card");
  const url = safeUrl(item.url);
  if (id) card.id = id;

  const title = el(withCategory ? "h3" : "h5", "card-title");
  title.tabIndex = -1;
  if (url) title.appendChild(externalLink(item.title || url, url));
  else title.textContent = item.title || "（タイトルなし）";
  card.appendChild(title);

  // 「OpenAI News ・ openai.com ・ 公開 2026-10-01」。欠けている項目は表示しない。項目の途中では改行しない。
  const metaParts = [item.feed, item.source, item.published && `公開 ${item.published}`].filter(Boolean);
  if (metaParts.length) {
    const meta = el("p", "meta");
    metaParts.forEach((part, i) => {
      if (i) meta.appendChild(document.createTextNode(" ・ "));
      meta.appendChild(el("span", "meta-part", part));
    });
    card.appendChild(meta);
  }
  if (item.notes) card.appendChild(el("p", "notes", `リリースノートの項目数: ${item.notes}`)); // 機械的な集計
  // 主な変更: 公式リリースノートの記載を原文のまま（機械的に選択）。各リリースのリリースノートへのリンクも出す。
  const highlights = Array.isArray(item.highlights) ? item.highlights : [];
  if (highlights.length) {
    card.appendChild(el("p", "notes", "主な変更（公式リリースノートから機械的に抜粋）"));
    const list = el("ul", "highlights");
    for (const h of highlights) list.appendChild(el("li", "", h));
    card.appendChild(list);
  }
  const releases = (Array.isArray(item.releases) ? item.releases : [])
    .map((r) => ({ label: r.label, url: safeUrl(r.url) })).filter((r) => r.url);
  if (releases.length) {
    const links = el("p", "notes releases", "リリースノート: ");
    releases.forEach((r, i) => {
      if (i) links.appendChild(document.createTextNode(" ・ "));
      links.appendChild(externalLink(r.label, r.url));
    });
    card.appendChild(links);
  }

  // リンクと補助情報はカード下部にまとめ、行内のカードで位置を揃える。
  const bottom = el("div", "card-bottom");
  if (url) bottom.appendChild(externalLink("元記事を開く →", url, "open"));
  if (id) {
    const share = el("a", "share", "このサイト内で共有");
    share.href = writeViewURL(location.href, viewState, id);
    share.addEventListener("click", event => {
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      articleTarget = id;
      syncURL("push");
      moveToArticle();
    });
    bottom.appendChild(share);
  }
  const parts = [];
  if (item.retrieved) parts.push(`取得日: ${item.retrieved}`);
  if (withCategory && item.category) parts.push(`カテゴリ: ${item.category}`); // 検索結果のみ（日刊表示では見出し）
  if (parts.length) {
    const foot = el("p", "foot", parts.join(" / "));
    foot.title = parts.join(" / "); // 1行表示で省略された場合に全文を確認できる
    bottom.appendChild(foot);
  }
  if (bottom.childNodes.length) card.appendChild(bottom);
  return card;
}

// 日付順に並べ替えた新しい配列を返す（元の配列は変更しない）。
function sortDays(days, order) {
  const sorted = [...days].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return order === "asc" ? sorted : sorted.reverse();
}

function countItems(categories) {
  return categories.reduce((n, c) => n + c.items.length, 0);
}

function renderMonth(ym, days, order) {
  const total = days.reduce((n, d) => n + countItems(d.categories), 0);
  // 初期展開するのは、並び順に関係なくその月の最新日のみ
  const latest = days.reduce((max, d) => (d.date > max ? d.date : max), "");
  const frag = document.createDocumentFragment();

  const head = el("div", "month-head");
  head.appendChild(viewHeading(monthLabel(ym)));
  head.appendChild(el("span", "count", `${total}件`));
  frag.appendChild(head);

  // Assign occurrences in log order, before sorting, so changing order preserves IDs.
  const ids = new Map(), counts = new Map();
  for (const day of days) for (const category of day.categories) for (const item of category.items) {
    const base = articleId(item.url);
    const n = (counts.get(base) || 0) + 1;
    counts.set(base, n);
    ids.set(item, base ? base + (n > 1 ? `~${n}` : "") : "");
  }
  for (const day of sortDays(days, order)) {
    const section = el("details", "day");
    section.open = day.date === latest;
    const summary = el("summary", "day-summary");
    const dayHeading = el("h3", "day-title", dateLabel(day.date));
    dayHeading.appendChild(el("span", "count", `${countItems(day.categories)}件`));
    if (latest && day.date === latest) dayHeading.appendChild(el("span", "latest", "最新"));
    summary.appendChild(dayHeading);
    section.appendChild(summary);
    for (const category of day.categories) {
      const block = el("div", "category");
      const h = el("h4", "category-title", category.name);
      h.appendChild(el("span", "count", `${category.items.length}件`));
      block.appendChild(h);
      const cards = el("div", "cards"); // カテゴリごとに独立したGrid
      for (const item of category.items) cards.appendChild(renderCard(item, false, ids.get(item)));
      block.appendChild(cards);
      section.appendChild(block);
    }
    frag.appendChild(section);
  }
  content.replaceChildren(frag);
  announce(`日刊: ${monthLabel(ym)}、${total}件。${order === "asc" ? "古い順" : "新しい順"}。`);
  moveToArticle();
}

async function showMonth(ym, retry = null) {
  if (resultsMode()) return;
  const token = beginView(retry);
  current = null; // 読み込み中・失敗時に旧月を並び順変更で再描画しない
  content.replaceChildren();
  setStatus("読み込み中...");
  let text;
  try {
    text = await fetchText(`logs/${ym.slice(0, 4)}/${ym}.md`);
  } catch (e) {
    if (token === loadToken) loadError(`${monthLabel(ym)}のログ`, e, request => showMonth(ym, request));
    return;
  }
  if (token !== loadToken) return;
  let days;
  try {
    // ログは寛容に解析するが、HTMLや無関係なテキストを正常な0件とは扱わない。
    if (text.trim() && !/^#{1,4} /m.test(text)) throw new DataError("not a Markdown log");
    days = parseLog(text);
  } catch (e) {
    loadError(`${monthLabel(ym)}のログ`, new DataError("invalid log"), request => showMonth(ym, request));
    return;
  }
  if (days.length === 0) {
    setStatus(`${monthLabel(ym)}に表示できる記事がありません。`);
    moveToArticle();
    return;
  }
  setStatus("");
  current = { ym, days };
  renderMonth(ym, days, sortOrder);
}

async function loadMonths(retry = null) {
  const token = beginView(retry);
  setStatus("月の一覧を読み込み中...");
  let months;
  try {
    const text = await fetchText("data/months.json");
    if (token !== loadToken) return;
    const data = parseJson(text);
    if (!Array.isArray(data)) throw new DataError("not an array");
    months = data.filter((m) => typeof m === "string" && MONTH_RE.test(m));
    if (data.length && !months.length) throw new DataError("no valid months");
  } catch (e) {
    if (token === loadToken) loadError("月の一覧（data/months.json）", e, loadMonths);
    return;
  }
  if (months.length === 0) {
    if (token === loadToken) setStatus("表示できるログがまだありません。毎朝の収集後に表示されます。");
    return;
  }
  if (!select.options.length) { // 並行して呼ばれた別の読み込みが作成済みなら作り直さない
    for (const ym of months) {
      const opt = el("option", "", monthLabel(ym));
      opt.value = ym;
      select.appendChild(opt);
    }
  }
  if (!months.includes(viewState.month)) {
    if (viewState.month) urlNotice("指定された月がないため、最新月を表示します。");
    viewState = { ...viewState, month: months[0] };
  }
  select.value = viewState.month;
  syncURL("replace");
  syncControls();
  if (token === loadToken) {
    if (resultsMode()) await showSearch(retry);
    else await showMonth(select.value, retry);
  } // months.json は新しい順。先頭=最新月
}

function resultsMode() {
  return Boolean(viewState.query || hasArticleFilters(viewState));
}

function conditionsSummary() {
  const parts = [];
  if (viewState.query) parts.push(`検索語「${viewState.query}」`);
  if (viewState.categories.length) parts.push(`カテゴリ: ${viewState.categories.join("、")}`);
  if (viewState.feeds.length) parts.push(`情報源: ${viewState.feeds.join("、")}`);
  if (viewState.from || viewState.to) parts.push(`取得日: ${viewState.from || "指定なし"} 〜 ${viewState.to || "指定なし"}（両端を含む）`);
  if (viewState.invalidDateInput) parts.push("取得日: 入力途中の年月日を確認してください");
  return parts.join(" ／ ");
}

// 閲覧条件の更新はこの経路へ集約する。データ取得やURL保存は状態に含めない。
function updateViewState(patch, historyMode = "push") {
  const next = { ...viewState, ...patch };
  if (JSON.stringify(next) === JSON.stringify(viewState) && !inputPending) return;
  viewState = next;
  urlNotice("");
  articleTarget = "";
  sortOrder = next.order;
  if (next.month) select.value = next.month;
  orderSelect.value = next.order;
  for (const [key, input] of [["from", filterFrom], ["to", filterTo]]) {
    if (key in patch && input.value !== next[key]) input.value = next[key];
  }
  syncControls();
  syncURL(historyMode);
  if (Object.keys(patch).length === 1 && "order" in patch && !current && !resultsMode()) return;
  if (composing) {
    inputPending = true;
    beginView();
    setStatus("");
    return; // フィルターを変えてもIME途中の検索結果を通知しない
  }
  inputPending = false;
  showDaily();
}

function applyFilterChange(patch, historyMode = "push") {
  clearTimeout(searchTimer);
  updateViewState({ ...patch, query: composing ? viewState.query : normalizedQuery(searchInput.value) }, historyMode);
}

function clearFilterValues() {
  filterFrom.value = "";
  filterTo.value = ""; // 空のvalueでもnative dateの入力途中状態をリセットする
  return { categories: [], feeds: [], from: "", to: "", invalidDateInput: false };
}

// 全期間モードでは月・日刊の並び順を無効にし、条件と解除方法を明示する。
function syncControls() {
  const off = resultsMode() || !select.options.length;
  select.disabled = off;
  orderSelect.disabled = off;
  searchClear.disabled = !searchInput.value;
  const active = resultsMode();
  document.getElementById("mode-hint").hidden = !active;
  const summary = document.getElementById("active-conditions");
  summary.textContent = active ? `適用中の条件: ${conditionsSummary()}` : "";
  summary.hidden = !active;
  conditionsClear.hidden = !active;
  filtersClear.disabled = !hasArticleFilters(viewState);
  const invalid = Boolean(validateFilterDates(viewState));
  filterFrom.setAttribute("aria-invalid", String(invalid));
  filterTo.setAttribute("aria-invalid", String(invalid));
  for (const key of ["categories", "feeds"]) {
    for (const checkbox of filterCheckboxes[key]) checkbox.checked = viewState[key].includes(checkbox.value);
  }
}

// 検索中なら検索結果、そうでなければ選択中の月（取得済みなら再取得せず再描画）。
function showDaily() {
  if (resultsMode()) {
    showSearch();
  } else if (current && current.ym === viewState.month) {
    beginView(); // 検索の読み込み中の応答で上書きしない
    setStatus("");
    renderMonth(current.ym, current.days, sortOrder);
  } else if (select.options.length) {
    if (![...select.options].some(o => o.value === viewState.month)) { loadMonths(); return; }
    showMonth(viewState.month);
  } else {
    loadMonths();
  }
}

// ---- 横断検索 -----------------------------------------------------------------
function loadSearchEntries() {
  if (!searchLoading) {
    searchLoading = fetchText("data/search-index.json")
      .then((text) => {
        const data = parseJson(text);
        if (!Array.isArray(data)) throw new DataError("not an array");
        const entries = buildSearchEntries(data);
        if (data.length && !entries.length) throw new DataError("no valid articles");
        searchEntries = entries;
        populateFilterOptions(entries);
      })
      .catch((e) => { searchLoading = null; throw e; }); // 失敗時は次の検索で再試行する
  }
  return searchLoading;
}

function populateFilterOptions(entries) {
  const options = articleFilterOptions(entries);
  for (const [key, id] of [["categories", "filter-categories"], ["feeds", "filter-feeds"]]) {
    const list = document.getElementById(id);
    filterCheckboxes[key] = options[key].map(value => {
      const label = el("label");
      const checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.value = value;
      checkbox.checked = viewState[key].includes(value);
      checkbox.addEventListener("change", () => {
        const selected = viewState[key].filter(v => v !== value);
        if (checkbox.checked) selected.push(value);
        applyFilterChange({ [key]: selected });
      });
      label.appendChild(checkbox);
      label.appendChild(el("span", "", value));
      list.appendChild(label);
      return checkbox;
    });
    if (!options[key].length) list.appendChild(el("p", "meta", "保存済み検索データには候補がありません。"));
  }
  document.getElementById("filter-category-field").disabled = false;
  document.getElementById("filter-feed-field").disabled = false;
  optionsStatus.textContent = "";
  if (document.activeElement === optionsRetry) (filterCheckboxes.categories[0] || filterToggle).focus();
  optionsRetry.hidden = true;
}

async function loadFilterOptions() {
  if (searchEntries !== null || filterOptionsLoading) return;
  const token = loadToken;
  filterOptionsLoading = true;
  optionsStatus.textContent = "カテゴリ・情報源の候補を読み込み中…（日刊の閲覧は続けられます）";
  optionsRetry.setAttribute("aria-disabled", "true");
  try {
    await loadSearchEntries(); // 初回検索・条件指定と同じPromise/キャッシュを共有する
  } catch (e) {
    optionsStatus.textContent = e instanceof DataError ? "候補データの形式が不正です。候補を再試行してください。"
      : "候補を取得できませんでした。候補を再試行してください。";
    optionsRetry.hidden = false;
    if (!resultsMode() && token === loadToken && filterPanel.open) announce(optionsStatus.textContent);
  } finally {
    filterOptionsLoading = false;
    optionsRetry.setAttribute("aria-disabled", "false");
  }
}

async function showSearch(retry = null) {
  const token = beginView(retry);
  let state = viewState;
  const error = validateFilterDates(state);
  if (error) {
    content.replaceChildren();
    setStatus(error, true);
    return;
  }
  if (searchEntries === null) {
    content.replaceChildren();
    setStatus("検索データを読み込み中...");
    try {
      await loadSearchEntries();
    } catch (e) {
      if (token === loadToken) loadError("検索データ（data/search-index.json）", e, showSearch);
      return;
    }
    if (token !== loadToken) return;
  }
  // Unknown selections can only be checked against the successfully loaded index.
  const options = articleFilterOptions(searchEntries);
  const categories = state.categories.filter(v => options.categories.includes(v));
  const feeds = state.feeds.filter(v => options.feeds.includes(v));
  if (categories.length !== state.categories.length || feeds.length !== state.feeds.length) {
    viewState = state = { ...state, categories, feeds };
    urlNotice("保存済み検索データにないカテゴリ・情報源を解除しました。");
    syncControls();
    syncURL("replace");
    if (!resultsMode()) { showDaily(); return; }
  }
  renderSearch(state, filterArticles(searchEntries, state));
}

function renderSearch(state, results) {
  const token = loadToken;
  const filtered = hasArticleFilters(state);
  const resultLabel = filtered ? "絞り込み結果" : `「${state.query}」の検索結果`;
  setStatus("");
  const frag = document.createDocumentFragment();
  const head = el("div", "month-head");
  head.appendChild(viewHeading(filtered ? "絞り込み結果" : "検索結果"));
  head.appendChild(el("span", "count", `${results.length}件`));
  frag.appendChild(head);
  frag.appendChild(el("p", "search-summary", filtered ? "保存済み検索データの全期間から絞り込み（取得日の新しい順）"
    : `「${state.query}」を全期間の日刊ログから検索（取得日の新しい順）`));
  if (results.length === 0) {
    frag.appendChild(el("p", "search-empty",
      filtered ? "条件に一致する記事はありません。検索語やフィルターを見直すか、すべての条件を解除してください。"
        : "該当する記事はありません。キーワードを減らすか、別の表記（略称・正式名称など）でお試しください。"));
    content.replaceChildren(frag);
    announce(`${resultLabel}: 0件。`);
    moveToArticle();
    return;
  }
  const cards = el("div", "cards search-results");
  frag.appendChild(cards);
  const more = el("button", "more");
  more.type = "button";
  let shown = 0;
  const showMore = (activated = false) => {
    if (activated && (token !== loadToken || shown >= results.length)) return;
    const next = results.slice(shown, shown + SEARCH_PAGE_SIZE);
    let firstAdded;
    for (const item of next) {
      const card = renderCard(item, true);
      if (!firstAdded) firstAdded = card.firstChild;
      cards.appendChild(card);
    }
    shown += next.length;
    // 最後の追加で消えるボタンから、新しく追加した記事へ移る。通常の検索では移動しない。
    if (activated && shown >= results.length && document.activeElement === more) firstAdded.focus();
    more.hidden = shown >= results.length;
    more.textContent = `さらに表示（残り${results.length - shown}件）`;
    if (activated) announce(`${results.length}件中${shown}件を表示しました。`);
  };
  more.addEventListener("click", () => showMore(true));
  showMore();
  const targetIndex = articleTarget ? results.findIndex(item => articleId(item.url) === articleTarget) : -1;
  while (targetIndex >= shown) showMore();
  frag.appendChild(more);
  content.replaceChildren(frag);
  announce(`${resultLabel}: ${results.length}件。${shown}件を表示しています。`);
  moveToArticle();
}

function normalizedQuery(value) {
  return normalizeViewQuery(value);
}

function applySearch(value, historyMode = "push") {
  clearTimeout(searchTimer);
  const query = normalizedQuery(value);
  if (query === viewState.query && !inputPending) return; // 空白の追加など、結果が変わらない入力では再描画しない
  updateViewState({ query }, historyMode); // 検索語だけ空にしてもフィルターがあれば全期間モードを維持
}

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => applySearch(searchInput.value, "query"), SEARCH_DELAY_MS);
}

function invalidateInput() {
  clearTimeout(searchTimer);
  // debounce/IME待ちの間にも旧応答の描画・通知・再試行のフォーカス移動を無効にする。
  if (composing || normalizedQuery(searchInput.value) !== viewState.query) {
    inputPending = true;
    beginView();
    setStatus("");
  }
}

function init() {
  if (BASE) notice.hidden = false;
  filterPanel.addEventListener("toggle", () => { if (filterPanel.open) loadFilterOptions(); });
  optionsRetry.addEventListener("click", loadFilterOptions);
  const changeDates = () => applyFilterChange({ from: filterFrom.value, to: filterTo.value,
    invalidDateInput: Boolean(filterFrom.validity?.badInput || filterTo.validity?.badInput) }, "dates");
  filterFrom.addEventListener("input", changeDates);
  filterTo.addEventListener("input", changeDates);
  for (const input of [filterFrom, filterTo, searchInput]) input.addEventListener("change", () => { editSession = ""; });
  filtersClear.addEventListener("click", () => {
    applyFilterChange(clearFilterValues());
    filterToggle.focus();
  });
  conditionsClear.addEventListener("click", () => {
    clearTimeout(searchTimer);
    searchInput.value = "";
    composing = false;
    updateViewState({ ...clearFilterValues(), query: "" });
    searchInput.focus();
  });
  retryButton.addEventListener("click", async () => {
    if (!retryAction || activeRetry) return;
    const retry = retryAction;
    const request = {};
    activeRetry = request;
    retryAction = null; // 連打・キーボード連続操作でも同じ再試行を重ねない
    // 待機中も要素を残す。native disabledによるフォーカス消失を避け、ハンドラで連打を防ぐ。
    try {
      await retry(request);
    } finally {
      if (activeRetry === request) {
        activeRetry = null;
        if (!retryAction && document.activeElement === retryButton) {
          (document.getElementById("view-heading") || statusEl).focus();
        }
        retryButton.hidden = !retryAction;
        retryButton.setAttribute("aria-disabled", "false");
      }
    }
  });
  searchInput.addEventListener("input", (e) => {
    syncControls();
    if (e.isComposing) composing = true;
    invalidateInput();
    if (composing) return; // 日本語入力の変換中は検索しない（確定時に compositionend で検索）
    scheduleSearch();
  });
  searchInput.addEventListener("compositionstart", () => { composing = true; invalidateInput(); });
  searchInput.addEventListener("compositionend", () => { composing = false; scheduleSearch(); });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing && !composing) {
      applySearch(searchInput.value, editSession === "query" ? "replace" : "push");
      editSession = "";
    }
  });
  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    composing = false;
    syncControls();
    applySearch("");
    searchInput.focus();
  });
  select.addEventListener("change", () => updateViewState({ month: select.value }));
  orderSelect.addEventListener("change", () => {
    updateViewState({ order: orderSelect.value === "asc" ? "asc" : "desc" });
  });
  window.addEventListener("popstate", () => restoreURL());
  restoreURL(true);
}

function urlNotice(message, append = true) {
  const node = document.getElementById("url-notice");
  const previous = append && message && !node.hidden ? node.textContent : "";
  node.textContent = previous && !previous.includes(message) ? previous + " " + message : message || "";
  node.hidden = !node.textContent;
}

function syncURL(mode) {
  if (validateFilterDates(viewState)) return; // Keep the last valid URL during incomplete date input.
  const url = writeViewURL(location.href, viewState, articleTarget);
  const previous = location.pathname + location.search + location.hash;
  const editing = mode === "query" || mode === "dates";
  const replace = mode === "replace" || (editing && editSession === mode);
  if (url !== previous) history[replace ? "replaceState" : "pushState"](null, "", url);
  editSession = editing ? mode : "";
}

function restoreURL(initial = false) {
  const parsed = readViewURL(location.href);
  if (parsed.sample !== Boolean(BASE)) { location.reload(); return; }
  clearTimeout(searchTimer);
  composing = inputPending = false;
  editSession = "";
  beginView();
  viewState = parsed.state;
  articleTarget = parsed.article;
  sortOrder = viewState.order;
  searchInput.value = viewState.query;
  filterFrom.value = viewState.from;
  filterTo.value = viewState.to;
  orderSelect.value = sortOrder;
  if (viewState.month) select.value = viewState.month;
  urlNotice(parsed.warnings.length ? "URLの不正・長すぎる条件を補正しました（" + parsed.warnings.join("、") + "）。" : "", false);
  syncControls();
  syncURL("replace");
  if (initial) loadMonths();
  else showDaily();
}

function moveToArticle() {
  if (!articleTarget) return;
  const card = document.getElementById(articleTarget);
  if (!card || !content.contains(card)) {
    urlNotice("指定された記事は現在の一覧にありません。条件や検索データの範囲を確認してください。");
    articleTarget = "";
    syncURL("replace");
    announce(document.getElementById("url-notice").textContent);
    return;
  }
  const day = card.closest("details");
  if (day) day.open = true;
  card.firstChild.focus({ preventScroll: true });
  card.scrollIntoView({ block: "center" });
  announce("共有記事へ移動しました: " + card.firstChild.textContent);
}

init();
