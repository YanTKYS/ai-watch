import gzip
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, SECRET, Base, FakeResponse, atom, block_network, collect, rss  # noqa: E402

import feeds  # noqa: E402
import search_index  # noqa: E402
import selection  # noqa: E402
from common import normalize_url  # noqa: E402

import yaml  # noqa: E402


def setUpModule():
    global _net
    _net = block_network()


def tearDownModule():
    _net.stop()


NEWS = "https://news.example.com/rss.xml"
CHANGELOG = "https://changelog.example.com/feed/"
RELEASES = "https://github.com/example/tool/releases.atom"


class UrlAndText(unittest.TestCase):
    def test_normalize_url(self):
        n = normalize_url
        self.assertEqual(n("https://Example.JP/a/b/#frag"), "https://example.jp/a/b")
        self.assertEqual(n("https://example.jp/a?utm_source=x&id=1&fbclid=z"), "https://example.jp/a?id=1")
        self.assertEqual(n("https://twitter.com/dev/status/1?s=20"), "https://x.com/dev/status/1?s=20")
        self.assertEqual(n("https://example.jp:443/a"), "https://example.jp/a")
        self.assertIsNone(n("javascript:alert(1)"))
        self.assertIsNone(n("https://example.jp:99999/"))
        self.assertIsNone(n(None))


class FeedParsing(unittest.TestCase):
    def test_rss_atom_and_rdf(self):
        r = feeds.parse_feed(rss(("GPT &amp; <b>API</b>", " https://news.example.com/a ", "Sat, 17 Oct 2026 23:30:00 GMT")))
        self.assertEqual([(e.title, e.url, e.published) for e in r],
                         [("GPT & API", "https://news.example.com/a", "2026-10-18")])  # 日本時間の日付
        a = feeds.parse_feed(atom(("v1.2.0", "https://github.com/example/tool/releases/tag/v1.2.0", "2026-10-17T01:00:00Z")))
        self.assertEqual([(e.title, e.url, e.published) for e in a],
                         [("v1.2.0", "https://github.com/example/tool/releases/tag/v1.2.0", "2026-10-17")])
        rdf = (b'<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
               b'xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
               b"<item><title>R</title><link>https://r.example.com/1</link><dc:date>2026-10-16T10:00:00+09:00</dc:date></item>"
               b"</rdf:RDF>")
        self.assertEqual([e.published for e in feeds.parse_feed(rdf)], ["2026-10-16"])

    def test_incomplete_entries_are_skipped(self):
        body = rss(("", "https://a.example.com/1", "Sat, 17 Oct 2026 00:00:00 GMT"),
                   ("no link", "", "Sat, 17 Oct 2026 00:00:00 GMT"),
                   ("bad link", "javascript:alert(1)", "Sat, 17 Oct 2026 00:00:00 GMT"),
                   ("no date", "https://a.example.com/2", ""),
                   ("ok", "https://a.example.com/3", "2026-10-17"))
        self.assertEqual([e.title for e in feeds.parse_feed(body)], ["ok"])

    def test_doctype_and_garbage_are_rejected(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
        for body in (bomb, b"not xml", b"<html><body>x</body></html>"):
            with self.assertRaises(Exception):
                feeds.parse_feed(body)

    def test_select_entries_window_exclusion_and_order(self):
        feed = feeds.Feed(name="T", url=RELEASES, category="coding", exclude_title_patterns=[
            __import__("re").compile(r"(?i)[-.](alpha|beta|rc)\b")])
        es = [feeds.Entry("v1.0.0", "https://x.example/1", "2026-10-11"),  # 7日前: 含む
              feeds.Entry("v0.9.0", "https://x.example/2", "2026-10-10"),  # 8日前: 除く
              feeds.Entry("v1.1.0-alpha.1", "https://x.example/3", "2026-10-17"),
              feeds.Entry("v1.1.0", "https://x.example/4", "2026-10-17"),
              feeds.Entry("search arc", "https://x.example/5", "2026-10-16"),  # "rc" を含む単語は除外しない
              feeds.Entry("future", "https://x.example/6", "2026-10-19")]
        got = feeds.select_entries(feed, es, "2026-10-18", 7)
        self.assertEqual([e.title for e in got], ["v1.1.0", "search arc", "v1.0.0"])

    def test_display_title(self):
        feed = feeds.Feed(name="T", url=RELEASES, category="coding", title_prefix="Claude Code")
        self.assertEqual(feeds.display_title(feed, "v2.1.0"), "Claude Code v2.1.0")
        self.assertEqual(feeds.display_title(feed, "claude code 2.1"), "claude code 2.1")


class Config(Base):
    def test_shipped_config_is_valid(self):
        config = collect.load_config(ROOT / "config" / "sources.yml")
        self.assertEqual([c.name for c in config.categories],
                         ["AIモデル", "AIコーディング", "AIエージェント", "MCP・連携技術", "API・料金・制限"])
        self.assertLessEqual(len(config.feeds), feeds.MAX_FEEDS)
        self.assertEqual(config.brave.daily_limit, 4)
        self.assertEqual([q.kind for q in config.brave.queries], ["x", "x", "web", "web"])  # X 2件・一般Web 2件
        self.assertTrue(all("site:x.com" in q.q for q in config.brave.queries if q.kind == "x"))

    def test_classification_priority(self):
        config = collect.load_config(self.config)
        self.assertEqual(collect.classify(config, "GPT API pricing update"), "api")  # classify_order が優先
        self.assertEqual(collect.classify(config, "Claude Code 2.0"), "coding")
        self.assertEqual(collect.classify(config, "Introducing Claude"), "models")
        self.assertIsNone(collect.classify(config, "RAPIDS release"))  # API は RAPIDS に一致しない
        self.assertIsNone(collect.classify(config, "ChatGPTs"))  # 英字は単語単位（GPT は ChatGPTs に一致しない）

    def bad(self, mutate):
        raw = yaml.safe_load(self.config_text)
        mutate(raw)
        self.config.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        code, out, err = self.run_collect()
        self.assertEqual(code, 2, err)
        self.assertEqual(self.calls, [])  # 設定異常ではどのAPIも呼ばない
        return err

    def test_invalid_configs_fail_without_any_request(self):
        def five_queries(r):
            r["brave"]["queries"] += [dict(r["brave"]["queries"][1], id=f"w{i}", q=f"q{i}") for i in range(3)]
        cases = [
            lambda r: r["brave"].update(daily_limit=5),  # 4 を超える上限は設定できない
            five_queries,  # 検索語が上限を超える（黙って切り捨てない）
            lambda r: r["brave"].update(daily_limit=1),  # 検索語2件 > 上限1件
            lambda r: r["brave"]["queries"][0].update(q="Claude Code"),  # kind: x なのに site:x.com がない
            lambda r: r["brave"]["queries"][0].update(kind="news"),
            lambda r: r["brave"]["queries"][1].update(id="x-coding"),
            lambda r: r["brave"]["queries"][1].update(freshness="yesterday"),
            lambda r: r["brave"]["queries"][1].update(category="unknown"),
            lambda r: r["feeds"][0].update(url="ftp://example.com/feed"),
            lambda r: r["feeds"][0].update(category="unknown"),
            lambda r: r["feeds"][1].update(url=r["feeds"][0]["url"]),
            lambda r: r["feeds"][2].update(exclude_title_patterns=["(unclosed"]),
            lambda r: r.update(feeds=[dict(r["feeds"][0], url=f"https://f{i}.example.com/") for i in range(11)]),
            lambda r: r.update(classify_order=["api", "unknown"]),
            lambda r: r.update(max_age_days=0),
            lambda r: r.update(categories=[]),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.calls.clear()
                self.bad(mutate)

    def test_corrupt_seen_json_fails_without_overwrite(self):
        self.seen.parent.mkdir(parents=True)
        self.seen.write_text("{broken", encoding="utf-8")
        code, _, err = self.run_collect()
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.seen.read_text(encoding="utf-8"), "{broken")


class CollectFeeds(Base):
    def setUp(self):
        super().setUp()
        self.feeds[NEWS] = rss(
            ("Introducing Example GPT model", "https://news.example.com/gpt?utm_source=rss", "Sat, 17 Oct 2026 01:00:00 GMT"),
            ("New API pricing", "https://news.example.com/pricing", "Fri, 16 Oct 2026 01:00:00 GMT"),
            ("Company update", "https://news.example.com/company", "Fri, 16 Oct 2026 02:00:00 GMT"),  # 該当なし→既定カテゴリ
            ("Old post", "https://news.example.com/old", "Mon, 05 Oct 2026 01:00:00 GMT"))
        self.feeds[CHANGELOG] = rss(
            ("Copilot code review is generally available", "https://changelog.example.com/1", "Sat, 17 Oct 2026 01:00:00 GMT"),
            ("Repository rulesets update", "https://changelog.example.com/2", "Sat, 17 Oct 2026 01:00:00 GMT"))  # require_keywords で除外
        self.feeds[RELEASES] = atom(
            ("v1.2.0", "https://github.com/example/tool/releases/tag/v1.2.0", "2026-10-17T10:00:00Z"),
            ("v1.3.0-beta.1", "https://github.com/example/tool/releases/tag/v1.3.0-beta.1", "2026-10-17T11:00:00Z"),
            ("API changes in v1.1.9", "https://github.com/example/tool/releases/tag/v1.1.9", "2026-10-15T10:00:00Z"))

    def test_log_format_categories_and_seen(self):
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.feed_calls()), 3)  # 1フィード1リクエスト
        text = self.log_text()
        self.assertTrue(text.startswith("# 2026年10月\n\n## 2026-10-18\n\n### AIモデル\n"))
        # 表示順は categories の順（AIモデル → AIコーディング → API・料金・制限）
        self.assertLess(text.index("### AIモデル"), text.index("### AIコーディング"))
        self.assertLess(text.index("### AIコーディング"), text.index("### API・料金・制限"))
        self.assertIn("#### Introducing Example GPT model\n\n- URL: https://news.example.com/gpt\n"
                      "- Source: news.example.com\n- Feed: News\n- Published: 2026-10-17\n- Retrieved: 2026-10-18\n", text)
        self.assertIn("#### Tool v1.2.0", text)
        self.assertIn("#### Tool API changes in v1.1.9", text)  # classify: false なのでAPIの語があっても coding
        api_section = text.split("### API・料金・制限", 1)[1]
        self.assertIn("New API pricing", api_section)
        self.assertNotIn("Tool API changes", api_section)
        self.assertIn("Company update", text.split("### AIモデル", 1)[1].split("\n### ", 1)[0])
        for absent in ("Old post", "Repository rulesets", "beta", "本文は保存しない", "リリースノート本文"):
            self.assertNotIn(absent, text)  # 古い記事・関係の薄い記事・プレリリース・本文は保存しない
        seen = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(len(seen), 6)
        self.assertEqual(seen["https://news.example.com/gpt"], {"first_seen": "2026-10-18"})
        self.assertEqual(json.loads(self.months.read_text(encoding="utf-8")), ["2026-10"])
        self.assertIn("new items: 6", out)
        self.assertIn("skipped (require_keywords): 1", out)

    def test_second_run_is_duplicate_and_leaves_log_untouched(self):
        self.run_collect(skip_brave=True)
        before = self.log_text()
        code, out, _ = self.run_collect(today="2026-10-19", skip_brave=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.log_text(), before)
        self.assertIn("new items: 0", out)
        self.assertIn("duplicate items: 6", out)

    def test_append_to_existing_day_new_day_and_new_month(self):
        self.run_collect(skip_brave=True)
        self.feeds[NEWS] = rss(("Claude model card", "https://news.example.com/c", "Sun, 18 Oct 2026 01:00:00 GMT"),
                               ("Gemini API quota", "https://news.example.com/q", "Sun, 01 Nov 2026 01:00:00 GMT"))
        self.run_collect(today="2026-10-18", skip_brave=True)
        text = self.log_text()
        self.assertEqual(text.count("## 2026-10-18"), 1)
        self.assertEqual(text.count("### AIモデル"), 1)
        self.assertIn("Claude model card", text.split("### AIモデル", 1)[1].split("\n### ", 1)[0])
        self.run_collect(today="2026-11-01", skip_brave=True)
        self.assertIn("Gemini API quota", self.log_text("2026-11"))
        self.assertEqual(json.loads(self.months.read_text(encoding="utf-8")), ["2026-11", "2026-10"])

    def test_one_failed_feed_does_not_stop_others_and_is_not_retried(self):
        self.feeds[NEWS] = urllib.error.HTTPError(NEWS, 500, "err", {}, None)
        self.feeds[CHANGELOG] = b"<html>not a feed</html>"
        code, out, _ = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.feed_calls()), 3)
        self.assertIn("failed feeds: 2 (News, Changelog)", out)
        self.assertIn("feed failed: feed='News' error=HTTP 500", out)
        self.assertIn("Tool v1.2.0", self.log_text())

    def test_all_failed_returns_error_but_keeps_existing_logs(self):
        self.run_collect(skip_brave=True)
        before = self.log_text()
        for url in (NEWS, CHANGELOG, RELEASES):
            self.feeds[url] = TimeoutError()
        code, _, err = self.run_collect(today="2026-10-19", env={})
        self.assertEqual(code, 1)
        self.assertIn("すべての取得が失敗しました", err)
        self.assertEqual(self.log_text(), before)

    def test_same_title_is_observed_but_saved(self):
        self.run_collect(skip_brave=True)
        self.feeds[NEWS] = rss(("Introducing Example GPT model!", "https://mirror.example.com/gpt", "Sun, 18 Oct 2026 01:00:00 GMT"))
        code, out, _ = self.run_collect(today="2026-10-19", skip_brave=True)
        self.assertIn("same-title items (observation only): 1", out)
        self.assertIn("https://mirror.example.com/gpt", self.log_text())

    def test_no_secret_in_outputs(self):
        code, out, err = self.run_collect()
        self.assertNotIn(SECRET, out + err + self.all_written_text())


class ShippedFeedsBase(Base):
    """出荷時の設定（7フィード）と、実際の配信形式を模した合成データ（tests/fixtures）を使うテストの共通部分。

    実サイトへの通信は行わない。実際のフィードの取得可否は、GitHub Actions での実行で確認する。
    """

    DEEPMIND = "https://deepmind.google/blog/rss.xml"
    FIXTURES = {
        "https://openai.com/news/rss.xml": "openai_news.xml",
        "https://deepmind.google/blog/rss.xml": "deepmind_blog.xml",
        "https://github.blog/changelog/feed/": "github_changelog.xml",
        "https://github.com/anthropics/claude-code/releases.atom": "claude_code_releases.atom",
        "https://github.com/openai/codex/releases.atom": "codex_releases.atom",
        "https://github.com/modelcontextprotocol/modelcontextprotocol/releases.atom": "mcp_spec_releases.atom",
        "https://github.com/anthropics/anthropic-sdk-python/releases.atom": "anthropic_sdk_releases.atom",
    }

    config_text = (ROOT / "config" / "sources.yml").read_text(encoding="utf-8")

    def run_with_deepmind(self, value):
        """DeepMind だけ value を返し、他のフィードは合成データを返す。DeepMind だけが失敗することを確認する。"""
        fixtures = ROOT / "tests" / "fixtures"
        self.feeds = {url: (fixtures / name).read_bytes() for url, name in self.FIXTURES.items()}
        self.feeds[self.DEEPMIND] = value
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn("failed feeds: 1 (Google DeepMind News)", out)  # 他のフィードは成功
        self.assertEqual(out.count("feed ok: "), len(self.FIXTURES) - 1)
        self.assertIn("Claude Code v9.9.2", self.log_text())
        diag = [line for line in out.splitlines() if line.startswith("  diagnostics: ")]
        self.assertEqual(len(diag), 1)
        for line in out.splitlines():  # 外部由来の文字列でActionsのワークフローコマンドを発生させない
            self.assertFalse(line.startswith("::") and not line.startswith(("::warning::feed failed", "::warning::BRAVE")), line)
        return out, diag[0]


class ShippedFeedFormats(ShippedFeedsBase):
    def test_shipped_feeds_parse_and_classify(self):
        fixtures = ROOT / "tests" / "fixtures"
        self.feeds = {url: (fixtures / name).read_bytes() for url, name in self.FIXTURES.items()}
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.feed_calls()), sorted(self.FIXTURES))  # 設定のURLどおりに1回ずつ取得
        self.assertIn("failed feeds: 0", out)
        days = {}
        for a in search_index.parse_log(self.log_text()):
            days.setdefault(a["category"], []).append((a["feed"], a["title"], a["url"], a["published"]))
        self.assertEqual(days, {
            "AIモデル": [
                ("OpenAI News", "Fixture: Introducing an example GPT model", "https://openai.com/index/fixture-gpt-model", "2026-10-18"),
                ("OpenAI News", "Fixture: Example research update",  # タイトルでは判断できず、説明文の技術情報で採用
                 "https://openai.com/index/fixture-research-update", "2026-10-16"),
                ("Google DeepMind News", "Fixture: Gemini 9 example model is now available",
                 "https://deepmind.google/discover/blog/fixture-gemini-update", "2026-10-15"),
            ],
            "AIコーディング": [
                ("GitHub Changelog", "Fixture: Copilot coding agent supports example setting",
                 "https://github.blog/changelog/2026-10-17-fixture-copilot-agent", "2026-10-18"),
                ("Claude Code Releases", "Claude Code v9.9.2", "https://github.com/anthropics/claude-code/releases/tag/v9.9.2", "2026-10-18"),
                ("OpenAI Codex Releases", "Codex 9.8.0", "https://github.com/openai/codex/releases/tag/rust-v9.8.0", "2026-10-17"),
            ],
            "MCP・連携技術": [
                ("MCP Specification Releases", "MCP 2026-10-15",
                 "https://github.com/modelcontextprotocol/modelcontextprotocol/releases/tag/2026-10-15", "2026-10-15"),
                ("Anthropic SDK Releases", "Anthropic Python SDK v9.2.0",
                 "https://github.com/anthropics/anthropic-sdk-python/releases/tag/v9.2.0", "2026-10-17"),
            ],
            "API・料金・制限": [
                ("OpenAI News", "Fixture: API pricing update for example models", "https://openai.com/index/fixture-api-pricing", "2026-10-17"),
            ],
        })
        text = self.log_text()
        for absent in ("old research", "Dependabot", "REST API", "alpha", "rc.1", "Synthetic", "Example Corp",
                       "law firm", "science collaboration", "v9.9.1", "v9.1.1", "example setting\n- Fixed"):
            self.assertNotIn(absent, text)  # 古い記事・AI以外・導入事例・修正のみのリリース・本文は保存しない
        # リリースは項目数だけを添える（リリースノートの文章は保存しない）
        self.assertIn("#### Claude Code v9.9.2\n\n- URL: https://github.com/anthropics/claude-code/releases/tag/v9.9.2\n"
                      "- Source: github.com\n- Feed: Claude Code Releases\n"
                      "- Notes: 新機能 1 / 変更・改善 1 / 破壊的変更・廃止 0 / 修正 2\n", text)
        self.assertIn("- Notes: 新機能 1 / 変更・改善 0 / 破壊的変更・廃止 0 / 修正 1\n", text)  # Codex（見出しで分類）
        self.assertNotIn("Notes", text.split("#### MCP 2026-10-15", 1)[1].split("####", 1)[0])  # 判定できない場合は付けない
        # 不採用の理由はActionsログと seen.json に残る
        seen = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(seen["https://openai.com/index/fixture-example-corp"]["excluded"], "customer_story")
        self.assertEqual(seen["https://openai.com/index/fixture-law-firm"]["excluded"], "low_score")
        self.assertEqual(seen["https://deepmind.google/discover/blog/fixture-science"]["excluded"], "partnership")
        self.assertEqual(seen["https://github.com/anthropics/claude-code/releases/tag/v9.9.1"]["excluded"], "fixes_only")
        self.assertEqual(seen["https://github.com/anthropics/anthropic-sdk-python/releases/tag/v9.1.1"]["excluded"], "fixes_only")
        self.assertIn("rejected by selection: 5 (fixes_only=2, customer_story=1, low_score=1, partnership=1)", out)
        self.assertIn("- rejected [customer_story] score=-3 (customer_story-3): How Example Corp scales support with ChatGPT", out)
        self.assertIn("'Customer Story': 1", out)  # フィードが付けたカテゴリ（in: categories の規則を作る参考）


class FeedDiagnostics(ShippedFeedsBase):
    """取得・解析に失敗したフィードの診断情報（v0.1.1）。他のフィードには影響しない。"""

    def test_html_response_reports_status_type_and_position(self):
        # DOCTYPE付きのHTMLは安全対策で先に拒否される（ValueError）。ParseError になるのは DOCTYPE なしのHTMLなど
        html = (b'<html lang="en">\n<head><meta charset="utf-8"><title>Blog</title></head>\n'
                b"<body>" + b"x" * 5000 + b"SECRET-FAR-FROM-ERROR</body></html>")
        out, diag = self.run_with_deepmind((html, {"Content-Type": "text/html; charset=utf-8"}))
        self.assertIn("error=ParseError", out)
        self.assertIn('status=200 content_type="text/html; charset=utf-8"', diag)
        self.assertIn(f"bytes={len(html)}", diag)
        self.assertIn('final_url="https://deepmind.google/blog/rss.xml"', diag)
        self.assertIn('start=html first_element="html"', diag)
        self.assertRegex(diag, r'parse_error="mismatched tag: line 2, column \d+"')
        self.assertNotIn("SECRET-FAR-FROM-ERROR", out)  # 本文全体は出さない
        context = diag.split("context=", 1)[1]
        self.assertLessEqual(len(context), 2 * 30 + 2 + 20)

    def test_doctype_html_is_still_rejected_before_parsing(self):
        out, diag = self.run_with_deepmind(b"<!DOCTYPE html><html><body>x</body></html>")
        self.assertIn("error=ValueError", out)
        self.assertIn('start=html', diag)
        self.assertIn('message="DOCTYPE is not allowed"', diag)

    def test_xml_variants_are_distinguishable(self):
        cases = [
            (b"\n\n  <?xml version=\"1.0\"?><rss><channel></channel></rss>", "start=xml-declaration", "leading_whitespace=4"),
            (b'<?xml version="1.0"?><rss><channel><item><title>A&nbsp;B</title></item></channel></rss>',
             "undefined entity", 'first_element="rss"'),
            (b"\x1f\x8b\x08\x00binary", "start=gzip", "bom=no"),
            (b"", "start=empty", "bytes=0"),
        ]
        for body, *needles in cases:
            with self.subTest(body=body[:20]):
                self.setUp()
                _, diag = self.run_with_deepmind((body, {"Content-Type": "application/rss+xml"}))
                for needle in needles:
                    self.assertIn(needle, diag)

    def test_injection_in_context_is_escaped(self):
        body = b'<?xml version="1.0"?><rss>\n::error::injected <bad & </rss>'
        _, diag = self.run_with_deepmind(body)
        self.assertIn("::error::injected", diag)  # 行頭ではないのでコマンドとして解釈されない
        self.assertNotIn("\n", diag)

    def test_http_error_reports_status_and_type(self):
        import email.message
        headers = email.message.Message()
        headers["Content-Type"] = "text/html"
        err = urllib.error.HTTPError(self.DEEPMIND, 403, "Forbidden", headers, None)
        out, diag = self.run_with_deepmind(err)
        self.assertIn("error=HTTP 403", out)
        self.assertIn('status=403 content_type="text/html"', diag)


class GzipFeeds(ShippedFeedsBase):
    """Content-Encoding: gzip のフィード（v0.1.2。Google DeepMind News が gzip で配信していた）。"""

    GZIP = {"Content-Type": "application/xml", "Content-Encoding": "gzip"}

    def deepmind_xml(self):
        return (ROOT / "tests" / "fixtures" / "deepmind_blog.xml").read_bytes()

    def test_gzip_rss_is_decoded_and_saved(self):
        fixtures = ROOT / "tests" / "fixtures"
        self.feeds = {url: (fixtures / name).read_bytes() for url, name in self.FIXTURES.items()}
        compressed = gzip.compress(self.deepmind_xml())
        self.feeds[self.DEEPMIND] = (compressed, self.GZIP)
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn("failed feeds: 0", out)
        self.assertEqual(out.count("feed ok: "), len(self.FIXTURES))
        self.assertIn(f"feed ok: feed='Google DeepMind News' status=200 content_type=\"application/xml\" "
                      f"content_encoding=\"gzip\" bytes={len(compressed)} decoded_bytes={len(self.deepmind_xml())} "
                      f"entries=2", out)
        self.assertIn("content_encoding=\"\" bytes=", out)  # 非圧縮のフィードは従来どおり
        text = self.log_text()
        self.assertIn("Fixture: Gemini 9 example model is now available", text)
        self.assertIn("- Feed: Google DeepMind News", text)

    def test_decode_body_variants(self):
        xml = self.deepmind_xml()
        cases = [("", xml), ("identity", xml), ("gzip", gzip.compress(xml)), ("x-gzip", gzip.compress(xml)),
                 ("GZIP", gzip.compress(xml)), ("gzip", gzip.compress(xml[:100]) + gzip.compress(xml[100:]))]  # 複数メンバー
        for encoding, body in cases:
            with self.subTest(encoding=encoding):
                info = feeds.FetchInfo(content_encoding=encoding)
                self.assertEqual(feeds.decode_body(body, info), xml)
                self.assertEqual(info.decoded_size, len(xml))

    def test_corrupt_gzip_fails_only_that_feed(self):
        compressed = gzip.compress(self.deepmind_xml())
        for name, body, errors in [
                ("corrupt", compressed[:10] + b"\x00" * 20 + compressed[30:], ("error=zlib.error", "while decompressing data", "start=gzip")),
                ("truncated", compressed[:-20], ("error=ValueError", 'message="truncated gzip data"', "start=gzip")),
                ("not gzip", self.deepmind_xml(), ("error=zlib.error", "incorrect header check", "start=xml-declaration"))]:
            with self.subTest(name=name):
                self.setUp()
                out, diag = self.run_with_deepmind((body, self.GZIP))  # 他の5フィードは成功
                self.assertIn('content_encoding="gzip"', diag)
                self.assertIn("decoded_bytes=-", diag)
                for needle in errors:
                    self.assertIn(needle, out + diag)

    def test_decoded_size_limit(self):
        bomb = gzip.compress(b"<rss>" + b" " * 2_000_000 + b"</rss>")  # 圧縮後は数KB
        self.assertLess(len(bomb), 10_000)
        with mock.patch.object(feeds, "MAX_DECODED_BYTES", 1_000_000):
            out, diag = self.run_with_deepmind((bomb, self.GZIP))
        self.assertIn("error=ValueError", out)
        self.assertIn('message="decompressed response too large"', diag)
        with mock.patch.object(feeds, "MAX_DECODED_BYTES", len(self.deepmind_xml())):  # ちょうど上限は許可
            info = feeds.FetchInfo(content_encoding="gzip")
            self.assertEqual(feeds.decode_body(gzip.compress(self.deepmind_xml()), info), self.deepmind_xml())

    def test_compressed_size_limit(self):
        # 受信データ（圧縮データ）の上限は展開前に判定する（他のフィードに影響させないよう fetch 単体で確認）
        compressed = gzip.compress(self.deepmind_xml())
        response = FakeResponse(compressed, headers=self.GZIP, url=self.DEEPMIND)
        for limit, ok in ((len(compressed), True), (len(compressed) - 1, False)):
            info = feeds.FetchInfo()
            with self.subTest(limit=limit), mock.patch.object(feeds, "MAX_RESPONSE_BYTES", limit), \
                    mock.patch("urllib.request.urlopen", return_value=response):
                if ok:
                    self.assertEqual(feeds.fetch(self.DEEPMIND, info), compressed)
                else:
                    with self.assertRaisesRegex(ValueError, "response too large"):
                        feeds.fetch(self.DEEPMIND, info)
                self.assertEqual((info.content_encoding, info.size), ("gzip", len(compressed)))

    def test_doctype_is_rejected_after_decoding(self):
        body = gzip.compress(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rss><channel></channel></rss>')
        out, diag = self.run_with_deepmind((body, self.GZIP))
        self.assertIn('message="DOCTYPE is not allowed"', diag)
        self.assertIn("start=xml-declaration", diag)  # 展開後の本文で診断する

    def test_unsupported_encoding_fails(self):
        out, diag = self.run_with_deepmind((b"\x8b\x00compressed", {"Content-Encoding": "br"}))
        self.assertIn('message="unsupported content encoding: br"', diag)


# 2026-10-18 の初回収集で実際にログに入った OpenAI News・Google DeepMind News の記事（タイトルのみで判定）と、
# v0.1.3 の評価（PRに記載）。True=残す。
REAL_NEWS_2026_10_18 = [
    ("Google DeepMind and Singapore Government collaborate to build fine-tuned AI model for scam detection", False),
    ("Developing Gemini 4 Argon responsibly and safely", False),
    ("Gemini 4 Argon for Robotics", True),
    ("Gemini 4 Argon: Built to solve your hardest problems", True),
    ("Accelerating the search for antimicrobial peptides with Google Antigravity", False),
    ("Higgsfield takes AI video from 1 minute to over 10", False),
    ("SentinelOne cuts malware analysis from weeks to hours", False),
    ("How Block is building AI-powered security with OpenAI technology", False),
    ("Amp puts AI agents to work beyond code with OpenAI models", False),
    ("How Third Moment Research runs 10,000 agents for 36+ hours", False),
    ("The EU’s next chapter in AI is agentic", False),
    ("Teaching students to think and learn through questions", False),
    ("Sullivan & Cromwell brings legal expertise into agreement review", False),
    ("Bringing GPT-Rosalind to academic research labs", False),
    ("Benefit Street Partners answers questions faster with Codex", False),
    ("Stack Overflow for Agents triples signups with ChatGPT plugin", False),
    ("How Itaú is building generative AI for its entire customer base", False),
]


class Selection(ShippedFeedsBase):
    """v0.1.3 の記事選定（出荷時の設定で確認）。"""

    def sel(self):
        return collect.load_config(ROOT / "config" / "sources.yml").selection

    def adopted(self, title, summary=""):
        points, _ = selection.score(self.sel(), title, summary)
        return points >= self.sel().min_score

    def test_real_titles_from_first_collection(self):
        for title, keep in REAL_NEWS_2026_10_18:
            with self.subTest(title=title):
                self.assertEqual(self.adopted(title), keep)

    def test_technical_signals_win_over_story_signals(self):
        # 技術的な発表・機能更新は採用し、導入事例でも実装・検証の中身が分かるものは残す（単語1つで除外しない）
        for title in ("Introducing GPT-5.5", "GPT-5.5 system card", "New tools for building agents",
                      "Codex is now generally available", "Pricing changes for the API",
                      "Upcoming deprecation of GPT-4.5 Preview in the API",
                      "How Notion built its agent harness on the Responses API",
                      "Gemini Robotics 1.5 brings AI agents into the physical world"):
            self.assertTrue(self.adopted(title), title)
        for title in ("Introducing ChatGPT Edu", "Our approach to AI and elections", "OpenAI and Example partner on AI"):
            self.assertFalse(self.adopted(title), title)
        # AIの単語が含まれるだけでは採用しない
        self.assertFalse(self.adopted("AI is changing how teams work"))
        # 説明文は、タイトルで判断できない記事の補助（導入事例の説明に出る一般語では加点しない）
        self.assertTrue(self.adopted("An update", "We report benchmark results and the architecture."))
        self.assertFalse(self.adopted("A law firm reviews contracts faster", "Built with the OpenAI API and GPT-5."))

    def test_release_note_classification(self):
        c = selection.release_counts
        claude = ("<ul><li>Added X</li><li>Improved artifacts: Y</li><li>[VSCode] Fixed Z</li>"
                  "<li>Windows: Fixed W</li><li>Removed the --old flag</li><li>Reverted V</li></ul>")
        self.assertEqual(c(claude), {"feature": 1, "change": 2, "breaking": 1, "fix": 2, "chore": 0, "other": 0})
        stainless = ("<h3>Features</h3><ul><li><strong>api:</strong> add speed</li></ul>"
                     "<h3>Bug Fixes</h3><ul><li><strong>client:</strong> close streams</li></ul>"
                     "<h3>Chores</h3><ul><li><strong>ci:</strong> speed up</li></ul>")
        self.assertEqual(c(stainless), {"feature": 1, "change": 0, "breaking": 0, "fix": 1, "chore": 1, "other": 0})
        conventional = "## Merged PRs\n- feat(tui): add X\n- feat!: drop Y\n- fix: Z\n- chore(deps): bump W\n"
        self.assertEqual(c(conventional), {"feature": 1, "change": 0, "breaking": 1, "fix": 1, "chore": 1, "other": 0})
        v = selection.release_verdict
        self.assertEqual(v(c("<ul><li>Fixed A</li><li>Fixed B</li></ul>")), "minor")
        self.assertEqual(v(c("<h2>Chores</h2><ul><li>bump deps</li></ul>")), "minor")
        self.assertEqual(v(c("")), "unknown")  # リリースノートが無い・判定できない場合は見落とさないよう採用
        self.assertEqual(v(c("<p>See the changelog.</p><ul><li>Fixed A</li></ul>")), "unknown")
        self.assertEqual(v(c(claude)), "notable")

    def run_feeds(self, mapping, today="2026-10-18"):
        fixtures = ROOT / "tests" / "fixtures"
        self.feeds = {url: (fixtures / name).read_bytes() for url, name in self.FIXTURES.items()}
        self.feeds.update(mapping)
        return self.run_collect(today=today, skip_brave=True)

    def test_multiple_notable_releases_become_one_entry(self):
        body = atom(*[(f"v9.9.{i}", f"https://github.com/anthropics/claude-code/releases/tag/v9.9.{i}",
                       f"2026-10-{12 + i}T21:00:00Z") for i in (5, 4, 3)],
                    content="<ul><li>Added A</li><li>Fixed B</li></ul>")
        code, out, err = self.run_feeds({"https://github.com/anthropics/claude-code/releases.atom": body})
        self.assertEqual(code, 0, err)
        text = self.log_text()
        self.assertEqual(text.count("#### Claude Code"), 1)
        self.assertIn("#### Claude Code v9.9.5（v9.9.3 以降の 3 リリース）\n\n"
                      "- URL: https://github.com/anthropics/claude-code/releases/tag/v9.9.5", text)
        self.assertIn("- Notes: 新機能 3 / 変更・改善 0 / 破壊的変更・廃止 0 / 修正 3\n", text)
        seen = json.loads(self.seen.read_text(encoding="utf-8"))
        for i in (4, 3):  # まとめたリリースも記録し、次回以降に個別に出さない
            self.assertEqual(seen[f"https://github.com/anthropics/claude-code/releases/tag/v9.9.{i}"],
                             {"first_seen": "2026-10-18", "grouped_into": "https://github.com/anthropics/claude-code/releases/tag/v9.9.5"})
        code, out, _ = self.run_feeds({"https://github.com/anthropics/claude-code/releases.atom": body}, today="2026-10-19")
        self.assertIn("new items: 0", out)

    def test_too_many_articles_in_one_day(self):
        titles = [f"Introducing GPT-9.{i}" for i in range(4)] + [f"New agents feature {i}" for i in range(4)]
        body = rss(*[(t, f"https://openai.com/index/many-{i}", "Sat, 17 Oct 2026 01:00:00 GMT") for i, t in enumerate(titles)])
        code, out, err = self.run_feeds({"https://openai.com/news/rss.xml": body})
        self.assertEqual(code, 0, err)
        text = self.log_text()
        self.assertEqual(sum(f"https://openai.com/index/many-{i}\n" in text for i in range(8)), 5)  # 上限 max_new_per_feed
        self.assertTrue(all(f"Introducing GPT-9.{i}" in text for i in range(4)))  # 点数の高い順に残る
        self.assertIn("over_limit=3", out)
        seen = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(sum(v.get("excluded") == "over_limit" for v in seen.values()), 3)

    def test_day_with_no_adopted_articles(self):
        empty = rss()
        stories = rss(("How Example Corp scales support with ChatGPT", "https://openai.com/index/story",
                       "Sat, 17 Oct 2026 01:00:00 GMT"))
        mapping = {url: empty for url in self.FIXTURES}
        mapping["https://openai.com/news/rss.xml"] = stories
        code, out, err = self.run_feeds(mapping)
        self.assertEqual(code, 0, err)
        self.assertFalse((self.logs / "2026" / "2026-10.md").exists())  # 0件の日はログを書かない
        self.assertEqual(json.loads(self.months.read_text(encoding="utf-8")), [])
        self.assertIn("new items: 0", out)
        seen = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(seen, {"https://openai.com/index/story": {"first_seen": "2026-10-18", "excluded": "customer_story"}})
        code, out, _ = self.run_feeds(mapping, today="2026-10-19")  # 翌日も同じ記事が配信されている
        self.assertIn("duplicate items: 1", out)  # 再判定せず、復活しない
        self.assertIn("rejected by selection: 0", out)

    def test_invalid_selection_config_fails_without_request(self):
        raw = yaml.safe_load(self.config_text)
        for mutate in (lambda r: r["feeds"][0].update(select="smart"),
                       lambda r: r["selection"].update(min_score="2"),
                       lambda r: r["selection"]["rules"].append({"label": "x", "weight": 0, "terms": ["a"]}),
                       lambda r: r["selection"]["rules"].append({"label": "x", "weight": 1, "in": "body", "terms": ["a"]}),
                       lambda r: r["selection"]["rules"].append({"label": "x", "weight": 1}),
                       lambda r: r["selection"]["rules"].append({"label": "x", "weight": 1, "patterns": ["("]})):
            with self.subTest(mutate=mutate):
                broken = yaml.safe_load(yaml.safe_dump(raw))
                mutate(broken)
                self.config.write_text(yaml.safe_dump(broken, allow_unicode=True), encoding="utf-8")
                self.calls.clear()
                code, _, err = self.run_collect(skip_brave=True)
                self.assertEqual(code, 2, err)
                self.assertEqual(self.calls, [])


class RepoLayout(unittest.TestCase):
    def workflow(self, name):
        return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))

    def test_collect_workflow_triggers_schedule_and_secrets(self):
        wf = self.workflow("collect.yml")
        triggers = wf.get(True, wf.get("on"))  # PyYAMLは 'on' を True と解釈する
        self.assertEqual(set(triggers), {"schedule", "workflow_dispatch"})
        self.assertEqual(wf["permissions"], {"contents": "write"})
        self.assertEqual(triggers["schedule"], [{"cron": "41 21 * * *"}])  # 1日1回
        self.assertNotEqual(triggers["schedule"][0]["cron"], "17 22 * * *")  # news-watch と時刻をずらす
        steps = wf["jobs"]["collect"]["steps"]
        with_env = [s for s in steps if "env" in s]
        self.assertEqual([s["name"] for s in with_env], ["Collect"])  # Secretは収集ステップだけに渡す
        self.assertEqual(set(with_env[0]["env"]), {"BRAVE_API_KEY", "SKIP_BRAVE"})
        text = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
        self.assertNotIn("JEV_API_KEY", text)  # v0.1.0 では Jev・Gemini を使わない
        self.assertNotIn("GEMINI_API_KEY", text)
        names = [s.get("name") for s in steps]
        commit = steps[names.index("Commit and push if there are changes")]
        self.assertEqual(commit["if"], "${{ !cancelled() }}")  # 取得の一部が失敗しても利用件数は記録する
        self.assertIn("data/brave-usage.json", commit["run"])

    def test_no_pull_request_target_and_test_workflow_has_no_secrets(self):
        for p in (ROOT / ".github" / "workflows").glob("*.yml"):
            wf = yaml.safe_load(p.read_text(encoding="utf-8"))
            self.assertNotIn("pull_request_target", wf.get(True, wf.get("on")), p.name)
        self.assertNotIn("secrets.", (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))

    def test_actions_use_node24_versions(self):
        # Node.js 20 で動く旧版（checkout@v4・setup-python@v5・setup-node@v4）を使わない。v7 はいずれも node24
        expected = {"actions/checkout": "v7", "actions/setup-python": "v7", "actions/setup-node": "v7"}
        for name in ("collect.yml", "test.yml"):
            for step in self.workflow(name)["jobs"][next(iter(self.workflow(name)["jobs"]))]["steps"]:
                if "uses" in step:
                    action, _, version = step["uses"].partition("@")
                    self.assertEqual(version, expected[action], (name, step["uses"]))

    def test_no_weekly_monthly_or_external_ai_calls(self):
        names = {p.name for p in (ROOT / "scripts").glob("*.py")}
        self.assertEqual(names, {"collect.py", "feeds.py", "brave.py", "common.py", "search_index.py", "selection.py"})
        code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "scripts").glob("*.py"))
        for needle in ("typesafe.ai", "generativelanguage", "JEV_API_KEY", "GEMINI_API_KEY"):
            self.assertNotIn(needle, code)
        self.assertFalse((ROOT / "reviews").exists())

    def test_initial_data_files(self):
        self.assertEqual(json.loads((ROOT / "data" / "months.json").read_text(encoding="utf-8")),
                         collect.list_months(ROOT / "logs"))
        seen = json.loads((ROOT / "data" / "seen.json").read_text(encoding="utf-8"))
        self.assertIsInstance(seen, dict)
        self.assertFalse(any("example.com" in u for u in seen))  # サンプルデータを本番データに混ぜない


if __name__ == "__main__":
    unittest.main()
