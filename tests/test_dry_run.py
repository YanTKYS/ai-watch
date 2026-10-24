import copy
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Base, ROOT, SECRET, atom, rss, collect  # noqa: E402

import selection_preview  # noqa: E402
import yaml  # noqa: E402


FIXTURE = ROOT / 'tests/fixtures/selection-evaluation.json'


class DryRun(Base):
    def setUp(self):
        super().setUp()
        self.config.write_text((ROOT / 'config/sources.yml').read_text())
        self.fixtures = self.dir / 'fixtures.json'
        self.raw = json.loads(FIXTURE.read_text())
        self.candidate = self.dir / 'candidate.yml'

    def preview(self, compare=False, reconsider=False):
        self.fixtures.write_text(json.dumps(self.raw))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch('feeds.fetch', side_effect=AssertionError('network forbidden')) as fetch, \
                mock.patch('brave.run_probe', side_effect=AssertionError('API forbidden')) as api:
            code = selection_preview.preview(self.config, self.candidate if compare else None,
                                             self.fixtures, reconsider_excluded=reconsider)
        fetch.assert_not_called()
        api.assert_not_called()
        rows = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{')]
        return code, rows, out.getvalue(), err.getvalue()

    def test_comparison_changes_status_score_category_reason_and_new_feed(self):
        raw = yaml.safe_load(self.config.read_text())
        raw['selection']['rules'].append({'label': 'industry_case', 'weight': -3, 'terms': ['investor']})
        raw['feeds'][0]['classify'] = False
        raw['feeds'][0]['category'] = 'agents'
        raw['feeds'].append({'name': 'Gemini SDK', 'url': 'https://github.com/googleapis/python-genai/releases.atom',
                             'category': 'api', 'select': 'release_notes', 'classify': False})
        self.candidate.write_text(yaml.safe_dump(raw))
        code, rows, _, err = self.preview(compare=True, reconsider=True)
        self.assertEqual(code, 0, err)
        terminal = next(row for row in rows if row['url'].endswith('/terminal'))
        self.assertTrue(terminal['changed'])
        self.assertEqual(terminal['current']['status'], 'adopted')
        self.assertEqual(terminal['candidate']['status'], 'rejected')
        self.assertEqual(terminal['candidate']['reason'], 'industry_case')
        self.assertEqual(terminal['candidate']['score'], terminal['current']['score'] - 3)
        self.assertEqual(terminal['candidate']['category'], 'AIエージェント')
        added = next(row for row in rows if row['url'].endswith('/gemini-sdk-v1'))
        self.assertIsNone(added['current'])
        self.assertEqual(added['candidate']['status'], 'adopted')
        # F12の正例は保つ。F17の分類改善は両設定で共通に使う。
        for slug in ('new-model', 'decisions', 'deprecation', 'codex'):
            row = next(row for row in rows if row['url'].endswith('/' + slug))
            self.assertEqual(row['candidate']['status'], 'adopted')
        sdk = next(row for row in rows if row['url'].endswith('/sdk-ci'))
        self.assertEqual(sdk['candidate']['status'], 'rejected')
        self.assertIn('破壊的変更・廃止 0', sdk['candidate']['detail'])

    def test_reconsider_preserves_history_and_adopted_entries_stay_skipped(self):
        self.raw['seen']['https://evaluation.example.org/new-model'] = {'first_seen': '2026-10-23'}
        _, rows, _, _ = self.preview()
        row = next(r for r in rows if r['url'].endswith('/languages'))
        self.assertEqual(row['current']['reason'], 'seen:excluded')
        original = copy.deepcopy(self.raw)
        code, rows, _, err = self.preview(reconsider=True)
        self.assertEqual(code, 0, err)
        row = next(r for r in rows if r['url'].endswith('/languages'))
        self.assertEqual(row['current']['status'], 'rejected')
        self.assertEqual(row['current']['score'], 0)
        row = next(r for r in rows if r['url'].endswith('/new-model'))
        self.assertEqual(row['current']['reason'], 'seen/duplicate')
        self.assertEqual(self.raw, original)

    def test_limits_grouped_releases_and_early_skips(self):
        # 既定データの定型修正文はF17で除外されるため、集約の検証には具体的な機能を2件用意する。
        self.raw['feeds']['https://github.com/anthropics/claude-code/releases.atom'][0]['content'] = '<ul><li>Added another configuration option</li></ul>'
        news = 'https://openai.com/news/rss.xml'
        self.raw['feeds'][news] = [{'title': f'Introducing GPT-9.{i}', 'url': f'https://e.example/{i}',
                                    'published': '2026-10-24'} for i in range(7)]
        self.raw['feeds'][news] += [{'title': 'Introducing GPT-1', 'url': 'https://e.example/old', 'published': '2026-09-01'}]
        code, rows, out, err = self.preview()
        self.assertEqual(code, 0, err)
        decisions = [r['current'] for r in rows]
        self.assertEqual(sum(d['reason'] == 'over_limit' for d in decisions), 2)
        self.assertEqual(sum(d['status'] == 'adopted' for d in decisions if d['feed'] == 'OpenAI News'), 5)
        self.assertEqual(next(d for d in decisions if d['url'].endswith('/old'))['reason'], 'age/title/max_items')
        releases = [d for d in decisions if d['feed'] == 'Claude Code Releases']
        self.assertEqual(len(releases), 2)
        self.assertEqual(sum(bool(d['grouped_into']) for d in releases), 1)
        self.assertIn('cards=', out)

    def test_empty_fixture_and_identical_comparison(self):
        self.raw['feeds'] = {url: [] for url in self.raw['feeds']}
        self.candidate.write_bytes(self.config.read_bytes())
        code, rows, out, err = self.preview(compare=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(rows, [])
        self.assertIn('adopted=0 rejected=0 skipped=0 cards=0', out)
        self.assertIn('changed articles: 0', out)

    def test_missing_or_invalid_fixture_fails_before_evaluation(self):
        for mutate in (lambda r: r['feeds'].pop('https://openai.com/news/rss.xml'),
                       lambda r: r.update(today='not-a-date'),
                       lambda r: r['feeds']['https://openai.com/news/rss.xml'].append(r['feeds']['https://openai.com/news/rss.xml'][0]),
                       lambda r: r['feeds']['https://openai.com/news/rss.xml'][0].update(url='javascript:bad'),
                       lambda r: r['feeds']['https://openai.com/news/rss.xml'][0].update(summary=3)):
            self.raw = json.loads(FIXTURE.read_text())
            mutate(self.raw)
            code, rows, _, err = self.preview()
            self.assertEqual(code, 2)
            self.assertEqual(rows, [])
            self.assertIn('ERROR: dry-run', err)

    def test_normal_collection_and_dry_run_use_identical_decisions(self):
        # 通常のRSS/Atom入力経路とdry-runの結果を比較する。
        self.config.write_text(self.config_text)
        mapping = {'https://news.example.com/rss.xml': rss(('GPT example', 'https://e.example/news', '2026-10-24')),
                   'https://changelog.example.com/feed/': rss(('Copilot update', 'https://e.example/change', '2026-10-24')),
                   'https://github.com/example/tool/releases.atom': atom(
                       ('v1', 'https://e.example/v1', '2026-10-24'), ('v2', 'https://e.example/v2', '2026-10-24'),
                       content='<ul><li>Added an option</li></ul>')}
        from feeds import parse_feed
        entries = {url: parse_feed(body) for url, body in mapping.items()}
        config = collect.load_config(self.config)
        live, offline = {}, {}
        with redirect_stdout(io.StringIO()), mock.patch('feeds.fetch', side_effect=lambda url, info: mapping[url]):
            normal = collect.collect_feeds(config, {}, '2026-10-24', decisions=live)
        with redirect_stdout(io.StringIO()):
            dry = collect.collect_feeds(config, {}, '2026-10-24', entry_source=entries.__getitem__, decisions=offline)
        self.assertEqual(live, offline)
        self.assertEqual(normal[:2], dry[:2])
        self.assertEqual(dry[2].feed_requests, 0)
        self.assertEqual(normal[2].feed_requests, 3)

    def test_cli_no_writes_or_api_even_with_key_and_explicit_seen(self):
        self.seen.parent.mkdir(parents=True)
        self.seen.write_text(json.dumps(self.raw['seen']))
        protected = ['config', 'logs', 'data', 'samples', 'tests/fixtures']
        def snapshot():
            return {p: p.read_bytes() for name in protected for p in (ROOT / name).rglob('*') if p.is_file()}
        before = snapshot()
        with mock.patch.dict('os.environ', {'BRAVE_API_KEY': SECRET}), \
                mock.patch('collect.write_log') as write_log, mock.patch('collect.save_json') as save_json, \
                mock.patch('collect.update_months') as months, mock.patch('brave.run_probe') as api, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network, \
                redirect_stdout(io.StringIO()) as out:
            code = collect.main(['--dry-run', '--seen', str(self.seen), '--reconsider-excluded',
                                 '--compare-config', str(self.config)])
        self.assertEqual(code, 0)
        for action in (write_log, save_json, months, api, network):
            action.assert_not_called()
        self.assertEqual(snapshot(), before)
        self.assertEqual(json.loads(self.seen.read_text()), self.raw['seen'])
        self.assertNotIn(SECRET, out.getvalue())
        # 実際のCLIサブプロセスでも再現可能。
        command = [sys.executable, str(ROOT / 'scripts/collect.py'), '--dry-run']
        one = subprocess.run(command, capture_output=True, text=True, check=True)
        two = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(one.stdout, two.stdout)
        self.assertEqual(snapshot(), before)

    def test_preview_options_require_dry_run(self):
        for option in ('--compare-config', '--fixtures', '--seen'):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                collect.main([option, str(self.config)])
            self.assertEqual(cm.exception.code, 2)

    def test_seen_skips_require_keywords_and_cross_feed_duplicates(self):
        news = self.raw['feeds']['https://openai.com/news/rss.xml'][0]
        self.raw['feeds']['https://deepmind.google/blog/rss.xml'] = [copy.deepcopy(news)]
        self.raw['feeds']['https://github.blog/changelog/feed/'] = [
            {'title': 'Repository labels update', 'url': 'https://e.example/labels', 'published': '2026-10-24'}]
        code, rows, _, err = self.preview()
        self.assertEqual(code, 0, err)
        copied = next(row for row in rows if row['current']['feed'] == 'Google DeepMind News')
        self.assertEqual(copied['current']['reason'], 'seen/duplicate')
        labels = next(row for row in rows if row['url'].endswith('/labels'))
        self.assertEqual(labels['current']['reason'], 'require_keywords')

    def test_invalid_candidate_fails_before_any_partial_output(self):
        self.candidate.write_text('broken: config')
        code, rows, out, err = self.preview(compare=True)
        self.assertEqual(code, 2)
        self.assertEqual(rows, [])
        self.assertEqual(out, '')
        self.assertIn('ERROR: dry-run', err)


if __name__ == '__main__':
    unittest.main()
