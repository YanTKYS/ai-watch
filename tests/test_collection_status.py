import io
import json
import sys
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Base, ROOT, SECRET, collect, rss  # noqa: E402

import collection_status as status  # noqa: E402
import yaml  # noqa: E402

T0 = '2026-10-23T08:00:00+09:00'
T1 = '2026-10-24T08:00:00+09:00'


class CollectionStatus(Base):
    @property
    def path(self):
        return self.months.parent / 'collection-status.json'

    def state(self):
        return json.loads(self.path.read_text())

    def run_at(self, stamp, **kwargs):
        with mock.patch('collection_status.timestamp', return_value=stamp):
            return self.run_collect(**kwargs)

    def test_success_new_articles_and_unchanged_day_record_real_attempt(self):
        self.feeds['https://news.example.com/rss.xml'] = rss(('New API', 'https://n.example/api', '2026-10-18'))
        self.assertEqual(self.run_at(T0, skip_brave=True)[0], 0)
        c = self.state()['collection']
        self.assertEqual(c['result'], 'success')
        self.assertEqual(c['new_articles'], 1)
        self.assertEqual(c['feeds'][0], {'name': 'News', 'status': 'success', 'candidates': 1, 'adopted': 1})
        before = self.log_text()
        self.assertEqual(self.run_at(T1, skip_brave=True)[0], 0)
        c = self.state()['collection']
        self.assertEqual(c['attempted_at'], T1)
        self.assertEqual(c['last_all_success_at'], T1)
        self.assertEqual(c['new_articles'], 0)
        self.assertEqual(self.log_text(), before)

    def test_partial_then_all_failure_preserve_last_all_success_even_if_brave_works(self):
        self.assertEqual(self.run_at(T0, skip_brave=True)[0], 0)
        self.feeds['https://news.example.com/rss.xml'] = OSError(SECRET)
        self.assertEqual(self.run_at(T1, skip_brave=True)[0], 0)
        self.assertEqual(self.state()['collection']['result'], 'partial')
        self.assertEqual(self.state()['collection']['last_all_success_at'], T0)
        config = collect.load_config(self.config)
        self.feeds = {feed.url: OSError(SECRET) for feed in config.feeds}
        code, _, _ = self.run_at(T1, skip_brave=False)
        self.assertEqual(code, 1)  # Braveの成功で公式フィード全失敗を隠さない
        c = self.state()['collection']
        self.assertEqual(c['result'], 'failed')
        self.assertEqual(c['last_all_success_at'], T0)
        self.assertTrue(all(f['candidates'] is None and f['adopted'] is None for f in c['feeds']))
        self.assertNotIn(SECRET, self.path.read_text())
        self.assertNotIn('diagnostics', self.path.read_text())
        self.assertNotIn('brave', self.path.read_text())

    def test_configuration_failure_records_unknown_work_without_network(self):
        self.run_at(T0, skip_brave=True)
        self.config.write_text('broken: true')
        self.calls.clear()
        code, _, _ = self.run_at(T1, skip_brave=True)
        self.assertEqual(code, 2)
        c = self.state()['collection']
        self.assertEqual(c['result'], 'error')
        self.assertEqual(c['last_all_success_at'], T0)
        self.assertIsNone(c['new_articles'])
        self.assertEqual(self.calls, [])

    def test_article_write_failure_records_incomplete_and_reraises(self):
        self.run_at(T0, skip_brave=True)
        self.feeds['https://news.example.com/rss.xml'] = rss(('New API', 'https://n.example/api', '2026-10-18'))
        with mock.patch('collect.write_log', side_effect=OSError(SECRET)), self.assertRaises(OSError):
            self.run_at(T1, skip_brave=True)
        c = self.state()['collection']
        self.assertEqual(c['result'], 'error')
        self.assertEqual(c['last_all_success_at'], T0)
        self.assertIsNone(c['new_articles'])
        self.assertNotIn(SECRET, self.path.read_text())

    def test_status_write_failure_returns_failure_without_changing_api_behavior(self):
        with mock.patch('collection_status.save', side_effect=OSError(SECRET)):
            code, _, err = self.run_at(T1, skip_brave=True)
        self.assertEqual(code, 1)
        self.assertIn('状態を保存できません', err)
        self.assertNotIn(SECRET, err)
        self.assertEqual(self.brave_calls(), [])

    def test_index_generation_success_then_failure_is_separate_and_preserves_success(self):
        self.run_at(T0, skip_brave=True)
        with mock.patch('collection_status.timestamp', return_value=T0):
            status.finalize(self.path, 'success', 'success')
        self.feeds['https://news.example.com/rss.xml'] = OSError('offline')
        self.run_at(T1, skip_brave=True)
        with mock.patch('collection_status.timestamp', return_value=T1):
            status.finalize(self.path, 'success', 'failure')
        s = self.state()
        self.assertEqual(s['collection']['result'], 'partial')
        self.assertEqual(s['index'], {'checked_at': T1, 'result': 'failed', 'last_success_at': T0, 'for_collection': T1})
        self.assertEqual(s['collection']['last_all_success_at'], T0)

    def test_new_action_run_without_collector_does_not_relabel_previous_success(self):
        with mock.patch.dict('os.environ', {'GITHUB_RUN_ID': '10', 'GITHUB_RUN_ATTEMPT': '1'}):
            self.run_at(T0, skip_brave=True)
            with mock.patch('collection_status.timestamp', return_value=T0):
                status.finalize(self.path, 'success', 'success')
        with mock.patch.dict('os.environ', {'GITHUB_RUN_ID': '11', 'GITHUB_RUN_ATTEMPT': '1'}), \
                mock.patch('collection_status.timestamp', return_value=T1):
            status.finalize(self.path, 'skipped', 'skipped')
        c = self.state()['collection']
        self.assertEqual(c['result'], 'unknown')
        self.assertIsNone(c['attempted_at'])  # 収集が始まった時刻を捏造しない
        self.assertEqual(c['last_all_success_at'], T0)
        self.assertEqual(self.state()['index']['last_success_at'], T0)

    def test_interrupted_attempt_is_marked_incomplete_but_brave_failure_does_not_relabel_official_success(self):
        with mock.patch('collection_status.timestamp', return_value=T0):
            status.begin(self.path, T0)
            status.finalize(self.path, 'failure', 'success')
        self.assertEqual(self.state()['collection']['result'], 'error')
        self.assertIsNone(self.state()['collection']['last_all_success_at'])
        self.run_at(T1, skip_brave=True)
        with mock.patch('collection_status.timestamp', return_value=T1):
            status.finalize(self.path, 'failure', 'success')
        self.assertEqual(self.state()['collection']['result'], 'success')

    def test_legacy_corruption_privacy_and_atomic_save(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{broken')
        self.run_at(T0, skip_brave=True)
        s = self.state()
        s['secret'] = SECRET
        s['collection']['feeds'][0]['body'] = SECRET
        s['index'] = {'result': 'failed', 'checked_at': T0, 'last_success_at': None, 'for_collection': T0, 'body': SECRET}
        self.path.write_text(json.dumps(s))
        status.finalize(self.path, 'success', 'failure')
        self.assertNotIn(SECRET, self.path.read_text())
        with mock.patch('collection_status.timestamp', return_value=T1):
            status.begin(self.path, T1)
            status.finish(self.path, T1, 'partial', [{'name': 'News', 'status': 'failed', 'candidates': None, 'adopted': None, 'body': SECRET}], 0)
        self.assertNotIn(SECRET, self.path.read_text())
        before = self.path.read_bytes()
        with mock.patch.object(Path, 'replace', side_effect=OSError('disk')), self.assertRaises(OSError):
            status.save(self.path, {'schema_version': 1})
        self.assertEqual(self.path.read_bytes(), before)

    def test_dry_run_never_records_collection_or_index_status(self):
        with mock.patch('collection_status.begin') as begin, mock.patch('collection_status.finish') as finish, \
                mock.patch('collection_status.finalize') as final, redirect_stdout(io.StringIO()):
            self.assertEqual(collect.main(['--dry-run', '--check-quality', '--reconsider-excluded']), 0)
        for fn in (begin, finish, final):
            fn.assert_not_called()

    def test_actions_status_cli_records_to_explicit_path_without_touching_production(self):
        self.run_at(T0, skip_brave=True)
        production = (ROOT / 'data/collection-status.json').read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/collection_status.py'), '--path', str(self.path),
                                 '--collect-result', 'success', '--index-result', 'failure'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()['index']['result'], 'failed')
        self.assertIsNone(self.state()['index']['last_success_at'])
        self.assertEqual((ROOT / 'data/collection-status.json').read_bytes(), production)

    def test_actions_preserve_failures_and_record_real_step_outcomes_before_commit(self):
        wf = yaml.safe_load((ROOT / '.github/workflows/collect.yml').read_text())
        steps = wf['jobs']['collect']['steps']
        by_name = {s.get('name'): s for s in steps}
        collector = by_name['Collect']
        index = by_name['Update search index']
        record = by_name['Record collection and index status']
        commit = by_name['Commit and push if there are changes']
        self.assertFalse(collector.get('continue-on-error', False))
        self.assertTrue(index['continue-on-error'])
        for step in (index, record, commit):
            self.assertEqual(step['if'], '${{ !cancelled() }}')
        self.assertIn('steps.search_index.outcome', record['run'])
        self.assertIn('steps.collect.outcome', record['run'])
        self.assertNotIn('.conclusion', record['run'])
        self.assertLess(steps.index(index), steps.index(record))
        self.assertLess(steps.index(record), steps.index(commit))
        self.assertIn('data/collection-status.json', commit['run'])
