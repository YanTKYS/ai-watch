"""Brave Search API による検索と、取得品質の集計。

Brave Search API の利用規約は、ストレージ権付きプラン以外での検索結果の保存・キャッシュ・データベース化を
認めていない。そのため検索結果（URL・タイトル・説明文）は実行中のメモリ上で集計に使うだけで、
ログ・seen.json・検索インデックス・Actionsログには書き出さない。永続化するのは件数の集計だけ。

API利用量の制御:
- 1日（日本時間）のリクエスト上限は MAX_DAILY_REQUESTS（設定で下げられるが上げられない）。
- 1日1回だけ実行する。同じ日に再実行（手動実行を含む）してもAPIを呼ばない。
- 利用件数は data/brave-usage.json に記録し、各リクエストの直前に書き込む（途中で失敗しても数え漏れない）。
- ページング・自動リトライなし。1検索語につき1リクエスト。

将来X公式APIへ移行する場合は search() を置き換える（戻り値は url/title/description/page_age の辞書のリスト）。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from common import USER_AGENT, ConfigError, compile_terms, matches_any, normalize_url

API_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_DAILY_REQUESTS = 4  # ハードリミット（news-watch と合わせても無料クレジットに十分な余裕を残す）
RESULT_COUNT = 20  # 1リクエストあたりの取得件数（Brave Web Search の上限。ページングはしない）
REQUEST_INTERVAL_SEC = 1.1  # レート制限（1 req/sec）対策
TIMEOUT_SEC = 15
MAX_RESPONSE_BYTES = 2_000_000
MAX_QUERY_CHARS = 400  # Brave Search API の検索語長の上限
USAGE_RETENTION_DAYS = 90
RECENT_DAYS = 7  # 「公開日が新しい」とみなす日数
KINDS = ("x", "web")
FRESHNESS_RE = re.compile(r"^(pd|pw|pm|py|\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2})$")
LANG_RE = re.compile(r"^[a-z]{2}(-[a-z]{2,4})?$")
COUNTRY_RE = re.compile(r"^([A-Z]{2}|ALL)$")
X_HOSTS = ("x.com", "twitter.com")
X_SITE_RE = re.compile(r"\bsite:(x|twitter)\.com\b", re.IGNORECASE)
X_POST_RE = re.compile(r"^/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)(?:/.*)?$")
X_PROFILE_RE = re.compile(r"^/([A-Za-z0-9_]{1,15})/?$")
X_RESERVED = {"i", "home", "search", "explore", "hashtag", "settings", "login", "signup", "intent", "share",
              "notifications", "messages", "tos", "privacy", "about"}
VERSION_RE = re.compile(r"(?<![A-Za-z0-9])v?\d+\.\d+(\.\d+)?(?![A-Za-z0-9])")


@dataclass
class Query:
    id: str
    kind: str  # "x" | "web"
    category: str
    q: str
    search_lang: str = "en"
    country: str = "ALL"
    freshness: str = "pd"


@dataclass
class BraveConfig:
    daily_limit: int
    queries: list[Query]
    evidence: list[re.Pattern] = field(default_factory=list)
    hype: list[re.Pattern] = field(default_factory=list)


@dataclass
class QueryStats:
    """1検索語の取得品質（件数のみ。URL・タイトルなどの検索結果そのものは持たない）。"""
    kind: str
    category: str
    status: str = "skipped"  # ok | failed | skipped
    error: str = ""
    results: int = 0  # http(s) の結果件数
    x_posts: int = 0  # x.com/{user}/status/{id} 形式（実際の投稿）
    x_profiles: int = 0  # x.com/{user}（プロフィール）
    x_other: int = 0  # その他の x.com ページ（検索・ハッシュタグなど）
    non_x: int = 0  # x.com 以外
    x_authors: int = 0  # 投稿者（ハンドル）の種類数
    dated: int = 0  # 公開日（page_age）がある
    recent: int = 0  # 公開日が RECENT_DAYS 日以内
    on_topic: int = 0  # カテゴリのキーワードを含む
    evidence: int = 0  # 根拠を示す語・バージョン番号を含む
    hype: int = 0  # 誇張表現を含む
    candidates: int = 0  # 保存できるなら採用候補になるもの（下記 evaluate 参照）
    duplicates: int = 0  # 同じ実行の別の検索語で既出
    official_overlap: int = 0  # 公式フィードで収集済みのURL


@dataclass
class ProbeResult:
    status: str  # ran | already_ran | no_api_key | limit_reached | no_queries | usage_unreadable
    requests: int = 0
    failed: int = 0
    queries: dict[str, QueryStats] = field(default_factory=dict)


# ---- 設定 ---------------------------------------------------------------
def load_brave(raw: object, quality: object, category_ids: set[str]) -> BraveConfig:
    if raw is None:
        return BraveConfig(daily_limit=0, queries=[])
    if not isinstance(raw, dict):
        raise ConfigError("'brave' はマッピングにしてください")
    limit = raw.get("daily_limit", MAX_DAILY_REQUESTS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= MAX_DAILY_REQUESTS:
        raise ConfigError(f"brave.daily_limit は 0〜{MAX_DAILY_REQUESTS} の整数にしてください: {limit!r}")
    items = raw.get("queries", [])
    if not isinstance(items, list):
        raise ConfigError("brave.queries はリストにしてください")
    queries: list[Query] = []
    ids: set[str] = set()
    texts: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ConfigError("brave.queries の各要素はマッピングにしてください")
        qid, q = item.get("id"), item.get("q")
        if not isinstance(qid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", qid):
            raise ConfigError(f"brave.queries の id が不正です（英小文字・数字・ハイフン）: {qid!r}")
        if qid in ids:
            raise ConfigError(f"brave.queries の id が重複しています: {qid}")
        if not isinstance(q, str) or not q.strip():
            raise ConfigError(f"検索語 '{qid}' の q が空です")
        q = " ".join(q.split())
        if q in texts:
            raise ConfigError(f"検索語が重複しています: {qid}")
        if len(q) > MAX_QUERY_CHARS:
            raise ConfigError(f"検索語 '{qid}' が長すぎます（{MAX_QUERY_CHARS}文字まで）")
        kind = item.get("kind")
        if kind not in KINDS:
            raise ConfigError(f"検索語 '{qid}' の kind は x / web のどちらかにしてください: {kind!r}")
        if kind == "x" and not X_SITE_RE.search(q):
            raise ConfigError(f"検索語 '{qid}' は kind: x なので site:x.com を含めてください")
        if item.get("category") not in category_ids:
            raise ConfigError(f"検索語 '{qid}' の category が categories にありません: {item.get('category')!r}")
        query = Query(id=qid, kind=kind, category=item["category"], q=q,
                      search_lang=item.get("search_lang", "en"), country=item.get("country", "ALL"),
                      freshness=item.get("freshness", "pd"))
        if not isinstance(query.search_lang, str) or not LANG_RE.match(query.search_lang):
            raise ConfigError(f"検索語 '{qid}' の search_lang が不正です（例: en, ja）")
        if not isinstance(query.country, str) or not COUNTRY_RE.match(query.country):
            raise ConfigError(f"検索語 '{qid}' の country が不正です（例: US, JP, ALL）")
        if not isinstance(query.freshness, str) or not FRESHNESS_RE.match(query.freshness):
            raise ConfigError(f"検索語 '{qid}' の freshness が不正です（pd / pw / pm / py）")
        ids.add(qid)
        texts.add(q)
        queries.append(query)
    if len(queries) > limit:  # 黙って切り捨てず、設定の見直しを求める
        raise ConfigError(f"Brave検索語が1日の上限を超えています: {len(queries)} 件 (上限 {limit} 件)")
    quality = quality if isinstance(quality, dict) else {}
    return BraveConfig(daily_limit=limit, queries=queries,
                       evidence=compile_terms(quality.get("evidence_terms"), "quality.evidence_terms"),
                       hype=compile_terms(quality.get("hype_terms"), "quality.hype_terms"))


# ---- 利用件数の記録（data/brave-usage.json） ------------------------------------
def load_usage(path: Path) -> dict:
    """読めない場合は例外。利用件数が分からない状態ではAPIを呼ばない（fail-closed）。"""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise ValueError("invalid usage file")
    return data


def save_usage(path: Path, usage: dict, today: str) -> None:
    oldest = (date.fromisoformat(today) - timedelta(days=USAGE_RETENTION_DAYS)).isoformat()
    kept = {d: v for d, v in usage.items() if d >= oldest}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def requests_on(usage: dict, day: str) -> int:
    value = (usage.get(day) or {}).get("requests", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else MAX_DAILY_REQUESTS


# ---- Brave Search API ----------------------------------------------------
def build_request(query: Query, api_key: str) -> urllib.request.Request:
    params = urllib.parse.urlencode({
        "q": query.q,
        "count": RESULT_COUNT,
        "country": query.country,
        "search_lang": query.search_lang,
        "freshness": query.freshness,
        "result_filter": "web",
    })
    return urllib.request.Request(f"{API_ENDPOINT}?{params}", headers={
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "X-Subscription-Token": api_key,  # URLには含めない
    })


def search(query: Query, api_key: str) -> list[dict]:
    """1回だけAPIを呼ぶ。失敗時は例外（本文・ヘッダは含めない）。"""
    with urllib.request.urlopen(build_request(query, api_key), timeout=TIMEOUT_SEC) as resp:
        body = resp.read(MAX_RESPONSE_BYTES)
    data = json.loads(body)
    results = ((data.get("web") or {}).get("results")) if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    return [r for r in results if isinstance(r, dict)][:RESULT_COUNT]


def describe_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return type(e).__name__


# ---- 品質集計 --------------------------------------------------------------
def classify_x_url(url: str) -> tuple[str, str | None]:
    """("post" | "profile" | "other" | "non_x", 投稿者ハンドル)。"""
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "") not in X_HOSTS:
        return "non_x", None
    m = X_POST_RE.match(parts.path)
    if m and m.group(1).lower() not in X_RESERVED:
        return "post", m.group(1).lower()
    m = X_PROFILE_RE.match(parts.path)
    if m and m.group(1).lower() not in X_RESERVED:
        return "profile", None
    return "other", None


def _page_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def evaluate(query: Query, results: list[dict], cfg: BraveConfig, topic_terms: list[re.Pattern],
             today: str, known_urls: set[str], run_urls: set[str]) -> QueryStats:
    """検索結果をメモリ上で集計する。戻り値は件数だけ（検索結果そのものは返さない・保存しない）。

    candidates（保存できる場合の採用候補相当）: カテゴリのキーワードを含み、誇張表現を含まず、
    公開日が RECENT_DAYS 日以内で、kind: x では実際の投稿URL（x.com/{user}/status/{id}）であるもの。
    投稿者の人気・フォロワー数は使わない。
    """
    s = QueryStats(kind=query.kind, category=query.category, status="ok")
    authors: set[str] = set()
    today_d = date.fromisoformat(today)
    for r in results:
        url = normalize_url(r.get("url"))
        if not url:
            continue
        s.results += 1
        if url in run_urls:
            s.duplicates += 1
        run_urls.add(url)
        if url in known_urls:
            s.official_overlap += 1
        kind, author = classify_x_url(url)
        if kind == "post":
            s.x_posts += 1
            authors.add(author)
        elif kind == "profile":
            s.x_profiles += 1
        elif kind == "other":
            s.x_other += 1
        else:
            s.non_x += 1
        published = _page_date(r.get("page_age"))
        recent = published is not None and 0 <= (today_d - published).days <= RECENT_DAYS
        s.dated += published is not None
        s.recent += recent
        text = " ".join(v for v in (r.get("title"), r.get("description")) if isinstance(v, str))
        on_topic = matches_any(text, topic_terms)
        evidence = matches_any(text, cfg.evidence) or bool(VERSION_RE.search(text))
        hype = matches_any(text, cfg.hype)
        s.on_topic += on_topic
        s.evidence += evidence
        s.hype += hype
        s.candidates += on_topic and not hype and recent and (query.kind != "x" or kind == "post")
    s.x_authors = len(authors)
    return s


# ---- 実行 ----------------------------------------------------------------
def run_probe(cfg: BraveConfig, api_key: str, usage: dict | None, today: str, topic_terms: dict[str, list],
              known_urls: set[str], persist, sleep, search_fn=None) -> ProbeResult:
    """1日1回、上限内でBrave検索を実行して品質を集計する。usage は呼び出し側で保存できる辞書。

    persist(usage) は各リクエストの直前に呼ばれ、利用件数を先に記録する。
    """
    search_fn = search_fn or search
    if usage is None:
        return ProbeResult(status="usage_unreadable")
    if not cfg.queries:
        return ProbeResult(status="no_queries")
    if not api_key:
        return ProbeResult(status="no_api_key")
    used = requests_on(usage, today)
    if used > 0:
        return ProbeResult(status="already_ran" if used < cfg.daily_limit else "limit_reached")

    result = ProbeResult(status="ran")
    day = {"requests": 0, "queries": {}}
    usage[today] = day
    run_urls: set[str] = set()
    for i, query in enumerate(cfg.queries):
        stats = QueryStats(kind=query.kind, category=query.category)
        result.queries[query.id] = stats
        if day["requests"] >= cfg.daily_limit:  # load_brave とは独立した最終防衛線
            continue
        if i > 0:
            sleep(REQUEST_INTERVAL_SEC)
        day["requests"] += 1
        result.requests += 1
        persist(usage)  # リクエストの前に記録する
        try:
            results = search_fn(query, api_key)
        except Exception as e:  # 1件の失敗で全体を止めない。リトライしない。
            stats.status, stats.error = "failed", describe_error(e)
            result.failed += 1
        else:
            stats = evaluate(query, results, cfg, topic_terms.get(query.category, []), today, known_urls, run_urls)
            result.queries[query.id] = stats
        day["queries"][query.id] = {k: v for k, v in asdict(stats).items() if v not in ("", None)}
    persist(usage)
    return result


def format_result(result: ProbeResult) -> list[str]:
    lines = [f"Brave status: {result.status}", f"Brave API requests: {result.requests}",
             f"Brave failed requests: {result.failed}"]
    for qid, s in result.queries.items():
        detail = f" error={s.error}" if s.error else ""
        lines.append(
            f"  [{qid}] kind={s.kind} status={s.status}{detail} results={s.results} x_posts={s.x_posts} "
            f"x_profiles={s.x_profiles} x_other={s.x_other} non_x={s.non_x} x_authors={s.x_authors} "
            f"dated={s.dated} recent={s.recent} on_topic={s.on_topic} evidence={s.evidence} hype={s.hype} "
            f"candidates={s.candidates} duplicates={s.duplicates} official_overlap={s.official_overlap}")
    return lines


def summarize(usage: dict, today: str, days: int = 7) -> list[str]:
    """直近 days 日の集計（kind ごと）。X検索の取得精度の推移をActionsログで確認するため。"""
    oldest = (date.fromisoformat(today) - timedelta(days=days - 1)).isoformat()
    totals: dict[str, dict[str, int]] = {}
    requests = 0
    for d, entry in usage.items():
        if not (oldest <= d <= today):
            continue
        requests += requests_on(usage, d)
        for q in (entry.get("queries") or {}).values():
            if not isinstance(q, dict) or q.get("kind") not in KINDS:
                continue
            t = totals.setdefault(q["kind"], {})
            t["requests"] = t.get("requests", 0) + 1
            for key in ("results", "x_posts", "recent", "on_topic", "evidence", "hype", "candidates"):
                value = q.get(key, 0)
                t[key] = t.get(key, 0) + (value if isinstance(value, int) else 0)
            t["failed"] = t.get("failed", 0) + (q.get("status") == "failed")
    lines = [f"Brave last {days} days: requests={requests}"]
    pct = lambda n, total: f"{n / total:.0%}" if total else "-"  # noqa: E731
    for kind in KINDS:
        t = totals.get(kind)
        if not t:
            continue
        n = t["results"]
        lines.append(
            f"  kind={kind} queries={t['requests']} failed={t['failed']} results={n} "
            f"x_post_rate={pct(t['x_posts'], n)} recent_rate={pct(t['recent'], n)} on_topic_rate={pct(t['on_topic'], n)} "
            f"evidence_rate={pct(t['evidence'], n)} hype_rate={pct(t['hype'], n)} candidates={t['candidates']}")
    return lines
