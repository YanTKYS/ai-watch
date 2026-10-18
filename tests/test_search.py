import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, Base, block_network, collect, rss  # noqa: E402

import search_index  # noqa: E402


def setUpModule():
    global _net
    _net = block_network()


def tearDownModule():
    _net.stop()


def month_log(entries, title="# 月"):
    """entries: [(day, category, title, url, retrieved)]。collect.py と同じ形式で書く。"""
    lines = [title]
    last_day = last_cat = None
    for day, cat, t, url, retrieved in entries:
        if day != last_day:
            lines += ["", f"## {day}"]
            last_day, last_cat = day, None
        if cat != last_cat:
            lines += ["", f"### {cat}"]
            last_cat = cat
        lines += ["", f"#### {t}", "", f"- URL: {url}", f"- Source: {url.split('/')[2] if '://' in url else ''}",
                  "- Feed: Example Feed", "- Published: 2026-01-01"]
        if retrieved:
            lines.append(f"- Retrieved: {retrieved}")
    return "\n".join(lines) + "\n"


class IndexBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.logs = d / "logs"
        self.index = d / "data" / "search-index.json"

    def write(self, ym, entries):
        path = self.logs / ym[:4] / f"{ym}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(month_log(entries), encoding="utf-8")
        return path


class BuildIndex(IndexBase):
    def test_multiple_months_and_years_newest_first(self):
        self.write("2025-12", [("2025-12-31", "AIモデル", "年末の記事", "https://a.example.com/1", "2025-12-31")])
        self.write("2026-01", [("2026-01-01", "AIモデル", "元日の記事", "https://a.example.com/2", "2026-01-01"),
                               ("2026-01-01", "AIコーディング", "同日の2件目", "https://b.example.com/3", "2026-01-01"),
                               ("2026-01-15", "AIモデル", "中旬の記事", "https://a.example.com/4", "2026-01-15")])
        self.write("2026-10", [("2026-10-05", "MCP・連携技術", "十月の記事", "https://a.example.com/5", "2026-10-05")])
        arts = search_index.build_index(self.logs)
        self.assertEqual([a["title"] for a in arts], ["十月の記事", "中旬の記事", "元日の記事", "同日の2件目", "年末の記事"])
        self.assertEqual(arts[1], {"title": "中旬の記事", "url": "https://a.example.com/4", "source": "a.example.com",
                                   "feed": "Example Feed", "published": "2026-01-01", "retrieved": "2026-01-15",
                                   "category": "AIモデル"})
        self.assertEqual(arts[3]["category"], "AIコーディング")

    def test_duplicates_invalid_urls_and_incomplete_entries(self):
        self.write("2026-09", [("2026-09-30", "t", "最初の記録", "https://a.example.com/dup", "2026-09-30")])
        self.write("2026-10", [("2026-10-02", "t", "同じURLの再記録", "https://a.example.com/dup", "2026-10-02"),
                               ("2026-10-02", "t", "危険なURL", "javascript:alert(1)", "2026-10-02"),
                               ("2026-10-02", "t", "ホストなし", "https://", "2026-10-02"),
                               ("2026-10-03", "t", "Retrievedなし（見出しの日付を使う）", "https://a.example.com/ok", "")])
        arts = search_index.build_index(self.logs)
        self.assertEqual([(a["title"], a["retrieved"]) for a in arts],
                         [("Retrievedなし（見出しの日付を使う）", "2026-10-03"), ("最初の記録", "2026-09-30")])

    def test_update_is_idempotent_and_writes_only_on_change(self):
        log = self.write("2026-10", [("2026-10-01", "t", "記事", "https://a.example.com/1", "2026-10-01")])
        self.assertEqual(search_index.update(self.index, self.logs), (True, 1))
        first = self.index.read_text(encoding="utf-8")
        self.assertEqual(search_index.update(self.index, self.logs), (False, 1))
        self.assertEqual(self.index.read_text(encoding="utf-8"), first)
        self.assertEqual(len(first.splitlines()), 3)  # "[" / 1記事1行 / "]"
        log.write_text(log.read_text(encoding="utf-8").replace("#### 記事", "#### 更新後の記事"), encoding="utf-8")
        self.assertEqual(search_index.update(self.index, self.logs), (True, 1))
        self.assertIn("更新後の記事", self.index.read_text(encoding="utf-8"))

    def test_empty_logs_and_unreadable_log_keeps_existing_index(self):
        self.assertEqual(search_index.update(self.index, self.logs), (True, 0))
        self.assertEqual(json.loads(self.index.read_text(encoding="utf-8")), [])
        bad = self.logs / "2026" / "2026-10.md"
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b"\xff\xfe broken")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(search_index.main(self.logs, self.index), 1)
        self.assertIn("search index was not updated", out.getvalue())
        self.assertEqual(self.index.read_text(encoding="utf-8"), "[]\n")


class CollectIntegration(Base):
    """日刊収集の後に search_index を実行すると、新着記事が検索インデックスに入る（通信はmock）。"""

    def test_index_follows_collected_logs(self):
        self.feeds["https://news.example.com/rss.xml"] = rss(
            ("Claude Code 2.0 リリース", "https://news.example.com/cc2", "Mon, 19 Oct 2026 00:00:00 GMT"))
        code, *_ = self.run_collect(today="2026-10-20", env={})
        self.assertEqual(code, 0)
        index = self.dir / "data" / "search-index.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(search_index.main(self.logs, index), 0)
        arts = json.loads(index.read_text(encoding="utf-8"))
        self.assertEqual([(a["title"], a["url"], a["retrieved"], a["category"], a["feed"]) for a in arts],
                         [("Claude Code 2.0 リリース", "https://news.example.com/cc2", "2026-10-20", "AIコーディング", "News")])


class RepoLayout(unittest.TestCase):
    def test_collect_workflow_updates_index_after_collection(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8"))
        steps = wf["jobs"]["collect"]["steps"]
        names = [s.get("name") for s in steps]
        i_collect, i_index, i_commit = (names.index("Collect"), names.index("Update search index"),
                                        names.index("Commit and push if there are changes"))
        self.assertLess(i_collect, i_index)
        self.assertLess(i_index, i_commit)
        index_step = steps[i_index]
        self.assertEqual(index_step["run"], "python scripts/search_index.py")
        self.assertTrue(index_step["continue-on-error"])  # 失敗しても日刊ログのcommitは続ける
        self.assertNotIn("env", index_step)  # APIキーを渡さない
        self.assertIn("data/search-index.json", steps[i_commit]["run"])

    def test_committed_indexes_are_derived_from_logs(self):
        for base in (ROOT, ROOT / "samples"):
            committed = json.loads((base / "data" / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual(committed, search_index.build_index(base / "logs"), base)
            self.assertEqual(json.loads((base / "data" / "months.json").read_text(encoding="utf-8")),
                             collect.list_months(base / "logs"), base)

    def test_samples_are_clearly_fictional(self):
        arts = search_index.build_index(ROOT / "samples" / "logs")
        self.assertGreater(len(arts), 50)  # 「さらに表示」を確認できる件数
        for a in arts:
            self.assertTrue(a["title"].startswith("（サンプル）"), a["title"])
            self.assertRegex(a["url"], r"^https://[a-z]+\.example\.(com|org)/")

    def test_pages_ui(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for needle in ('type="search" id="search-input"', 'id="search-clear"', 'for="search-input"', 'id="month-select"',
                       'id="order-select"', 'name="viewport"', 'name="color-scheme" content="light dark"',
                       'rel="icon" type="image/svg+xml" href="favicon.svg"'):
            self.assertIn(needle, html)
        self.assertNotIn("weekly", html)  # 週刊・月刊は持ち込まない
        self.assertTrue((ROOT / "favicon.svg").exists())
        self.assertTrue((ROOT / ".nojekyll").exists())
        js = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotRegex(js, r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write")  # 外部由来の文字列をHTMLとして扱わない
        self.assertEqual(js.count('fetchText("data/search-index.json")'), 1)
        self.assertNotRegex(js, r"https?://")  # 外部APIを呼ばない（相対パスのみ）
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn("@media (prefers-color-scheme: dark)", css)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ClientSearch(unittest.TestCase):
    """parser.js の関数（ブラウザ内で実行される処理）を Node.js で確認する。"""

    INDEX = [
        {"title": "Claude Code v2.1.0", "url": "https://github.com/a/1", "source": "github.com", "feed": "Claude Code Releases",
         "published": "", "retrieved": "2026-10-06", "category": "AIコーディング"},
        {"title": "Introducing GPT-5.5 API pricing", "url": "https://openai.com/2", "source": "openai.com", "feed": "OpenAI News",
         "published": "", "retrieved": "2026-10-12", "category": "API・料金・制限"},
        {"title": "MCP 仕様の更新", "url": "https://github.com/c/3", "source": "github.com", "feed": "MCP Specification Releases",
         "published": "", "retrieved": "2026-09-30", "category": "MCP・連携技術"},
        {"title": "重複URL", "url": "https://github.com/a/1", "source": "x", "retrieved": "2026-12-01", "category": ""},
        {"title": "危険なURL Claude", "url": "javascript:alert(1)", "source": "x", "retrieved": "2026-12-01"},
        {"title": 123, "url": "https://d.example.com/4", "source": None, "retrieved": "2026-08-01"},
        "not an object",
    ]

    def node(self, script, *args):
        res = subprocess.run(["node", "-e", f"const p = require({json.dumps(str(ROOT / 'parser.js'))});\n{script}", *args],
                             capture_output=True, text=True, timeout=30, check=True)
        return json.loads(res.stdout)

    def search(self, *queries):
        return self.node("const e = p.buildSearchEntries(JSON.parse(process.argv[1]));"
                         "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(q => p.searchArticles(e, q).map(a => a.url))));",
                         json.dumps(self.INDEX, ensure_ascii=False), json.dumps(list(queries), ensure_ascii=False))

    def test_fields_partial_match_case_and_width(self):
        got = self.search("claude code", "ＣＬＡＵＤＥ", "料金", "openai.com", "Releases", "仕様", "MCP 更新", "存在しない", "", "[(.*+?^$|\\")
        self.assertEqual(got, [
            ["https://github.com/a/1"],  # 大文字小文字を区別しない
            ["https://github.com/a/1"],  # 全角英字
            ["https://openai.com/2"],  # カテゴリ
            ["https://openai.com/2"],  # 情報源
            ["https://github.com/a/1", "https://github.com/c/3"],  # 配信元（取得日の新しい順）
            ["https://github.com/c/3"],
            ["https://github.com/c/3"],  # AND
            [], [], [],  # 0件・空欄・記号でもエラーにならない
        ])

    def test_duplicates_invalid_and_non_string_fields(self):
        got = self.node("const e = p.buildSearchEntries(JSON.parse(process.argv[1]));"
                        "console.log(JSON.stringify(e.map(a => [a.url, a.title, a.source])));",
                        json.dumps(self.INDEX, ensure_ascii=False))
        self.assertEqual(got, [
            ["https://openai.com/2", "Introducing GPT-5.5 API pricing", "openai.com"],
            ["https://github.com/a/1", "Claude Code v2.1.0", "github.com"],
            ["https://github.com/c/3", "MCP 仕様の更新", "github.com"],
            ["https://d.example.com/4", "", ""],
        ])

    def test_parse_log_matches_collect_output(self):
        text = (ROOT / "samples" / "logs" / "2026" / "2026-10.md").read_text(encoding="utf-8")
        days = self.node("console.log(JSON.stringify(p.parseLog(process.argv[1])));", text)
        py = [a for a in search_index.parse_log(text)]
        js = [dict(i, retrieved=i["retrieved"], category=c["name"]) for d in days for c in d["categories"] for i in c["items"]]
        self.assertEqual([(a["title"], a["url"], a["feed"], a["category"]) for a in py],
                         [(a["title"], a["url"], a["feed"], a["category"]) for a in js])
        self.assertEqual(days[0]["date"], "2026-10-01")
        self.assertEqual(self.node("console.log(JSON.stringify([p.parseLog(''), p.parseLog('### x\\n#### t\\n- URL: u')]));"),
                         [[], [{"date": "", "categories": [{"name": "x", "items": [
                             {"title": "t", "url": "u", "source": "", "feed": "", "notes": "", "published": "",
                              "retrieved": ""}]}]}]])


if __name__ == "__main__":
    unittest.main()
