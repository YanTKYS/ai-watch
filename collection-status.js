"use strict";
// 記事表示と独立した公開スナップショットの表示。一定間隔のネットワーク監視はしない。
const CollectionHealth = (() => {
  const STALE_HOURS = 36; // 毎日JST 06:41、24時間の間隔 + Actions遅延への12時間の猶予
  const time = value => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;
  const count = value => Number.isSafeInteger(value) && value >= 0;
  const format = value => time(value) === null ? "不明" : new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", dateStyle: "short", timeStyle: "short",
  }).format(new Date(value)) + " JST";

  function summarize(data, now = Date.now(), staleHours = STALE_HOURS) {
    const unknown = { summary: "収集状況: 状態不明", detail: "最後に公開された状態を確認できません。記事の閲覧は続けられます。",
      index: "検索インデックス: 状態不明", feeds: [] };
    if (!data || data.schema_version !== 1) return unknown;
    const c = data.collection;
    const i = data.index;
    const model = { ...unknown };
    const validIndex = i && ["success", "failed", "skipped"].includes(i.result) && time(i.checked_at) !== null
      && (i.last_success_at === null || (time(i.last_success_at) !== null && time(i.last_success_at) <= now + 300000))
      && (i.result !== "success" || i.last_success_at === i.checked_at) && time(i.checked_at) <= now + 300000;
    if (validIndex) {
      const label = { success: "生成成功", failed: "生成失敗", skipped: "生成未実行" }[i.result];
      const sameAttempt = c && c.attempted_at && i.for_collection === c.attempted_at;
      model.index = `検索インデックス: ${sameAttempt ? label : "今回の生成は未確認（前回: " + label + "）"}。`
        + `最終生成成功: ${format(i.last_success_at)}。生成成功はコミット・配信成功を保証しません。`;
    }
    if (!c || !["success", "partial", "failed", "running", "error", "unknown"].includes(c.result)
        || !Array.isArray(c.feeds) || !(c.new_articles === null || count(c.new_articles))
        || !(c.last_all_success_at === null || (time(c.last_all_success_at) !== null && time(c.last_all_success_at) <= now + 300000))) return model;
    const validFeeds = c.feeds.every(f => f && typeof f.name === "string" && f.name
      && ["success", "failed"].includes(f.status)
      && (f.status === "failed" ? f.candidates === null && f.adopted === null : count(f.candidates) && count(f.adopted)));
    const failed = c.feeds.filter(f => f && f.status === "failed").length;
    const complete = ["success", "partial", "failed"].includes(c.result);
    const consistent = c.result === "success" ? c.feeds.length > 0 && failed === 0
      : c.result === "partial" ? failed > 0 && failed < c.feeds.length
      : c.result === "failed" ? failed > 0 && failed === c.feeds.length : true;
    const attempted = time(c.attempted_at);
    if (!validFeeds || !consistent || (complete && (!count(c.new_articles) || time(c.completed_at) === null || time(c.completed_at) > now + 300000))
        || (attempted !== null && attempted > now + 300000)) return model;
    const result = { success: "正常", partial: "一部取得失敗", failed: "取得失敗", running: "状態不明（収集未完了）",
      error: "取得失敗（収集処理未完了）", unknown: "状態不明" }[c.result];
    const stale = attempted !== null && now - attempted > staleHours * 3600000;
    const freshResult = attempted === null ? "状態不明" : result;
    model.summary = `収集状況: ${stale ? "更新遅延" : freshResult}`;
    if (!stale && c.result === "success" && attempted !== null) {
      model.summary += c.new_articles === 0 ? "・新着なし" : `・新着${c.new_articles}件`;
    }
    model.detail = `最後に公開された試行: ${format(c.attempted_at)}。最終全フィード成功: ${format(c.last_all_success_at)}。`
      + (stale ? `前回の結果: ${result}。予定は毎日06:41 JST。状態が古く、収集停止や配信失敗の可能性があります。再読み込みで最新の公開記録を確認してください。` : "公開済みの公式フィード収集結果です。");
    model.feeds = c.feeds.map(f => `${f.name}: ${f.status === "success"
      ? "取得成功、候補" + f.candidates + "件・採用" + f.adopted + "件" : "取得失敗"}`);
    return model;
  }

  async function start(document, fetchState, location, clock = () => Date.now()) {
    const panel = document.getElementById("collection-health");
    if (new URLSearchParams(location.search).has("sample")) {
      panel.hidden = true;
      return () => {}; // 本番状態をサンプルと混ぜず、状態取得リクエストもしない
    }
    let data = null;
    const render = () => {
      const model = summarize(data, clock());
      for (const [id, text] of [["collection-summary", model.summary], ["collection-detail", model.detail], ["index-summary", model.index]]) {
        const node = document.getElementById(id);
        if (node.textContent !== text) node.textContent = text;
      }
      const list = document.getElementById("collection-feeds");
      if (list.textContent !== model.feeds.join("")) {
        list.replaceChildren(...model.feeds.map(text => {
          const node = document.createElement("li"); node.textContent = text; return node;
        }));
      }
      document.getElementById("collection-feed-details").hidden = !model.feeds.length;
    };
    render();
    try {
      const response = await fetchState("data/collection-status.json", { cache: "no-cache" });
      if (!response.ok) throw new Error("status unavailable");
      data = await response.json();
    } catch (e) {
      data = null;
    }
    render();
    return render;
  }
  return { summarize, start, STALE_HOURS };
})();

if (typeof module !== "undefined" && module.exports) module.exports = CollectionHealth;
if (typeof document !== "undefined") {
  CollectionHealth.start(document, fetch, location).then(render => {
    // キャッシュした時刻の表示だけを更新する。ネットワークの定期取得ではない。
    if (!new URLSearchParams(location.search).has("sample")) setInterval(render, 60000);
  });
}
