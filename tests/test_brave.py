import json
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import SECRET, Base, block_network, brave_payload, result, rss  # noqa: E402

import brave  # noqa: E402

X_Q = 'site:x.com "Claude Code"'
WEB_Q = "OpenAI API pricing"


def setUpModule():
    global _net
    _net = block_network()


def tearDownModule():
    _net.stop()


class Request(unittest.TestCase):
    def test_key_only_in_header_and_no_paging(self):
        q = brave.Query(id="x", kind="x", category="coding", q=X_Q, search_lang="en", country="ALL", freshness="pd")
        req = brave.build_request(q, SECRET)
        self.assertNotIn(SECRET, req.full_url)
        self.assertEqual(req.get_header("X-subscription-token"), SECRET)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        self.assertEqual(params["q"], [X_Q])
        self.assertEqual(params["count"], ["20"])
        self.assertEqual(params["freshness"], ["pd"])
        self.assertEqual(params["country"], ["ALL"])
        self.assertEqual(params["search_lang"], ["en"])
        self.assertNotIn("offset", params)
        self.assertLessEqual(brave.RESULT_COUNT, 20)
        self.assertEqual(brave.MAX_DAILY_REQUESTS, 4)


class Quality(unittest.TestCase):
    def test_classify_x_url(self):
        c = brave.classify_x_url
        self.assertEqual(c("https://x.com/dev_user/status/1234567890"), ("post", "dev_user"))
        self.assertEqual(c("https://x.com/Dev_User/status/1234567890/photo/1"), ("post", "dev_user"))
        self.assertEqual(c("https://x.com/dev_user"), ("profile", None))
        self.assertEqual(c("https://x.com/i/status/123"), ("other", None))
        self.assertEqual(c("https://x.com/search?q=mcp"), ("other", None))
        self.assertEqual(c("https://x.com/hashtag/MCP"), ("other", None))
        self.assertEqual(c("https://example.com/dev_user/status/1"), ("non_x", None))

    def test_evaluate_counts(self):
        config = brave.BraveConfig(daily_limit=4, queries=[],
                                   evidence=brave.compile_terms(["changelog", "検証"], "e"),
                                   hype=brave.compile_terms(["insane", "最強"], "h"))
        query = brave.Query(id="x", kind="x", category="coding", q=X_Q)
        topic = brave.compile_terms(["Claude Code", "Codex"], "t")
        results = [
            result("https://x.com/a/status/1", "Claude Code v2.1 changelog", "", page_age="2026-10-17T10:00:00"),
            result("https://x.com/a/status/2", "Claude Code is insane", "", page_age="2026-10-17T10:00:00"),
            result("https://x.com/b/status/3?s=20", "Codex を実機で検証", "", page_age="2026-09-01T00:00:00"),
            result("https://x.com/b", "b (@b) / X", "Claude Code fan"),
            result("https://x.com/search?q=x", "search", ""),
            result("https://news.example.com/1", "Claude Code news", "", page_age="2026-10-18T00:00:00"),
            result("https://news.example.com/1", "dup", ""),
            result("javascript:alert(1)", "bad", ""),
            "not a dict",
        ]
        results = [r for r in results if isinstance(r, dict)]
        run_urls = set()
        s = brave.evaluate(query, results, config, topic, "2026-10-18", {"https://news.example.com/1"}, run_urls)
        self.assertEqual((s.results, s.x_posts, s.x_profiles, s.x_other, s.non_x, s.x_authors), (7, 3, 1, 1, 2, 2))
        self.assertEqual((s.dated, s.recent), (4, 3))
        self.assertEqual((s.on_topic, s.evidence, s.hype), (5, 2, 1))  # バージョン番号も根拠として数える
        self.assertEqual(s.candidates, 1)  # 実際の投稿・話題に一致・誇張なし・7日以内
        self.assertEqual((s.duplicates, s.official_overlap), (1, 2))
        self.assertNotIn("Claude", json.dumps(brave.asdict(s)))  # 集計結果に検索結果の文字列を含めない


class Probe(Base):
    def setUp(self):
        super().setUp()
        self.brave[X_Q] = brave_payload(
            result("https://x.com/dev/status/1", "Claude Code v2.1 changelog", "secret snippet", page_age="2026-10-17T00:00:00"),
            result("https://x.com/dev", "dev (@dev) / X", "profile"))
        self.brave[WEB_Q] = brave_payload(result("https://blog.example.net/pricing", "OpenAI API pricing changes", "desc"))
        self.feeds["https://news.example.com/rss.xml"] = rss(
            ("Claude model", "https://news.example.com/claude", "Sat, 17 Oct 2026 00:00:00 GMT"))

    def usage_data(self):
        return json.loads(self.usage.read_text(encoding="utf-8"))

    def test_runs_once_and_records_usage(self):
        code, out, err = self.run_collect()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.brave_calls()), 2)  # 1検索語1リクエスト
        day = self.usage_data()["2026-10-18"]
        self.assertEqual(day["requests"], 2)
        self.assertEqual(day["queries"]["x-coding"]["x_posts"], 1)
        self.assertEqual(day["queries"]["x-coding"]["x_profiles"], 1)
        self.assertEqual(day["queries"]["x-coding"]["candidates"], 1)
        self.assertEqual(day["queries"]["web-api"]["non_x"], 1)
        self.assertIn("Brave API requests: 2", out)
        self.assertIn("[x-coding] kind=x status=ok results=2 x_posts=1", out)
        self.assertIn("Brave last 7 days: requests=2", out)
        self.assertIn("kind=x queries=1 failed=0 results=2 x_post_rate=50%", out)

    def test_brave_results_are_never_persisted_or_printed(self):
        code, out, err = self.run_collect()
        written = self.all_written_text()
        for needle in ("x.com/dev", "blog.example.net", "secret snippet", "OpenAI API pricing changes", "changelog"):
            self.assertNotIn(needle, written)  # logs・seen・usage のどこにも検索結果を保存しない
            self.assertNotIn(needle, out + err)  # Actionsログにも出さない
        self.assertIn("Claude model", self.log_text())  # 公式フィードは保存する

    def test_same_day_rerun_does_not_call_api(self):
        self.run_collect()
        self.calls.clear()
        code, out, _ = self.run_collect()  # 手動実行など、同じ日の再実行
        self.assertEqual(code, 0)
        self.assertEqual(self.brave_calls(), [])
        self.assertTrue(self.feed_calls())  # 公式フィードは取得する
        self.assertIn("Brave status: already_ran", out)
        self.assertEqual(self.usage_data()["2026-10-18"]["requests"], 2)
        self.calls.clear()
        self.run_collect(today="2026-10-19")  # 翌日は再び実行する
        self.assertEqual(len(self.brave_calls()), 2)

    def test_daily_limit_reached_is_respected(self):
        self.usage.parent.mkdir(parents=True)
        self.usage.write_text(json.dumps({"2026-10-18": {"requests": 4}}), encoding="utf-8")
        code, out, _ = self.run_collect()
        self.assertEqual(self.brave_calls(), [])
        self.assertIn("Brave status: limit_reached", out)

    def test_hard_cap_even_if_config_check_is_bypassed(self):
        cfg = brave.BraveConfig(daily_limit=4, queries=[
            brave.Query(id=f"q{i}", kind="web", category="api", q=f"q{i}") for i in range(7)])
        calls = []
        usage = {}
        r = brave.run_probe(cfg, SECRET, usage, "2026-10-18", {}, set(), persist=lambda u: None,
                            sleep=lambda s: None, search_fn=lambda q, k: calls.append(q.id) or [])
        self.assertEqual(len(calls), 4)
        self.assertEqual(usage["2026-10-18"]["requests"], 4)
        self.assertEqual(r.requests, 4)
        self.assertEqual([q.status for q in r.queries.values()].count("skipped"), 3)

    def test_usage_is_persisted_before_each_request(self):
        cfg = brave.BraveConfig(daily_limit=4, queries=[
            brave.Query(id=f"q{i}", kind="web", category="api", q=f"q{i}") for i in range(2)])
        persisted = []

        def search_fn(q, k):
            self.assertEqual(persisted[-1]["2026-10-18"]["requests"], len(persisted))  # 呼び出し前に記録済み
            raise RuntimeError("crash")

        brave.run_probe(cfg, SECRET, {}, "2026-10-18", {}, set(),
                        persist=lambda u: persisted.append(json.loads(json.dumps(u))),
                        sleep=lambda s: None, search_fn=search_fn)
        self.assertEqual(persisted[-1]["2026-10-18"]["requests"], 2)

    def test_failures_are_counted_not_retried_and_do_not_break_logs(self):
        self.brave[X_Q] = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        self.brave[WEB_Q] = TimeoutError()
        code, out, _ = self.run_collect()
        self.assertEqual(code, 0)  # 公式フィードが取れていれば成功
        self.assertEqual(len(self.brave_calls()), 2)  # リトライなし
        self.assertIn("Brave failed requests: 2", out)
        self.assertIn("[x-coding] kind=x status=failed error=HTTP 429", out)
        day = self.usage_data()["2026-10-18"]
        self.assertEqual((day["requests"], day["queries"]["x-coding"]["status"]), (2, "failed"))
        self.assertIn("Claude model", self.log_text())
        self.calls.clear()
        self.run_collect()  # 失敗した日も、同じ日には再実行しない
        self.assertEqual(self.brave_calls(), [])

    def test_missing_key_or_skip_flag_does_not_call_or_record(self):
        code, out, _ = self.run_collect(env={})
        self.assertEqual(code, 0)
        self.assertEqual(self.brave_calls(), [])
        self.assertIn("BRAVE_API_KEY is not configured", out)
        self.assertFalse(self.usage.exists())
        code, out, _ = self.run_collect(skip_brave=True)
        self.assertEqual(self.brave_calls(), [])
        self.assertIn("skipped (--skip-brave)", out)

    def test_unreadable_usage_file_fails_closed(self):
        self.usage.parent.mkdir(parents=True)
        for broken in ("{broken", "[]", json.dumps({"2026-10-18": {"requests": "many"}})):
            self.usage.write_text(broken, encoding="utf-8")
            self.calls.clear()
            code, out, _ = self.run_collect()
            self.assertEqual(self.brave_calls(), [], broken)  # 利用件数が分からなければAPIを呼ばない

    def test_usage_retention(self):
        usage = {"2026-01-01": {"requests": 4}, "2026-10-17": {"requests": 4}}
        brave.save_usage(self.usage, usage, "2026-10-18")
        self.assertEqual(set(self.usage_data().keys()), {"2026-10-17"})


if __name__ == "__main__":
    unittest.main()
