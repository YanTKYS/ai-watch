"""テスト共通の補助。実APIへの通信は一切行わない（urllib.request.urlopen をすべて差し替える）。"""
import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402

SECRET = "dummy-key-for-tests"  # 実キーではないテスト用ダミー値


def block_network():
    """モジュール全体で、差し替え忘れの通信を失敗させる。"""
    def deny(*a, **k):
        raise AssertionError("network access is not allowed in tests")
    patcher = mock.patch("urllib.request.urlopen", side_effect=deny)
    patcher.start()
    return patcher


class FakeResponse:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def rss(*items):
    """items: (title, link, pubDate)"""
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>本文は保存しない</description></item>"
                   for t, l, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode("utf-8")


def atom(*entries):
    """entries: (title, href, updated)"""
    body = "".join(f'<entry><title>{t}</title><link rel="alternate" type="text/html" href="{h}"/>'
                   f"<updated>{u}</updated><content type=\"html\">リリースノート本文</content></entry>"
                   for t, h, u in entries)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>{body}</feed>'.encode("utf-8")


def brave_payload(*results):
    return {"web": {"results": list(results)}}


def result(url, title="title", description="", **extra):
    return {"url": url, "title": title, "description": description, **extra}


CONFIG = """
categories:
  - id: models
    name: AIモデル
    keywords: [GPT, Claude, Gemini, model]
  - id: coding
    name: AIコーディング
    keywords: [Claude Code, Codex, Copilot]
  - id: api
    name: API・料金・制限
    keywords: [API, pricing]
classify_order: [api, coding, models]
feeds:
  - name: News
    url: https://news.example.com/rss.xml
    category: models
  - name: Changelog
    url: https://changelog.example.com/feed/
    category: coding
    require_keywords: [Copilot, Codex]
  - name: Tool Releases
    url: https://github.com/example/tool/releases.atom
    category: coding
    classify: false
    title_prefix: Tool
    exclude_title_patterns: ['(?i)[-.](alpha|beta|rc)\\b']
max_age_days: 7
brave:
  daily_limit: 4
  queries:
    - id: x-coding
      kind: x
      category: coding
      q: 'site:x.com "Claude Code"'
    - id: web-api
      kind: web
      category: api
      q: 'OpenAI API pricing'
      freshness: pw
quality:
  evidence_terms: [changelog, benchmark, 検証]
  hype_terms: [insane, 最強]
"""


class Base(unittest.TestCase):
    """一時ディレクトリに設定・データを置き、collect.run を通信なしで実行する。"""

    config_text = CONFIG

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.config = self.dir / "sources.yml"
        self.config.write_text(self.config_text, encoding="utf-8")
        self.seen = self.dir / "data" / "seen.json"
        self.logs = self.dir / "logs"
        self.months = self.dir / "data" / "months.json"
        self.usage = self.dir / "data" / "brave-usage.json"
        self.feeds = {}  # url -> bytes | Exception
        self.brave = {}  # 検索語(q) -> payload | Exception
        self.calls = []

    def responder(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        if url.startswith("https://api.search.brave.com/"):
            self.assertEqual(req.get_header("X-subscription-token"), SECRET)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"][0]
            value = self.brave.get(q, brave_payload())  # 検索語 -> 応答
        else:
            value = self.feeds.get(url, rss())
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)

    def run_collect(self, today="2026-10-18", env=None, skip_brave=False):
        env = {"BRAVE_API_KEY": SECRET} if env is None else env
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=self.responder), \
                redirect_stdout(out), redirect_stderr(err):
            code = collect.run(self.config, self.seen, self.logs, self.months, self.usage, today, env,
                               skip_brave=skip_brave, sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def brave_calls(self):
        return [u for u in self.calls if u.startswith("https://api.search.brave.com/")]

    def feed_calls(self):
        return [u for u in self.calls if not u.startswith("https://api.search.brave.com/")]

    def log_text(self, ym="2026-10"):
        return (self.logs / ym[:4] / f"{ym}.md").read_text(encoding="utf-8")

    def all_written_text(self):
        """収集処理が書き出したファイル（data/・logs/）の内容。"""
        files = [p for d in (self.dir / "data", self.logs) if d.exists() for p in d.rglob("*") if p.is_file()]
        return "\n".join(p.read_text(encoding="utf-8") for p in files)
