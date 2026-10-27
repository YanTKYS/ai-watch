"""公開仕様を模した合成応答だけを使う。PLaMo・引用先への実通信は禁止。"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import plamo_probe as probe  # noqa: E402

KEY = "test-plamo-secret-DO-NOT-PRINT"
NOW = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)


def payload():
    return {"model": probe.MODEL,
            "choices": [{"message": {"role": "assistant", "content": "2026-10-27 発表元A: 新モデルの公開（未検証）。\n発表元B: API料金の更新。",
                                      "annotations": [cite("https://public.example/news"), cite("https://public.example/new")],
                                      "reasoning_content": "PRIVATE REASONING MUST NOT BE SAVED"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "plamo_usage_details": [{"usage_type": "main_response", "token_consumed": 150},
                                    {"usage_type": "web_search", "input_tokens": 123, "token_consumed": 2}],
            "unknown_private_field": "RAW RESPONSE MUST NOT BE SAVED"}


def cite(url, title="発表元A"):
    return {"type": "url_citation", "url_citation": {"url": url, "title": title, "start_index": 1, "end_index": 2}}


class Response:
    status = 200

    def __init__(self, value, status=200):
        self.body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.status = status
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.seen = Path(self.tmp.name) / "seen.json"
        self.seen.write_text(json.dumps({"https://public.example/news": {"first_seen": "2026-10-26"},
                                        "https://public.example/excluded": {"excluded": "low_score"},
                                        "https://public.example/grouped": {"grouped_into": "https://public.example/group"}}))
        self.network = mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("NO NETWORK"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def run_live(self, value=None, error=None, status=200):
        transport = mock.Mock()
        transport.open.side_effect = error
        response = Response(payload() if value is None else value, status=status)
        transport.open.return_value = response
        before = self.seen.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = probe.run_probe(live=True, api_key=KEY, seen_path=self.seen, now=NOW, opener=transport)
        self.assertEqual(self.seen.read_bytes(), before)
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertEqual(transport.open.call_count, 1)
        self.assertNotIn(KEY, json.dumps(result) + probe.render_markdown(result))
        return result, transport, response

    def test_plan_default_never_calls_api_and_records_exact_prompt_period(self):
        opener = mock.Mock()
        result = probe.run_probe(api_key=KEY, seen_path=self.seen, now=NOW, opener=opener)
        opener.open.assert_not_called()
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["api_requests"], 0)
        self.assertEqual(result["period"], {"from": "2026-10-22", "to": "2026-10-28", "timezone": "Asia/Tokyo", "inclusive": True})
        self.assertIn("2026-10-22", result["messages"][1]["content"])
        self.assertIn("2026-10-28", result["messages"][1]["content"])
        self.assertEqual(result["seen_snapshot"]["urls"], 3)
        self.assertEqual(len(result["seen_snapshot"]["sha256"]), 64)
        self.assertEqual(result["started_at"], NOW.isoformat())

    def test_one_post_uses_official_supported_parameters_and_header_only_key(self):
        result, transport, response = self.run_live()
        request = transport.open.call_args.args[0]
        self.assertEqual(request.full_url, probe.ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        data = json.loads(request.data)
        self.assertEqual(data["model"], "plamo-3.1-prime")
        self.assertEqual(data["web_search_options"], {"search_context_size": "low"})
        self.assertEqual(data["max_tokens"], 2048)
        self.assertFalse(data["stream"])
        self.assertEqual(data["reasoning_effort"], "none")
        for name in ["temperature", "n", "tools", "response_format", "seed", "max_tool_calls"]:
            self.assertNotIn(name, data)
        self.assertNotIn(KEY, request.full_url + request.data.decode())
        self.assertEqual(transport.open.call_args.kwargs, {"timeout": 90})
        self.assertEqual(response.read_sizes, [probe.MAX_RESPONSE_BYTES + 1])
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["web_search_calls"], 2)  # API要求1件・input_tokens123と混同しない
        self.assertEqual(result["api_requests"], 1)
        self.assertEqual(result["tokens"]["total_tokens"], 150)
        self.assertGreaterEqual(result["elapsed_seconds"], 0)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE REASONING", serialized)
        self.assertNotIn("RAW RESPONSE", serialized)

    def test_usage_sums_only_web_search_consumption_and_explicit_zero_is_zero(self):
        data = payload()
        data["plamo_usage_details"].append({"usage_type": "web_search", "token_consumed": 3})
        result, _, _ = self.run_live(data)
        self.assertEqual(result["web_search_calls"], 5)
        data["plamo_usage_details"] = [{"usage_type": "web_search", "token_consumed": 0}]
        result, _, _ = self.run_live(data)
        self.assertEqual(result["web_search_calls"], 0)

    def test_missing_or_malformed_search_usage_is_unknown_never_inferred_from_api_count(self):
        variants = [None, [], {}, [{"usage_type": "main_response", "token_consumed": 40}],
                    [{"usage_type": "web_search", "input_tokens": 3}],
                    [{"usage_type": "web_search", "token_consumed": True}],
                    [{"usage_type": "web_search", "token_consumed": -1}],
                    [{"usage_type": "web_search", "token_consumed": 2}, "broken"],
                    [{"usage_type": "web_search", "token_consumed": 2}, {"usage_type": "web_search", "token_consumed": "3"}]]
        for value in variants:
            with self.subTest(value=value):
                data = payload()
                data["plamo_usage_details"] = value
                result, _, _ = self.run_live(data)
                self.assertIsNone(result["web_search_calls"])
                self.assertIn("Web検索使用回数: 不明", probe.render_markdown(result))
                self.assertEqual(result["api_requests"], 1)

    def test_missing_and_invalid_token_usage_remains_unknown(self):
        for value in [None, [], {}, {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "150"}]:
            data = payload()
            data["usage"] = value
            result, _, _ = self.run_live(data)
            self.assertEqual(result["tokens"], {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None})
            self.assertIn("unknown_token_usage", result["warnings"])

    def test_no_annotations_is_valid_but_no_citations_are_invented_from_text(self):
        for annotations in [None, []]:
            data = payload()
            data["choices"][0]["message"]["annotations"] = annotations
            data["choices"][0]["message"]["content"] = "https://public.example/not-annotated"
            result, _, _ = self.run_live(data)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["citations"], [])
            self.assertIn("no_citations", result["warnings"])
            self.assertEqual(result["citation_counts"]["unique"], 0)

    def test_exact_matching_duplicates_exclusions_grouped_and_tracking_variants(self):
        data = payload()
        data["choices"][0]["message"]["annotations"] += [cite("https://public.example/news"),
            cite("https://public.example/excluded"), cite("https://public.example/grouped"),
            cite("https://public.example/news?utm_source=plamo"), cite("https://public.example/news#section")]
        result, _, _ = self.run_live(data)
        self.assertEqual(result["citation_counts"], {"unique": 6, "repeated": 1, "discarded": 0, "seen_exact": 3,
                                                    "collected_exact": 2, "excluded_exact": 1, "new_candidates": 3})
        self.assertIn("記事内容の重複", probe.render_markdown(result))

    def test_nonpublic_unsafe_or_secret_urls_are_dropped_without_following(self):
        bad = ["javascript:alert(1)", "file:///tmp/private", "https://user:password@public.example/x",
               "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.2/x", "http://10.0.0.1/x",
               "http://localhost/x", "http://worker.internal/x", "http://worker/x", "https://public.example/a b",
               "https://public.example/x?api_key=private", "https://public.example/" + KEY,
               "https://public.example/?x=" + ''.join('%%%02X' % ord(c) for c in KEY), "https://public.example/" + "a" * 2050]
        data = payload()
        data["choices"][0]["message"]["annotations"] = [cite(url) for url in bad]
        result, _, _ = self.run_live(data)
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["citation_counts"]["discarded"], len(bad))
        self.assertIn("filtered_citations", result["warnings"])

    def test_summary_and_titles_are_bounded_redacted_and_rendered_as_inert_text(self):
        data = payload()
        malicious = '</pre><img src="https://evil.example/leak"><script>bad()</script> [x](javascript:bad) ``` ::warning::'
        data["choices"][0]["message"]["content"] = (malicious + KEY + ' Authorization: Bearer private ' + "a" * 1000 + '\n') * 10
        data["choices"][0]["message"]["annotations"] = [cite("https://public.example/new", malicious + KEY)]
        result, _, _ = self.run_live(data)
        rendered = probe.render_markdown(result)
        self.assertEqual(len(result["answer_points"]), 6)
        self.assertTrue(all(len(p) <= 160 for p in result["answer_points"]))
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;", rendered)
        self.assertNotIn("Bearer private", rendered)
        self.assertNotIn(KEY, rendered)

    def test_truncation_is_reported_and_not_retried(self):
        data = payload()
        data["choices"][0]["finish_reason"] = "length"
        result, _, _ = self.run_live(data)
        self.assertEqual(result["finish_reason"], "length")
        self.assertIn("truncated", result["warnings"])

    def test_citation_bound_is_explicit(self):
        data = payload()
        data["choices"][0]["message"]["annotations"] = [cite(f"https://public.example/{i}") for i in range(110)]
        result, _, _ = self.run_live(data)
        self.assertEqual(len(result["citations"]), 100)
        self.assertIn("citation_limit", result["warnings"])

    def test_invalid_responses_fail_safely(self):
        variants = [None, [], {}, {"error": {"message": KEY}}, {"choices": []}, {"choices": [1]},
                    {"model": "other", "choices": payload()["choices"]}]
        for mutate in [lambda d: d["choices"][0].update(message=None),
                       lambda d: d["choices"][0]["message"].update(content=""),
                       lambda d: d["choices"][0]["message"].update(annotations={}),
                       lambda d: d["choices"][0].update(finish_reason="private " + KEY),
                       lambda d: d.update(model=KEY)]:
            data = payload()
            mutate(data)
            variants.append(data)
        for value in variants:
            with self.subTest(value=value):
                # None must be JSON null, not the default fixture.
                response = b"null" if value is None else json.dumps(value).encode()
                result, _, _ = self.run_live(response)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error_code"], "invalid_response")
                self.assertIsNone(result["citation_counts"])

    def test_non_json_and_oversized_responses_fail_without_body(self):
        for data, code in [(b"not-json " + KEY.encode(), "invalid_json"),
                           (b"a" * (probe.MAX_RESPONSE_BYTES + 1), "response_too_large")]:
            result, _, _ = self.run_live(data)
            self.assertEqual(result["error_code"], code)

    def test_http_errors_do_not_read_body_or_print_exception_and_never_retry(self):
        for status in [301, 400, 401, 429, 500]:
            body = mock.Mock()
            body.read.side_effect = AssertionError("DO NOT READ ERROR BODY")
            error = urllib.error.HTTPError(probe.ENDPOINT, status, KEY, {"Authorization": KEY}, body)
            result, _, _ = self.run_live(error=error)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["http_status"], status)
            self.assertEqual(result["error_code"], "http_error")
            body.read.assert_not_called()

        result, _, response = self.run_live(status=503)
        self.assertEqual(result["error_code"], "http_error")
        self.assertEqual(response.read_sizes, [])

    def test_network_and_unexpected_failures_have_only_fixed_codes(self):
        for error, code in [(urllib.error.URLError(KEY), "network_error"), (TimeoutError(KEY), "network_error"),
                            (RuntimeError(KEY), "unexpected_error")]:
            result, _, _ = self.run_live(error=error)
            self.assertEqual(result["error_code"], code)
            self.assertIsNone(result["http_status"])

    def test_no_key_or_unreadable_seen_prevents_requests_and_false_new_candidates(self):
        opener = mock.Mock()
        for key in ["", "bad key", "bad\nkey", "bad\x01key", "キー"]:
            result = probe.run_probe(live=True, api_key=key, seen_path=self.seen, now=NOW, opener=opener)
            self.assertEqual(result["api_requests"], 0)
        for text in ["{bad", "[]", '{"https://public.example/x":null}']:
            self.seen.write_text(text)
            result = probe.run_probe(live=True, api_key=KEY, seen_path=self.seen, now=NOW, opener=opener)
            self.assertEqual(result["error_code"], "seen_unreadable")
            self.assertIsNone(result["citation_counts"])
            self.assertEqual(result["api_requests"], 0)
        opener.open.assert_not_called()

    def test_default_transport_disables_redirects(self):
        no_redirect = probe.NoRedirect()
        self.assertIsNone(no_redirect.redirect_request(None, None, 302, "", {}, "https://evil.example/"))
        transport = mock.Mock()
        transport.open.return_value = Response(payload())
        with mock.patch.object(probe.urllib.request, "build_opener", return_value=transport) as build:
            result = probe.run_probe(live=True, api_key=KEY, seen_path=self.seen, now=NOW)
        self.assertEqual(result["status"], "success")
        self.assertIsInstance(build.call_args.args[0], probe.NoRedirect)
        self.assertEqual(transport.open.call_count, 1)

    def test_cli_plan_live_fail_and_output_preflight(self):
        output = Path(self.tmp.name) / "reports"
        with mock.patch.dict("os.environ", {"PLAMO_API_KEY": KEY}), mock.patch.object(probe, "run_probe", wraps=probe.run_probe) as run:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(probe.main(["--output-dir", str(output)]), 0)
            self.assertFalse(run.call_args.kwargs["live"])
            self.assertEqual(json.loads((output / "report.json").read_text())["api_requests"], 0)
            self.assertNotIn(KEY, out.getvalue())
        transport = mock.Mock()
        transport.open.return_value = Response(payload())
        with mock.patch.dict("os.environ", {"PLAMO_API_KEY": KEY}), mock.patch.object(probe.urllib.request, "build_opener", return_value=transport), redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(["--live", "--output-dir", str(output)]), 0)
            self.assertEqual(transport.open.call_count, 1)
            saved = (output / "report.json").read_text() + (output / "report.md").read_text()
            self.assertNotIn(KEY, saved)
            self.assertNotIn("RAW RESPONSE", saved)
            self.assertEqual(json.loads((output / "report.json").read_text())["status"], "success")
        with mock.patch.dict("os.environ", {"PLAMO_API_KEY": ""}), redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(["--live", "--output-dir", str(output)]), 1)
        with mock.patch.object(probe, "run_probe") as run, redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(["--live", "--output-dir", str(ROOT / "data")]), 2)
            run.assert_not_called()
            (output / "report.json").unlink()
            (output / "report.json").symlink_to(self.seen)
            self.assertEqual(probe.main(["--live", "--output-dir", str(output)]), 2)
            run.assert_not_called()


class Workflow(unittest.TestCase):
    def test_manual_only_minimal_permissions_secret_scope_and_short_artifact(self):
        text = (ROOT / ".github/workflows/plamo-probe.yml").read_text()
        wf = yaml.safe_load(text)
        triggers = wf.get("on", wf.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertIs(triggers["workflow_dispatch"]["inputs"]["confirm_one_request"]["default"], False)
        self.assertEqual(wf["permissions"], {"contents": "read"})
        self.assertEqual(wf["concurrency"]["cancel-in-progress"], False)
        self.assertEqual(set(wf["jobs"]), {"probe"})
        job = wf["jobs"]["probe"]
        self.assertIn("workflow_dispatch", job["if"])
        steps = job["steps"]
        secret_steps = [s for s in steps if "PLAMO_API_KEY" in s.get("env", {})]
        self.assertEqual(len(secret_steps), 1)
        self.assertNotIn("env", job)
        self.assertFalse(steps[0]["with"]["persist-credentials"])
        artifact = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(artifact["with"]["retention-days"], 3)
        self.assertIn("always()", artifact["if"])
        summary = next(s for s in steps if "GITHUB_STEP_SUMMARY" in s.get("run", ""))
        self.assertIn("always()", summary["if"])
        self.assertNotIn("git push", text)
        self.assertNotIn("collect.py", text)

    def test_ci_is_secretless_and_does_not_execute_live_probe(self):
        text = (ROOT / ".github/workflows/test.yml").read_text()
        wf = yaml.safe_load(text)
        triggers = wf.get("on", wf.get(True))
        self.assertEqual(set(triggers), {"push", "pull_request"})
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIsNone(triggers["pull_request"])
        self.assertNotIn("secrets.", text)
        self.assertNotIn("--live", text)


if __name__ == "__main__":
    unittest.main()
