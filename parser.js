"use strict";
// logs/YYYY/YYYY-MM.md のMarkdownを、表示用のデータ構造へ変換する（DOM操作なし。news-watch から流用）。
//
// 戻り値: [{ date, categories: [{ name, items: [{ title, url, source, feed, notes, highlights: [文字列],
//           releases: [{ label, url }], published, retrieved }] }] }]   ※ファイル中の出現順
// notes・highlights・releases はリリース（公式リリースノートの項目数・抜粋・各リリースへのリンク）のみ。
// 見出し階層: "## 日付" > "### カテゴリ" > "#### 記事タイトル"。
// 項目の欠落や未知の行があっても例外にせず、可能な範囲で読み取る。

const FIELD_KEYS = {
  url: "url",
  source: "source",
  feed: "feed",
  notes: "notes",
  published: "published",
  retrieved: "retrieved",
};
const FIELD_RE = /^-\s*([A-Za-z]+):\s*(.*)$/;
const UNCATEGORIZED = "（未分類）";

function parseLog(markdown) {
  const days = [];
  let day = null;
  let category = null;
  let item = null;

  const ensureCategory = () => {
    if (!day) {
      day = { date: "", categories: [] };
      days.push(day);
    }
    if (!category) {
      category = { name: UNCATEGORIZED, items: [] };
      day.categories.push(category);
    }
  };

  for (const raw of String(markdown || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (line === "") continue;

    if (line.startsWith("#### ")) {
      ensureCategory();
      item = {
        title: line.slice(5).trim(), url: "", source: "", feed: "", notes: "", highlights: [], releases: [],
        published: "", retrieved: "",
      };
      category.items.push(item);
    } else if (line.startsWith("### ")) {
      ensureCategory();
      category = { name: line.slice(4).trim() || UNCATEGORIZED, items: [] };
      day.categories.push(category);
      item = null;
    } else if (line.startsWith("## ")) {
      day = { date: line.slice(3).trim(), categories: [] };
      days.push(day);
      category = null;
      item = null;
    } else if (item) {
      const m = FIELD_RE.exec(line);
      const name = m && m[1].toLowerCase();
      if (name === "highlight") {
        item.highlights.push(m[2].trim());
      } else if (name === "release") {
        const r = /^(.*\S)\s+(\S+)$/.exec(m[2].trim()); // "v1.2.3 https://..."
        if (r) item.releases.push({ label: r[1], url: r[2] });
      } else if (FIELD_KEYS[name]) {
        item[FIELD_KEYS[name]] = m[2].trim();
      }
    }
  }

  // 記事のないカテゴリ・日付は捨てる
  for (const d of days) d.categories = d.categories.filter((c) => c.items.length > 0);
  return days.filter((d) => d.categories.length > 0);
}

// http/https のみ許可する。不正・欠落なら null。
function safeUrl(value) {
  try {
    const u = new URL(String(value || "").trim());
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch (e) {
    return null;
  }
}

// "2026-10" -> "2026年10月"（先頭ゼロなし）。形式が不正なら null。
function monthLabel(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  return m ? `${m[1]}年${Number(m[2])}月` : null;
}

// "2026-10-01" -> "2026年10月1日"。解釈できなければ元の文字列。
function dateLabel(ymd) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  return m ? `${m[1]}年${Number(m[2])}月${Number(m[3])}日` : ymd || "日付不明";
}

// ---- 日刊ログの横断検索（data/search-index.json。scripts/search_index.py が生成） -------------
// 全角英数・半角カナなどを NFKC で揃え、英字は小文字にして比較する。
function normalizeText(text) {
  return String(text || "").normalize("NFKC").toLowerCase();
}

// 空白（全角空白を含む）で区切ったキーワード。AND検索に使う。
function splitKeywords(query) {
  return normalizeText(query).split(/\s+/).filter(Boolean);
}

const textOf = (v) => (typeof v === "string" ? v : "");

// インデックスの記事に検索用の文字列を付け、取得日の新しい順に並べる。URLが不正な記事・重複URLは除く。
function buildSearchEntries(data) {
  if (!Array.isArray(data)) return [];
  const seen = new Set();
  const entries = [];
  for (const a of data) {
    if (!a || typeof a !== "object") continue;
    const url = safeUrl(a.url);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    const item = {
      title: textOf(a.title), url, source: textOf(a.source), feed: textOf(a.feed), published: textOf(a.published),
      retrieved: textOf(a.retrieved), category: textOf(a.category),
      notes: textOf(a.notes),
      highlights: Array.isArray(a.highlights) ? a.highlights.filter((h) => typeof h === "string") : [],
      releases: (Array.isArray(a.releases) ? a.releases : [])
        .filter((r) => r && typeof r === "object")
        .map((r) => ({ label: textOf(r.label).trim(), url: safeUrl(textOf(r.url)) }))
        .filter((r) => r.label && r.url),
    };
    // 検索対象: タイトル・カテゴリ・情報源・配信元・リリースの抜粋と個別バージョン名。
    // 改行で区切り、項目をまたいで一致しないようにする。
    item.haystack = normalizeText([item.title, item.category, item.source, item.feed, ...item.highlights,
      ...item.releases.map((r) => r.label)].join("\n"));
    entries.push(item);
  }
  // 安定ソートのため、同じ取得日はインデックスの順（ログの出現順）を保つ
  return entries.sort((x, y) => (x.retrieved < y.retrieved ? 1 : x.retrieved > y.retrieved ? -1 : 0));
}

// すべてのキーワードを含む記事（部分一致・AND）。キーワードが無ければ空配列。
function searchArticles(entries, query) {
  const words = splitKeywords(query);
  if (words.length === 0) return [];
  return entries.filter((e) => words.every((w) => e.haystack.includes(w)));
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    parseLog, safeUrl, monthLabel, dateLabel, normalizeText, splitKeywords, buildSearchEntries, searchArticles,
  };
}
