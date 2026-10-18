"""収集処理で共通に使う小さな関数（news-watch の collect.py から流用）。外部APIは呼ばない。"""
from __future__ import annotations

import html
import re
import urllib.parse
from datetime import timedelta, timezone

JST = timezone(timedelta(hours=9))
USER_AGENT = "ai-watch/0.1 (+https://github.com/YanTKYS/ai-watch)"

# 記事の同一性に影響しないことが明らかなトラッキング用パラメータのみ除去する。
TRACKING_PARAMS = {
    "fbclid", "gclid", "gbraid", "wbraid", "yclid", "msclkid", "dclid",
    "mc_cid", "mc_eid", "igshid", "_hsenc", "_hsmi", "mkt_tok", "ref_src", "ref_url",
}
TRACKING_PREFIXES = ("utm_",)


class ConfigError(Exception):
    """設定・実行前提の異常（APIを呼ぶ前に停止させる）。"""


def normalize_url(url: object) -> str | None:
    """安全側の最小限の正規化。http(s)以外は None を返す。twitter.com は x.com に揃える。"""
    if not isinstance(url, str):
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    if host in ("twitter.com", "www.twitter.com", "mobile.twitter.com", "www.x.com", "mobile.x.com"):
        host = "x.com"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    query = urllib.parse.urlencode(
        [
            (k, v)
            for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
        ]
    )
    return urllib.parse.urlunsplit((scheme, host, path, query, ""))


def domain_of(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


_TAG_RE = re.compile(r"<[^>]*>")


def clean_text(text: object) -> str:
    """HTMLタグ・実体参照を除去し1行に整形する（Markdown見出しの誤認防止のため先頭の#も除く）。"""
    if not isinstance(text, str):
        return ""
    text = html.unescape(_TAG_RE.sub("", text))
    return " ".join(text.split()).lstrip("#> -").strip()


def term_pattern(term: str) -> re.Pattern:
    """英数字で始まる・終わる語は単語境界で、それ以外（日本語・記号）は部分一致で照合する（大文字小文字は区別しない）。"""
    escaped = re.escape(" ".join(term.split()))
    head = r"(?<![A-Za-z0-9])" if term[:1].isascii() and term[:1].isalnum() else ""
    tail = r"(?![A-Za-z0-9])" if term[-1:].isascii() and term[-1:].isalnum() else ""
    return re.compile(head + escaped + tail, re.IGNORECASE)


def compile_terms(value: object, name: str) -> list[re.Pattern]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(t, str) and t.strip() for t in value):
        raise ConfigError(f"{name} は空でない文字列のリストにしてください")
    return [term_pattern(t.strip()) for t in value]


def matches_any(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)
