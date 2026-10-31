"use strict";
// Independent reader and request lifetime; official search/parser/data remain separate.
const ImportReader = (() => {
  const names = { official: "公式ニュース", x: "Grok（X）", p: "Perplexity（週次）" };
  let hooks, api, serial = 0, active = "official", sample = false, retrying = false, retryNeeded = false;
  const byId = id => document.getElementById(id);
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  function status(text, retry = false, complete = false) {
    byId("import-status").className = complete ? "visually-hidden" : retry ? "import-error" : "";
    byId("import-status").textContent = text;
    retryNeeded = retry;
    byId("import-retry").hidden = !retry && !retrying;
  }
  function navigate(source, id = "", replace = false) {
    const next = ImportCatalog.routeURL(location.href, source, id);
    if (next !== location.pathname + location.search + location.hash) history[replace ? "replaceState" : "pushState"](null, "", next);
    if (!restore()) hooks.showOfficial();
  }
  function renderGrok(text, id) {
    const parsed = ImportMarkdown.grok(text), grid = make("div", undefined, "grok-news-grid");
    byId("import-heading").textContent = parsed.title || `Grok（X） · ${id}`;
    const summary = make("ul", undefined, "grok-summary");
    const addSummary = (key, value) => {
      const li = make("li"); li.appendChild(make("span", key + " ", "grok-meta-label"));
      li.appendChild(document.createTextNode(value)); summary.appendChild(li);
    };
    if (!parsed.meta["採用件数"]) addSummary("表示件数", `${parsed.items.length}件`);
    const metaKeys = [...new Set(["採用件数", "収集日時", "対象期間", "収集元", ...Object.keys(parsed.meta)])];
    for (const key of metaKeys) if (Object.hasOwn(parsed.meta, key)) {
      addSummary(key === "採用件数" ? "採用件数（原記録）" : key, parsed.meta[key]);
    }
    byId("import-metadata").replaceChildren(summary);
    if (!parsed.items.length) {
      const fallback = make("article", undefined, "import-document grok-fallback");
      fallback.appendChild(make("p", "項目形式を読み取れないため、原記録をMarkdownとして表示します。"));
      fallback.appendChild(ImportMarkdown.render(document, text, 3)); return fallback;
    }
    const known = new Set(["概要", "注目点", "カテゴリ", "投稿者", "投稿日時", "元投稿", "情報の確度"]);
    parsed.items.forEach((item, index) => {
      const fields = item.fields, card = make("article", undefined, "grok-card");
      const title = make("h3", item.title || "（タイトルなし）", "grok-card-title");
      title.id = `grok-card-${index + 1}`; card.setAttribute("aria-labelledby", title.id); card.appendChild(title);
      const overview = make("p", undefined, "grok-overview");
      ImportMarkdown.inline(document, overview, fields["概要"] || "（概要の記載なし）"); card.appendChild(overview);
      if (Object.hasOwn(fields, "注目点")) {
        const point = make("p", undefined, "grok-point");
        point.appendChild(make("span", "注目点 ", "grok-point-label"));
        ImportMarkdown.inline(document, point, fields["注目点"]); card.appendChild(point);
      }
      const footer = make("div", undefined, "grok-card-footer"), meta = make("ul", undefined, "grok-card-meta");
      for (const key of ["カテゴリ", "投稿者", "投稿日時"]) if (Object.hasOwn(fields, key)) {
        const li = make("li"); li.appendChild(make("span", key + ": ", "grok-meta-label"));
        ImportMarkdown.inline(document, li, fields[key]); meta.appendChild(li);
      }
      footer.appendChild(meta);
      if (Object.hasOwn(fields, "情報の確度")) {
        const confidence = make("p", undefined, "grok-confidence");
        confidence.appendChild(make("span", "原記録の確度（未検証）: ", "grok-meta-label"));
        ImportMarkdown.inline(document, confidence, fields["情報の確度"]); footer.appendChild(confidence);
      }
      const source = make("p", undefined, "grok-source");
      if (ImportMarkdown.safeLink(fields["元投稿"])) source.appendChild(ImportMarkdown.link(document, "元投稿を開く", fields["元投稿"]));
      else source.textContent = fields["元投稿"] ? "元投稿（リンク無効）: " + fields["元投稿"] : "元投稿URLの記載なし";
      footer.appendChild(source); card.appendChild(footer);
      const extra = make("dl", undefined, "grok-extra");
      for (const [key, value] of Object.entries(fields)) if (!known.has(key)) {
        extra.appendChild(make("dt", key)); const dd = make("dd");
        ImportMarkdown.inline(document, dd, value); extra.appendChild(dd);
      }
      if (extra.childNodes.length) card.appendChild(extra);
      grid.appendChild(card);
    });
    return grid;
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
    fallback.textContent = requested ? "GitHubの原記録" : "GitHubの一覧";
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
      fallback.href = selected.original; fallback.textContent = "GitHubの原記録";
      status("本文を読み込み中…");
      const text = await api.body(selected, refresh || retryBody);
      if (token !== serial) return;
      if (!text.trim()) throw new Error("原記録の本文が空です。GitHubの原ファイルも確認してください。");
      if (source === "x") byId("import-content").appendChild(renderGrok(text, selected.id));
      else {
        byId("import-metadata").textContent = metadata(text) || "対象週・調査日は原記録を確認してください。";
        const report = make("article", undefined, "import-document");
        report.appendChild(ImportMarkdown.render(document, text, 3)); byId("import-content").appendChild(report);
      }
      status(`${selected.id}の原記録を表示しました。`, false, true);
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
      ? "Grok生成の未検証候補です（確度は原記録の申告で、公式ニュースの採用・検索対象外のため、重要な判断は元出典を確認してください）。"
      : "Perplexityによる週途中を含む調査で、一部未検証のため重要な判断は元出典を確認してください。";
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
