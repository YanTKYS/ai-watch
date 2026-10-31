"use strict";
const ImportCatalog = (() => {
  const API = "https://api.github.com/repos/YanTKYS/ai-watch/contents/";
  const REPO = "https://github.com/YanTKYS/ai-watch/";
  const MAX_BYTES = 1_000_000;
  function validDate(value) {
    if (!/^[1-9]\d{3}-\d{2}-\d{2}$/.test(value)) return false;
    const d = new Date(value + "T00:00:00Z");
    return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === value;
  }
  function validWeek(value) {
    const m = /^([1-9]\d{3})-W(0[1-9]|[1-4]\d|5[0-3])$/.exec(value);
    if (!m) return false;
    const jan1 = new Date(`${m[1]}-01-01T00:00:00Z`).getUTCDay();
    const leap = new Date(`${m[1]}-02-29T00:00:00Z`).getUTCMonth() === 1;
    return +m[2] <= (jan1 === 4 || (jan1 === 3 && leap) ? 53 : 52);
  }
  function validEntry(source, value) { return source === "x" ? validDate(value) : source === "p" && validWeek(value); }
  function entry(source, id) {
    if (!validEntry(source, id)) return null;
    const path = source === "x" ? `imports/x/${id.slice(0, 4)}/x-${id.replaceAll("-", "")}.md` : `imports/p/${id}.md`;
    return { id, path, original: REPO + "blob/main/" + path };
  }
  function entries(source, rows, year = "") {
    if (!Array.isArray(rows)) throw new Error("ファイル一覧の形式を確認できません。");
    if (rows.length >= 1000) throw new Error("GitHub APIの一覧上限に達しています。全件を確認できないため原記録をGitHubで確認してください。");
    const found = new Map();
    for (const row of rows) {
      if (!row || row.type !== "file" || typeof row.name !== "string") continue;
      const m = source === "x" ? /^x-(\d{4})(\d{2})(\d{2})\.md$/.exec(row.name) : /^([1-9]\d{3}-W\d{2})\.md$/.exec(row.name);
      const id = !m ? "" : source === "x" ? `${m[1]}-${m[2]}-${m[3]}` : m[1];
      const e = entry(source, id);
      if (e && (source !== "x" || id.startsWith(year + "-")) && row.path === e.path) found.set(id, e);
    }
    return [...found.values()].sort((a, b) => b.id.localeCompare(a.id));
  }
  function route(value) {
    const url = new URL(value, "https://local.invalid/");
    const source = url.searchParams.get("source");
    const sample = url.searchParams.has("sample");
    return { source: !sample && ["x", "p"].includes(source) ? source : "official",
      id: url.searchParams.get("entry") || "", sample };
  }
  function routeURL(value, source, id = "") {
    const u = new URL(value, "https://local.invalid/");
    u.searchParams.delete("source"); u.searchParams.delete("entry");
    if (!u.searchParams.has("sample") && ["x", "p"].includes(source)) {
      u.searchParams.set("source", source);
      if (validEntry(source, id)) u.searchParams.set("entry", id);
    }
    return u.pathname + u.search + u.hash;
  }
  async function readResponse(res, max = MAX_BYTES) {
    if (+res.headers.get("content-length") > max) throw new Error("ファイルが表示上限を超えています。");
    if (!res.body?.getReader) { const text = await res.text(); if (new TextEncoder().encode(text).length > max) throw new Error("ファイルが表示上限を超えています。"); return text; }
    const reader = res.body.getReader(), decoder = new TextDecoder(); let size = 0, text = "";
    try {
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.byteLength;
        if (size > max) { await reader.cancel(); throw new Error("ファイルが表示上限を超えています。"); }
        text += decoder.decode(value, { stream: true });
      }
      return text + decoder.decode();
    } finally { reader.releaseLock(); }
  }
  function create(fetcher) {
    const lists = new Map(), documents = new Map();
    async function get(url, api = false) {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
      try {
        const res = await fetcher(url, { cache: "no-cache", credentials: "omit", redirect: "error", signal: controller.signal,
          ...(api ? { headers: { Accept: "application/vnd.github+json" } } : {}) });
        if (!res.ok) {
          if (api && [403, 429].includes(res.status)) throw new Error("GitHubの公開APIが制限中か、アクセスを拒否しています。時間をおいて再試行してください。");
          if (!api && res.status === 404) throw new Error("本文がまだPagesへ配信されていない可能性があります。時間をおいて再試行してください。");
          throw new Error(api ? "GitHubのファイル一覧を取得できませんでした。" : "本文を取得できませんでした。");
        }
        return await readResponse(res);
      } finally { clearTimeout(timer); }
    }
    async function discover(source, refresh = false) {
      if (!["x", "p"].includes(source)) throw new Error("表示元が不正です。");
      if (refresh) lists.delete(source);
      if (!lists.has(source)) {
        const request = (async () => {
          const root = JSON.parse(await get(API + `imports/${source}?ref=main`, true));
          if (!Array.isArray(root)) throw new Error("ファイル一覧の形式を確認できません。");
          if (root.length >= 1000) throw new Error("GitHub APIの一覧上限に達しています。原記録をGitHubで確認してください。");
          if (source === "p") return entries(source, root);
          const years = [...new Set(root.filter(r => r && r.type === "dir" && /^[1-9]\d{3}$/.test(r.name)
            && r.path === `imports/x/${r.name}`).map(r => r.name))].sort().reverse();
          const result = [];
          for (const year of years) result.push(...entries("x", JSON.parse(await get(API + `imports/x/${year}?ref=main`, true)), year));
          return result.sort((a, b) => b.id.localeCompare(a.id));
        })();
        lists.set(source, request);
        request.catch(() => { if (lists.get(source) === request) lists.delete(source); });
      }
      return lists.get(source);
    }
    async function body(e, refresh = false) {
      // Reconstruct, never trust API download_url / html_url or caller-provided paths.
      const source = e.path?.startsWith("imports/x/") ? "x" : "p";
      if (entry(source, e.id)?.path !== e.path) throw new Error("ファイルの指定が不正です。");
      if (refresh) documents.delete(e.path);
      if (!documents.has(e.path)) {
        const request = get(e.path);
        documents.set(e.path, request);
        request.catch(() => { if (documents.get(e.path) === request) documents.delete(e.path); });
      }
      return documents.get(e.path);
    }
    return { discover, body };
  }
  return { validDate, validWeek, validEntry, entry, entries, route, routeURL, create, readResponse, REPO };
})();
if (typeof module !== "undefined" && module.exports) module.exports = ImportCatalog;
