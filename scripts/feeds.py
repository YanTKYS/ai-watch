"""公式の情報源（RSS 2.0 / Atom。GitHub Releases の releases.atom を含む）を取得・解析する。

- 1フィードにつきHTTPリクエストは1回（リトライ・ページングなし）。失敗したフィードは飛ばして続行する。
- 使うのはタイトル・URL・公開日だけ（本文・要約は保存しない）。
- DOCTYPE・ENTITY を含むXMLは解析しない（外部実体・実体展開の対策）。
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from common import JST, USER_AGENT, ConfigError, clean_text, compile_terms, normalize_url

MAX_FEEDS = 10  # 情報源を無理に増やさないための上限
MAX_ITEMS_PER_FEED = 30  # 1フィードから採用する記事数の上限（新しい順）
TIMEOUT_SEC = 20
MAX_RESPONSE_BYTES = 3_000_000
DEFAULT_MAX_AGE_DAYS = 7

ATOM = "{http://www.w3.org/2005/Atom}"
RDF_RSS = "{http://purl.org/rss/1.0/}"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


@dataclass
class Feed:
    name: str
    url: str
    category: str
    classify: bool = True
    require_terms: list[re.Pattern] = field(default_factory=list)
    title_prefix: str = ""
    exclude_title_patterns: list[re.Pattern] = field(default_factory=list)


@dataclass
class Entry:
    title: str
    url: str
    published: str  # YYYY-MM-DD（日本時間）


def load_feeds(value: object, category_ids: set[str]) -> list[Feed]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError("'feeds' はリストにしてください")
    if len(value) > MAX_FEEDS:
        raise ConfigError(f"フィードが上限を超えています: {len(value)} 件 (上限 {MAX_FEEDS} 件)")
    feeds: list[Feed] = []
    urls: set[str] = set()
    for f in value:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"].strip():
            raise ConfigError("各フィードに文字列の 'name' が必要です")
        name = f["name"].strip()
        normalized = normalize_url(f.get("url"))  # 検証・重複確認のみに使い、取得は設定どおりのURLで行う
        if not normalized:
            raise ConfigError(f"フィード '{name}' の url が不正です（http/https のみ）")
        if normalized in urls:
            raise ConfigError(f"フィードのURLが重複しています: {normalized}")
        urls.add(normalized)
        url = f["url"].strip()
        if f.get("category") not in category_ids:
            raise ConfigError(f"フィード '{name}' の category が categories にありません: {f.get('category')!r}")
        if "classify" in f and not isinstance(f["classify"], bool):
            raise ConfigError(f"フィード '{name}' の classify は true / false にしてください")
        prefix = f.get("title_prefix", "")
        if not isinstance(prefix, str):
            raise ConfigError(f"フィード '{name}' の title_prefix は文字列にしてください")
        patterns = f.get("exclude_title_patterns", [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
            raise ConfigError(f"フィード '{name}' の exclude_title_patterns は文字列のリストにしてください")
        try:
            compiled = [re.compile(p) for p in patterns]
        except re.error as e:
            raise ConfigError(f"フィード '{name}' の exclude_title_patterns が正規表現として不正です: {e}") from e
        feeds.append(Feed(name=name, url=url, category=f["category"], classify=f.get("classify", True),
                          require_terms=compile_terms(f.get("require_keywords"), f"フィード '{name}' の require_keywords"),
                          title_prefix=prefix.strip(),
                          exclude_title_patterns=compiled))
    return feeds


def fetch(url: str) -> bytes:
    """1回だけ取得する。失敗時は例外（リトライしない）。"""
    req = urllib.request.Request(url, headers={
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    return body


def parse_date(value: str | None) -> str | None:
    """RFC 822（RSS）・ISO 8601（Atom・dc:date）の日時を日本時間の YYYY-MM-DD にする。解釈できなければ None。"""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if dt.tzinfo is None:
        return dt.date().isoformat()
    return dt.astimezone(JST).date().isoformat()


def _text(node: ET.Element | None) -> str:
    return "".join(node.itertext()) if node is not None else ""


def _atom_link(entry: ET.Element) -> str:
    links = entry.findall(f"{ATOM}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href")
    return ""


def parse_feed(body: bytes) -> list[Entry]:
    """RSS 2.0 / RSS 1.0 (RDF) / Atom を解析する。タイトル・URL・日付のいずれかを欠く記事は除く。"""
    root_start = re.search(rb"<[A-Za-z]", body)  # 実体宣言はルート要素より前（DOCTYPE内）にしか書けない
    if root_start is None or b"<!doctype" in body[:root_start.start()].lower():
        raise ValueError("DOCTYPE is not allowed")
    root = ET.fromstring(body)
    raw: list[tuple[str, str, str | None]] = []
    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry"):
            when = _text(e.find(f"{ATOM}published")) or _text(e.find(f"{ATOM}updated"))
            raw.append((_text(e.find(f"{ATOM}title")), _atom_link(e), when))
    elif root.tag == "rss":
        for e in root.iter("item"):
            when = _text(e.find("pubDate")) or _text(e.find(DC_DATE))
            raw.append((_text(e.find("title")), _text(e.find("link")), when))
    elif root.tag.endswith("RDF"):
        for e in root.findall(f"{RDF_RSS}item"):
            raw.append((_text(e.find(f"{RDF_RSS}title")), _text(e.find(f"{RDF_RSS}link")), _text(e.find(DC_DATE))))
    else:
        raise ValueError("unknown feed format")
    entries = []
    for title, link, when in raw:
        title, url, published = clean_text(title), normalize_url(link.strip()), parse_date(when)
        if title and url and published:
            entries.append(Entry(title=title, url=url, published=published))
    return entries


def select_entries(feed: Feed, entries: list[Entry], today: str, max_age_days: int) -> list[Entry]:
    """除外パターン・公開日（max_age_days 以内、未来日は除く）で絞り、新しい順に上限件数まで返す。
    require_keywords による絞り込みは件数を分けて記録するため、呼び出し側で行う。"""
    oldest = (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()
    kept = [e for e in entries
            if oldest <= e.published <= today and not any(p.search(e.title) for p in feed.exclude_title_patterns)]
    kept.sort(key=lambda e: e.published, reverse=True)  # 安定ソート（同じ日はフィードの順）
    return kept[:MAX_ITEMS_PER_FEED]


def display_title(feed: Feed, title: str) -> str:
    """GitHub Releases の "v1.2.3" のようなタイトルに、製品名の接頭辞を付ける（既に含まれていれば付けない）。"""
    if feed.title_prefix and feed.title_prefix.lower() not in title.lower():
        return f"{feed.title_prefix} {title}"
    return title


def describe_error(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return type(e).__name__
