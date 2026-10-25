"use strict";
// Pure URL boundary. No DOM, network, or history side effects.
const urlParser = typeof module !== "undefined" && module.exports ? require("./parser.js")
  : { safeUrl, validFilterDate, validateFilterDates };
const VIEW_LIMITS = { query: 500, option: 200, selections: 50, article: 32768 };

function normalizeViewQuery(value) {
  const query = value.trim().replace(/\s+/g, " ").slice(0, VIEW_LIMITS.query);
  return /[\uD800-\uDBFF]$/.test(query) ? query.slice(0, -1) : query;
}

function readViewURL(value, options = null) {
  const url = new URL(value, "https://local.invalid/");
  const params = url.searchParams;
  const warnings = [];
  const single = key => {
    const values = params.getAll(key);
    if (values.length > 1) warnings.push(key);
    return values[0] || "";
  };
  const month = single("month"), order = single("order");
  const state = {
    month: /^[1-9][0-9]{3}-(0[1-9]|1[0-2])$/.test(month) ? month : "",
    order: order === "asc" ? "asc" : "desc",
    query: normalizeViewQuery(single("q")),
    categories: [], feeds: [], from: "", to: "", invalidDateInput: false,
  };
  if (month && !state.month) warnings.push("month");
  if (order && !["asc", "desc"].includes(order)) warnings.push("order");
  if ((params.get("q") || "").length > VIEW_LIMITS.query) warnings.push("q");
  for (const [key, param] of [["categories", "category"], ["feeds", "feed"]]) {
    const raw = params.getAll(param);
    state[key] = [...new Set(raw.filter(v => v && v.length <= VIEW_LIMITS.option))].sort()
      .slice(0, VIEW_LIMITS.selections);
    if (raw.some(v => !state[key].includes(v))) warnings.push(param);
    if (options) {
      const known = state[key].filter(v => options[key].includes(v));
      if (known.length !== state[key].length) warnings.push(param);
      state[key] = known;
    }
  }
  for (const key of ["from", "to"]) {
    const date = single(key);
    if (date && !urlParser.validFilterDate(date)) warnings.push(key);
    else state[key] = date;
  }
  if (state.from && state.to && state.from > state.to) {
    state.from = state.to = "";
    warnings.push("期間");
  }
  const hash = url.hash.slice(1);
  const article = /^article-[A-Za-z0-9_-]+(?:~[1-9][0-9]*)?$/.test(hash) && hash.length <= VIEW_LIMITS.article ? hash : "";
  if (hash.startsWith("article-") && !article) warnings.push("記事リンク");
  return { state, article, sample: params.has("sample"), warnings: [...new Set(warnings)] };
}

function writeViewURL(value, state, article = "") {
  const url = new URL(value, "https://local.invalid/");
  const sample = url.searchParams.has("sample");
  url.search = "";
  if (sample) url.searchParams.set("sample", "");
  if (state.month) url.searchParams.set("month", state.month);
  if (state.order === "asc") url.searchParams.set("order", "asc");
  if (state.query) url.searchParams.set("q", state.query);
  for (const [key, param] of [["categories", "category"], ["feeds", "feed"]]) {
    for (const v of [...new Set(state[key])].sort()) url.searchParams.append(param, v);
  }
  // Native date input under construction is deliberately not persisted.
  if (!urlParser.validateFilterDates(state)) {
    for (const key of ["from", "to"]) if (state[key]) url.searchParams.set(key, state[key]);
  }
  url.hash = article;
  return url.pathname + url.search + url.hash;
}

// Reversible base64url of UTF-16 bytes: unlike a short hash this has no collisions.
// A validated URL's complete identity (including query and fragment) is preserved.
function articleId(value) {
  const url = urlParser.safeUrl(value);
  if (!url || url.length > 8192) return "";
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  let bits = 0, count = 0, encoded = "";
  for (let i = 0; i < url.length; i++) {
    for (const byte of [url.charCodeAt(i) >> 8, url.charCodeAt(i) & 255]) {
      bits = (bits << 8) | byte;
      count += 8;
      while (count >= 6) { count -= 6; encoded += alphabet[(bits >> count) & 63]; }
    }
  }
  if (count) encoded += alphabet[(bits << (6 - count)) & 63];
  return "article-" + encoded;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { readViewURL, writeViewURL, articleId, normalizeViewQuery, VIEW_LIMITS };
}
