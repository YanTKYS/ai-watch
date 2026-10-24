import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import ROOT, block_network, collect  # noqa: E402

import source_report  # noqa: E402


class SourceReport(unittest.TestCase):
    def setUp(self):
        patcher = block_network()
        self.addCleanup(patcher.stop)
        self.config = collect.load_config(ROOT / 'config/sources.yml')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.logs = self.base / 'logs'
        month = self.logs / '2026/2026-10.md'
        month.parent.mkdir(parents=True)
        month.write_text(
            '## 2026-10-23\n### AIコーディング\n#### grouped release\n'
            '- URL: https://github.com/anthropics/claude-code/releases/tag/v3\n'
            '- Feed: Claude Code Releases\n- Retrieved: 2026-10-23\n'
            '## 2026-10-24\n### AIモデル\n#### new article\n'
            '- URL: https://openai.com/index/new\n- Feed: OpenAI News\n'
            '- Retrieved: 2026-10-24\n'
            '#### retired source\n- URL: https://retired.example/article\n'
            '- Feed: Retired Feed\n- Retrieved: 2026-10-24\n', encoding='utf-8')
        self.seen = self.base / 'seen.json'
        self.seen.write_text(json.dumps({
            'https://github.com/anthropics/claude-code/releases/tag/v2': {
                'first_seen': '2026-10-23',
                'grouped_into': 'https://github.com/anthropics/claude-code/releases/tag/v3'},
            'https://openai.com/index/rejected': {'first_seen': '2026-10-24', 'excluded': 'low_score'},
            'https://unknown.example/not-published': {'first_seen': '2026-10-24', 'excluded': 'low_score'},
            'https://openai.com/index/old': {'first_seen': '2026-10-22', 'excluded': 'customer_story'},
        }))

    def test_period_grouped_urls_unknown_sources_and_no_mutation(self):
        before = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        text = source_report.report(self.config, self.logs, self.seen, '2026-10-23', '2026-10-24')
        claude = next(row for row in text.splitlines() if row.startswith('| Claude Code Releases'))
        self.assertIn('| 1 | 1 | 0 | 2026-10-23 |', claude)
        self.assertIn('保存記事合計: 3件。うち現行設定にないFeed: 1件', text)
        self.assertIn('除外URL合計: 2件（未帰属: 1件）', text)
        self.assertIn('| low_score | 2 |', text)
        self.assertNotIn('customer_story', text)
        self.assertNotIn('not-published', text)  # 除外記事のURLはレポートに転載しない
        self.assertEqual(before, {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()})
        narrow = source_report.report(self.config, self.logs, self.seen, '2026-10-24', '2026-10-24')
        claude = next(row for row in narrow.splitlines() if row.startswith('| Claude Code Releases'))
        self.assertIn('| 0 | 0 | 0 | — |', claude)

    def test_inference_is_repository_scoped_and_ambiguous_hosts_stay_unknown(self):
        infer = lambda url: source_report.inferred_feed(url, self.config)
        self.assertEqual(infer('https://github.com/openai/codex/releases/tag/v1'), 'OpenAI Codex Releases')
        self.assertIsNone(infer('https://github.com/openai/codex-other/releases/tag/v1'))
        self.assertIsNone(infer('https://github.com/unrelated/repo/releases/tag/v1'))
        self.assertIsNone(infer('https://[invalid'))
        self.config.feeds.append(self.config.feeds[0])
        self.assertIsNone(infer('https://openai.com/index/a'))

    def test_cli_rejects_reverse_period(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            source_report.main(['--since', '2026-10-24', '--until', '2026-10-18'])
        self.assertEqual(cm.exception.code, 2)

    def test_empty_period_keeps_every_configured_feed(self):
        text = source_report.report(self.config, self.logs, self.seen, '2020-01-01', '2020-01-01')
        for feed in self.config.feeds:
            self.assertIn(f'| {feed.name} ({feed.url})', text)
        self.assertIn('保存記事合計: 0件', text)
        self.assertIn('除外URL合計: 0件', text)


if __name__ == '__main__':
    unittest.main()
