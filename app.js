"use strict";
// 閲覧UI（news-watch の日刊表示を流用）。data/months.json と logs/YYYY/YYYY-MM.md を相対パスで読み取るだけ。
// 横断検索は data/search-index.json を初回検索時に1回だけ読み、ブラウザ内で絞り込む（外部APIは使わない）。
// 外部由来の文字列は textContent と検証済みURLのhref設定のみで描画する（innerHTML は使わない）。
// ?sample を付けると samples/ 以下のサンプルデータ（架空の記事）を表示する。

const MONTH_RE = /^\d{4}-\d{2}$/;
const BASE = new URLSearchParams(location.search).has("sample") ? "samples/" : "";
const select = document.getElementById("month-select");
const orderSelect = document.getElementById("order-select");
const searchInput = document.getElementById("search-input");
const searchClear = document.getElementById("search-clear");
const notice = document.getElementById("notice");
const statusEl = document.getElementById("status");
const content = document.getElementById("content");
let loadToken = 0; // 連続切替時に古い応答で上書きしない
let sortOrder = "desc"; // "desc"=新しい順 / "asc"=古い順（月を切り替えても維持。永続化はしない）
let current = null; // 表示中の月 { ym, days }。並び順変更時の再描画に使う
const SEARCH_PAGE_SIZE = 50; // 検索結果は50件ずつ表示する（「さらに表示」で追加）
const SEARCH_DELAY_MS = 250; // 入力が止まってから検索する（入力途中の再描画を抑える）
let searchQuery = ""; // 検索中のキーワード（空なら通常の日刊表示）
let searchEntries = null; // buildSearchEntries の結果（初回検索時に読み込み、以後は再利用）
let searchLoading = null; // 読み込み中の Promise（同時に複数回取得しない）
let searchTimer = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== "") node.textContent = text;
  return node;
}

function setStatus(message, isError) {
  statusEl.textContent = message;
  statusEl.className = isError ? "error" : "";
  statusEl.hidden = !message;
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
  return a;
}

function renderCard(item, withCategory) {
  const card = el("article", "card");
  const url = safeUrl(item.url);

  const title = el("h5", "card-title");
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
  head.appendChild(el("h2", "", monthLabel(ym)));
  head.appendChild(el("span", "count", `${total}件`));
  frag.appendChild(head);

  for (const day of sortDays(days, order)) {
    const section = el("details", "day");
    section.open = day.date === latest;
    const summary = el("summary", "day-summary");
    summary.appendChild(el("span", "day-title", dateLabel(day.date)));
    summary.appendChild(el("span", "count", `${countItems(day.categories)}件`));
    if (latest && day.date === latest) summary.appendChild(el("span", "latest", "最新"));
    section.appendChild(summary);
    for (const category of day.categories) {
      const block = el("div", "category");
      const h = el("h4", "category-title", category.name);
      h.appendChild(el("span", "count", `${category.items.length}件`));
      block.appendChild(h);
      const cards = el("div", "cards"); // カテゴリごとに独立したGrid
      for (const item of category.items) cards.appendChild(renderCard(item, false));
      block.appendChild(cards);
      section.appendChild(block);
    }
    frag.appendChild(section);
  }
  content.replaceChildren(frag);
}

async function showMonth(ym) {
  if (searchQuery) return;
  const token = ++loadToken;
  current = null; // 読み込み中・失敗時に旧月を並び順変更で再描画しない
  content.replaceChildren();
  setStatus("読み込み中...");
  let text;
  try {
    text = await fetchText(`logs/${ym.slice(0, 4)}/${ym}.md`);
  } catch (e) {
    if (token === loadToken) setStatus(`${monthLabel(ym)}のログを取得できませんでした。`, true);
    return;
  }
  if (token !== loadToken) return;
  let days;
  try {
    days = parseLog(text);
  } catch (e) {
    setStatus(`${monthLabel(ym)}のログを解析できませんでした。`, true);
    return;
  }
  if (days.length === 0) {
    setStatus(`${monthLabel(ym)}に表示できる記事がありません。`);
    return;
  }
  setStatus("");
  current = { ym, days };
  renderMonth(ym, days, sortOrder);
}

async function loadMonths() {
  const token = ++loadToken;
  let months;
  try {
    const data = JSON.parse(await fetchText("data/months.json"));
    if (!Array.isArray(data)) throw new Error("not an array");
    months = data.filter((m) => typeof m === "string" && MONTH_RE.test(m));
  } catch (e) {
    if (token === loadToken) setStatus("月の一覧（data/months.json）を取得できませんでした。", true);
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
  syncControls();
  if (token === loadToken && !searchQuery) showMonth(select.value); // months.json は新しい順。先頭=最新月
}

// 検索中は月の選択・並び順を無効にする（検索は全期間・新しい順）。
function syncControls() {
  const off = Boolean(searchQuery) || !select.options.length;
  select.disabled = off;
  orderSelect.disabled = off;
  searchClear.disabled = !searchInput.value;
}

// 検索中なら検索結果、そうでなければ選択中の月（取得済みなら再取得せず再描画）。
function showDaily() {
  if (searchQuery) {
    showSearch();
  } else if (current) {
    ++loadToken; // 検索の読み込み中の応答で上書きしない
    setStatus("");
    renderMonth(current.ym, current.days, sortOrder);
  } else if (select.value) {
    showMonth(select.value);
  } else {
    loadMonths();
  }
}

// ---- 横断検索 -----------------------------------------------------------------
function loadSearchEntries() {
  if (!searchLoading) {
    searchLoading = fetchText("data/search-index.json")
      .then((text) => { searchEntries = buildSearchEntries(JSON.parse(text)); })
      .catch((e) => { searchLoading = null; throw e; }); // 失敗時は次の検索で再試行する
  }
  return searchLoading;
}

async function showSearch() {
  const token = ++loadToken;
  const query = searchQuery;
  if (searchEntries === null) {
    content.replaceChildren();
    setStatus("検索データを読み込み中...");
    try {
      await loadSearchEntries();
    } catch (e) {
      if (token === loadToken) setStatus("検索データ（data/search-index.json）を取得できませんでした。", true);
      return;
    }
    if (token !== loadToken) return;
  }
  renderSearch(query, searchArticles(searchEntries, query));
}

function renderSearch(query, results) {
  setStatus("");
  const frag = document.createDocumentFragment();
  const head = el("div", "month-head");
  head.appendChild(el("h2", "", "検索結果"));
  head.appendChild(el("span", "count", `${results.length}件`));
  frag.appendChild(head);
  frag.appendChild(el("p", "search-summary", `「${query}」を全期間の日刊ログから検索（取得日の新しい順）`));
  if (results.length === 0) {
    frag.appendChild(el("p", "search-empty",
      "該当する記事はありません。キーワードを減らすか、別の表記（略称・正式名称など）でお試しください。"));
    content.replaceChildren(frag);
    return;
  }
  const cards = el("div", "cards search-results");
  frag.appendChild(cards);
  const more = el("button", "more");
  more.type = "button";
  let shown = 0;
  const showMore = () => {
    const next = results.slice(shown, shown + SEARCH_PAGE_SIZE);
    for (const item of next) cards.appendChild(renderCard(item, true));
    shown += next.length;
    more.hidden = shown >= results.length;
    more.textContent = `さらに表示（残り${results.length - shown}件）`;
  };
  more.addEventListener("click", showMore);
  showMore();
  frag.appendChild(more);
  content.replaceChildren(frag);
}

function applySearch(value) {
  clearTimeout(searchTimer);
  const query = value.trim().replace(/\s+/g, " ");
  if (query === searchQuery) return; // 空白の追加など、結果が変わらない入力では再描画しない
  searchQuery = query;
  syncControls();
  showDaily(); // 空欄に戻したら通常の日刊表示へ
}

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => applySearch(searchInput.value), SEARCH_DELAY_MS);
}

function init() {
  if (BASE) notice.hidden = false;
  searchInput.addEventListener("input", (e) => {
    syncControls();
    if (e.isComposing) return; // 日本語入力の変換中は検索しない（確定時に compositionend で検索）
    scheduleSearch();
  });
  searchInput.addEventListener("compositionend", scheduleSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) applySearch(searchInput.value);
  });
  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    applySearch("");
    searchInput.focus();
  });
  select.addEventListener("change", () => showMonth(select.value));
  orderSelect.addEventListener("change", () => {
    sortOrder = orderSelect.value === "asc" ? "asc" : "desc";
    if (current && !searchQuery) renderMonth(current.ym, current.days, sortOrder); // 再取得せず再描画
  });
  loadMonths();
}

init();
