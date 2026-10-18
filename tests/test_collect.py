import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, SECRET, Base, atom, block_network, collect, rss  # noqa: E402

import feeds  # noqa: E402
import search_index  # noqa: E402
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


class ShippedFeedFormats(Base):
    """出荷時の設定（6フィード）を、実際の配信形式を模した合成データ（tests/fixtures）で通しで確認する。

    実サイトへの通信は行わない。実際のフィードの取得可否は、GitHub Actions での実行で確認する。
    """

    FIXTURES = {
        "https://openai.com/news/rss.xml": "openai_news.xml",
        "https://deepmind.google/blog/rss.xml": "deepmind_blog.xml",
        "https://github.blog/changelog/feed/": "github_changelog.xml",
        "https://github.com/anthropics/claude-code/releases.atom": "claude_code_releases.atom",
        "https://github.com/openai/codex/releases.atom": "codex_releases.atom",
        "https://github.com/modelcontextprotocol/modelcontextprotocol/releases.atom": "mcp_spec_releases.atom",
    }

    config_text = (ROOT / "config" / "sources.yml").read_text(encoding="utf-8")

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
                ("Google DeepMind News", "Fixture: Gemini example model card update",
                 "https://deepmind.google/discover/blog/fixture-gemini-update", "2026-10-15"),
                ("Google DeepMind News", "Fixture: A science collaboration",  # キーワードなし→既定カテゴリ
                 "https://deepmind.google/discover/blog/fixture-science", "2026-10-14"),
            ],
            "AIコーディング": [
                ("GitHub Changelog", "Fixture: Copilot coding agent supports example setting",
                 "https://github.blog/changelog/2026-10-17-fixture-copilot-agent", "2026-10-18"),
                ("Claude Code Releases", "Claude Code v9.9.2", "https://github.com/anthropics/claude-code/releases/tag/v9.9.2", "2026-10-18"),
                ("Claude Code Releases", "Claude Code v9.9.1", "https://github.com/anthropics/claude-code/releases/tag/v9.9.1", "2026-10-16"),
                ("OpenAI Codex Releases", "Codex 9.8.0", "https://github.com/openai/codex/releases/tag/rust-v9.8.0", "2026-10-17"),
            ],
            "MCP・連携技術": [
                ("MCP Specification Releases", "MCP 2026-10-15",
                 "https://github.com/modelcontextprotocol/modelcontextprotocol/releases/tag/2026-10-15", "2026-10-15"),
            ],
            "API・料金・制限": [
                ("OpenAI News", "Fixture: API pricing update for example models", "https://openai.com/index/fixture-api-pricing", "2026-10-17"),
            ],
        })
        text = self.log_text()
        for absent in ("old research", "Dependabot", "REST API", "alpha", "rc.1", "Synthetic"):
            self.assertNotIn(absent, text)  # 古い記事・AI以外の記事・プレリリース・本文は保存しない


class FeedDiagnostics(ShippedFeedFormats):
    """取得・解析に失敗したフィードの診断情報（v0.1.1）。他のフィードには影響しない。"""

    DEEPMIND = "https://deepmind.google/blog/rss.xml"

    def run_with_deepmind(self, value):
        fixtures = ROOT / "tests" / "fixtures"
        self.feeds = {url: (fixtures / name).read_bytes() for url, name in self.FIXTURES.items()}
        self.feeds[self.DEEPMIND] = value
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn("failed feeds: 1 (Google DeepMind News)", out)  # 他の5フィードは成功
        self.assertEqual(out.count("feed ok: "), 5)
        self.assertIn("Claude Code v9.9.2", self.log_text())
        diag = [line for line in out.splitlines() if line.startswith("  diagnostics: ")]
        self.assertEqual(len(diag), 1)
        for line in out.splitlines():  # 外部由来の文字列でActionsのワークフローコマンドを発生させない
            self.assertFalse(line.startswith("::") and not line.startswith(("::warning::feed failed", "::warning::BRAVE")), line)
        return out, diag[0]

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
        self.assertEqual(names, {"collect.py", "feeds.py", "brave.py", "common.py", "search_index.py"})
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
