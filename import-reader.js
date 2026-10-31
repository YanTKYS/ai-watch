"use strict";
// Independent reader and request lifetime; official search/parser/data remain separate.
const ImportReader = (() => {
  const names = { official: "公式ニュース", x: "Grok（X）", p: "Perplexity（週次）" };
  let hooks, api, serial = 0, active = "official", sample = false, retrying = false, retryNeeded = false;
  const byId = id => document.getElementById(id);
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  function status(text, retry = false) {
    byId("import-status").textContent = text;
    retryNeeded = retry;
    byId("import-retry").hidden = !retry && !retrying;
  }
  function navigate(source, id = "", replace = false) {
    const next = ImportCatalog.routeURL(location.href, source, id);
    if (next !== location.pathname + location.search + location.hash) history[replace ? "replaceState" : "pushState"](null, "", next);
    if (!restore()) hooks.showOfficial();
  }
  function renderGrok(text) {
    const parsed = ImportMarkdown.grok(text), article = make("article", undefined, "import-document");
    article.appendChild(make("h3", parsed.title || "Xニュースの原記録"));
    const meta = make("dl", undefined, "import-fields");
    for (const [k, v] of Object.entries(parsed.meta)) { meta.appendChild(make("dt", k)); meta.appendChild(make("dd", v)); }
    article.appendChild(meta);
    if (!parsed.items.length) {
      article.appendChild(make("p", "項目形式を読み取れないため、原記録をMarkdownとして表示します。"));
      article.appendChild(ImportMarkdown.render(document, text, 4));
    }
    for (const item of parsed.items) {
      const card = make("section", undefined, "import-card"); card.appendChild(make("h4", item.title));
      const fields = make("dl", undefined, "import-fields");
      for (const [k, v] of Object.entries(item.fields)) {
        fields.appendChild(make("dt", k === "情報の確度" ? "原記録の確度（未検証）" : k));
        const dd = make("dd");
        if (k === "元投稿") dd.appendChild(ImportMarkdown.link(document, "元投稿を開く", v));
        else ImportMarkdown.inline(document, dd, v);
        fields.appendChild(dd);
      }
      if (!Object.keys(item.fields).length) fields.appendChild(make("dd", "詳細欄を読み取れません。原記録も確認してください。"));
      card.appendChild(fields); article.appendChild(card);
    }
    return article;
  }
  function metadata(text) {
    return text.split(/\r?\n/).filter(line => /^- (調査日|対象週):/.test(line)).join("\n");
  }
  async function load(refresh = false, retryBody = false) {
    const token = ++serial, state = ImportCatalog.route(location.href);
    if (state.source === "official") return;
    const source = state.source;
    byId("import-content").replaceChildren();
    byId("import-metadata").textContent = "";
    const picker = byId("import-select"); picker.replaceChildren(); picker.disabled = true;
    byId("import-refresh").disabled = true;
    const fallback = byId("import-original");
    const requested = ImportCatalog.entry(source, state.id);
    fallback.href = requested?.original || ImportCatalog.REPO + `tree/main/imports/${source}`;
    fallback.textContent = requested ? "GitHubで原ファイルを読む（新しいタブ）" : "GitHubで原記録の一覧を開く（新しいタブ）";
    status("ファイル一覧を読み込み中…");
    try {
      const files = await api.discover(source, refresh);
      if (token !== serial) return;
      for (const file of files) { const option = make("option", file.id); option.value = file.id; picker.appendChild(option); }
      picker.disabled = !files.length;
      if (!files.length) { status("命名規則に合う原記録は、リポジトリの一覧にまだありません。一覧を更新できます。"); return; }
      // Invalid or unknown selections are not silently presented as the latest report.
      const selected = state.id ? files.find(f => f.id === state.id) : files[0];
      if (!selected) { picker.value = ""; status("指定した日付・週は一覧にありません。別の原記録を選ぶか、一覧を更新してください。", true); return; }
      picker.value = selected.id;
      if (!state.id) history.replaceState(null, "", ImportCatalog.routeURL(location.href, source, selected.id));
      fallback.href = selected.original; fallback.textContent = "GitHubで原ファイルを読む（新しいタブ）";
      status("本文を読み込み中…");
      const text = await api.body(selected, refresh || retryBody);
      if (token !== serial) return;
      if (!text.trim()) throw new Error("原記録の本文が空です。GitHubの原ファイルも確認してください。");
      if (source === "x") byId("import-content").appendChild(renderGrok(text));
      else {
        byId("import-metadata").textContent = metadata(text) || "対象週・調査日は原記録を確認してください。";
        const report = make("article", undefined, "import-document");
        report.appendChild(ImportMarkdown.render(document, text, 3)); byId("import-content").appendChild(report);
      }
      status(`${selected.id}の原記録を表示しました。`);
    } catch (error) {
      if (token === serial) status(error.name === "AbortError" ? "読み込みがタイムアウトしました。再試行してください。"
        : ["TypeError", "SyntaxError"].includes(error.name) ? "データを取得・解析できませんでした。再試行するかGitHubの原記録を確認してください。" : error.message, true);
    } finally {
      if (token === serial) byId("import-refresh").disabled = false;
    }
  }
  function restore() {
    const state = ImportCatalog.route(location.href);
    if (state.sample !== sample) { location.reload(); return true; }
    active = state.source; ++serial; retrying = false;
    byId("import-retry").setAttribute("aria-disabled", "false");
    byId("source-navigation").hidden = sample;
    byId("official-controls").hidden = active !== "official";
    byId("official-view").hidden = active !== "official";
    byId("import-view").hidden = active === "official";
    for (const a of document.querySelectorAll("[data-news-source]")) {
      const source = a.dataset.newsSource;
      a.href = ImportCatalog.routeURL(location.href, source);
      if (source === active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    if (active === "official") return false;
    hooks.leaveOfficial();
    byId("import-heading").textContent = names[active];
    byId("import-label").textContent = active === "x" ? "表示する日付（新しい順）" : "表示する対象週（新しい順）";
    byId("import-disclaimer").textContent = active === "x"
      ? "Grokが生成した未検証の候補です。原記録の「公式発表」等の確度表記も検証済みを意味しません。投稿日時・対象期間・収集日時は原記録の記載を表示します。"
      : "Perplexityによる週次調査です。一部未検証の可能性があります。対象週と調査日は原記録の記載です。週途中の調査も含みます。";
    load(); return true;
  }
  function start(callbacks) {
    hooks = callbacks; sample = new URLSearchParams(location.search).has("sample"); api = ImportCatalog.create(fetch);
    for (const a of document.querySelectorAll("[data-news-source]")) a.addEventListener("click", event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); navigate(a.dataset.newsSource);
    });
    byId("import-select").addEventListener("change", event => navigate(active, event.target.value));
    byId("import-refresh").addEventListener("click", () => {
      retrying = false; byId("import-retry").setAttribute("aria-disabled", "false"); load(true);
    });
    byId("import-retry").addEventListener("click", async () => {
      if (retrying) return;
      retrying = true;
      const button = byId("import-retry");
      button.setAttribute("aria-disabled", "true");
      const pending = load(false, true), token = serial;
      await pending;
      if (token !== serial) return;
      retrying = false; button.setAttribute("aria-disabled", "false");
      if (!retryNeeded && document.activeElement === button) byId("import-heading").focus();
      button.hidden = !retryNeeded;
    });
    if (sample && new URLSearchParams(location.search).has("source")) history.replaceState(null, "", ImportCatalog.routeURL(location.href, "official"));
    return restore();
  }
  return { start, restore };
})();
