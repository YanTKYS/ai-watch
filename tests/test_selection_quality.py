import copy
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Base, ROOT, SECRET, collect  # noqa: E402

import selection_preview  # noqa: E402
import yaml  # noqa: E402


class SelectionQuality(Base):
    def setUp(self):
        super().setUp()
        self.config.write_bytes((ROOT / 'config/sources.yml').read_bytes())
        self.raw = json.loads((ROOT / 'tests/fixtures/selection-evaluation.json').read_text())
        self.fixtures = self.dir / 'quality.json'
        self.candidate = self.dir / 'candidate.yml'

    def evaluate(self, *, check=False, compare=False, quality=True):
        self.fixtures.write_text(json.dumps(self.raw))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network, \
                mock.patch('brave.run_probe', side_effect=AssertionError('API forbidden')) as api:
            code = selection_preview.preview(self.config, self.candidate if compare else None, self.fixtures,
                                             reconsider_excluded=True, evaluate=quality, check_quality=check)
        network.assert_not_called()
        api.assert_not_called()
        rows = {}
        for line in out.getvalue().splitlines():
            if line.startswith('{'):
                row = json.loads(line)
                if row.get('quality'):
                    rows[row['url'].rsplit('/', 1)[-1]] = row
        return code, rows, out.getvalue(), err.getvalue()

    def test_confirmed_pending_and_known_mismatches_are_separate(self):
        code, rows, out, err = self.evaluate(check=True)
        self.assertEqual(code, 0, err)
        self.assertIn('confirmed=10 match=9 mismatch=1 pending=7 required_failed=0', out)
        self.assertIn('undecided=5 not_configured=2', out)
        self.assertEqual(rows['new-model']['current']['result'], 'match')
        self.assertEqual(rows['dashboard']['current']['result'], 'mismatch')
        self.assertEqual(rows['terminal']['current']['result'], 'pending')
        self.assertIsNone(rows['terminal']['current']['expected'])
        self.assertEqual(rows['gemini-sdk-v1']['current']['pending_reason'], '設定にフィードがない')
        self.assertIn('QUALITY CHECK current: PASS', out)

    def test_legacy_notes_never_become_machine_truth_and_no_empty_guard(self):
        self.raw['expectations'] = {url: ('keep', 'review', 'check')[i % 3]
                                    for i, url in enumerate(self.raw['expectations'])}
        code, rows, out, _ = self.evaluate()
        self.assertEqual(code, 0)
        self.assertIn('confirmed=0 match=0 mismatch=0 pending=17', out)
        self.assertTrue(all(r['current']['expected'] is None for r in rows.values()))
        code, _, _, err = self.evaluate(check=True)
        self.assertEqual(code, 2)
        self.assertIn('required', err)

    def test_normal_dry_run_output_and_exit_status_are_unchanged(self):
        first = self.evaluate(quality=False)
        self.raw['expectations'] = {'invalid reference': {'not': 'valid metadata'}}
        second = self.evaluate(quality=False)
        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        self.assertNotIn('QUALITY', first[2])

    def test_candidate_improvement_and_regression_and_guard_exit(self):
        raw = yaml.safe_load(self.config.read_text())
        raw['selection']['min_score'] = 100
        for feed in raw['feeds']:
            if feed['name'] == 'GitHub Changelog':
                feed['select'] = 'score'
        self.candidate.write_text(yaml.safe_dump(raw))
        code, rows, out, _ = self.evaluate(compare=True, check=True)
        self.assertEqual(code, 3)
        self.assertEqual(rows['dashboard']['change'], 'improved')
        self.assertEqual(rows['new-model']['change'], 'regressed')
        self.assertEqual(rows['terminal']['change'], 'pending')
        self.assertIn('QUALITY CHECK candidate: FAIL', out)
        self.assertEqual(self.evaluate(compare=True)[0], 0)  # 集計のみは処理成功

    def test_only_target_candidate_guards_gate_a_repair(self):
        self.candidate.write_bytes(self.config.read_bytes())
        raw = yaml.safe_load(self.config.read_text())
        raw['selection']['min_score'] = 100
        self.config.write_text(yaml.safe_dump(raw))
        code, rows, out, err = self.evaluate(compare=True, check=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(rows['new-model']['change'], 'improved')
        self.assertIn('QUALITY CHECK candidate: PASS', out)
        self.assertGreater(sum(r['current']['required'] and r['current']['result'] == 'mismatch' for r in rows.values()), 0)

    def test_missing_required_feed_and_seen_skips_do_not_silently_pass(self):
        raw = yaml.safe_load(self.config.read_text())
        raw['feeds'] = [f for f in raw['feeds'] if f['name'] != 'OpenAI News']
        self.candidate.write_text(yaml.safe_dump(raw))
        code, rows, _, _ = self.evaluate(compare=True, check=True)
        self.assertEqual(code, 3)
        self.assertIsNone(rows['new-model']['candidate']['actual'])
        self.assertEqual(rows['new-model']['candidate']['result'], 'mismatch')
        self.raw['seen']['https://evaluation.example.org/new-model'] = {'first_seen': '2026-10-23'}
        code, rows, _, _ = self.evaluate(check=True)
        self.assertEqual(code, 3)
        self.assertEqual(rows['new-model']['current']['actual']['status'], 'skipped')

    def test_validation_partition_checks_internal_vs_real_breaking_changes(self):
        self.raw = json.loads((ROOT / 'tests/fixtures/selection-validation.json').read_text())
        code, rows, out, err = self.evaluate(check=True)
        self.assertEqual(code, 0, err)
        self.assertIn('validation: confirmed=11 match=11 mismatch=0 pending=0', out)
        for slug in ('public-breaking', 'api-breaking'):
            row = rows[slug]['current']
            self.assertEqual(row['result'], 'match')
            self.assertEqual(row['actual']['release_counts']['breaking'], 1)
        for slug in ('internal-html', 'example-html'):
            row = rows[slug]['current']
            self.assertEqual(row['result'], 'match')
            self.assertEqual(row['actual']['release_counts']['breaking'], 0)
            self.assertEqual(row['actual']['release_counts']['chore'], 1)
            self.assertEqual(row['differences'], {})
        self.assertEqual(rows['routine-fix']['current']['result'], 'match')

    def test_invalid_expectations_are_input_errors_not_quality_failures(self):
        original = copy.deepcopy(self.raw)
        url = 'https://evaluation.example.org/new-model'
        for mutate in (lambda m: m.update(required='yes'), lambda m: m.update(expected=None),
                       lambda m: m.update(split='unknown'), lambda m: m.update(reason=''),
                       lambda m: m.update(feed_url='https://missing.example/feed'),
                       lambda m: m['expected'].update(status='keep'),
                       lambda m: m['expected'].update(categry='typo'),
                       lambda m: m['expected'].update(release_counts={'breaking': True}),
                       lambda m: m['expected'].update(release_counts={'breaking': -1}),
                       lambda m: m['expected'].update(release_counts={'typo': 1})):
            self.raw = copy.deepcopy(original)
            mutate(self.raw['expectations'][url])
            code, rows, out, err = self.evaluate(check=True)
            self.assertEqual(code, 2)
            self.assertEqual(rows, {})
            self.assertEqual(out, '')
            self.assertIn('ERROR: dry-run', err)

    def test_quality_flags_require_dry_run(self):
        for flag in ('--evaluate', '--check-quality'):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                collect.main([flag])
            self.assertEqual(cm.exception.code, 2)

    def test_ci_commands_and_real_cli_exit_codes(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())
        commands = '\n'.join(s.get('run', '') for s in workflow['jobs']['test']['steps'])
        self.assertIn('python scripts/collect.py --dry-run --check-quality --reconsider-excluded', commands)
        self.assertIn('--fixtures tests/fixtures/selection-validation.json', commands)
        raw = yaml.safe_load(self.config.read_text())
        raw['selection']['min_score'] = 100
        self.candidate.write_text(yaml.safe_dump(raw))
        cmd = [sys.executable, str(ROOT / 'scripts/collect.py'), '--dry-run', '--reconsider-excluded',
               '--compare-config', str(self.candidate)]
        checked = subprocess.run([*cmd, '--check-quality'], capture_output=True, text=True)
        report = subprocess.run([*cmd, '--evaluate'], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 3, checked.stderr)
        self.assertIn('QUALITY CHECK candidate: FAIL', checked.stdout)
        self.assertEqual(report.returncode, 0, report.stderr)

    def test_mixed_field_changes_and_zero_cases_are_not_hidden(self):
        self.raw['expectations']['https://evaluation.example.org/dashboard']['expected']['category'] = 'AIモデル'
        raw = yaml.safe_load(self.config.read_text())
        for feed in raw['feeds']:
            if feed['name'] == 'GitHub Changelog':
                feed['select'] = 'score'
                feed['classify'] = False
                feed['category'] = 'models'
        # statusは引き続き採用で不一致、カテゴリだけ一致に改善する。
        self.candidate.write_text(yaml.safe_dump(raw))
        code, rows, _, err = self.evaluate(compare=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(rows['dashboard']['change'], 'improved')
        self.assertEqual(rows['dashboard']['candidate']['result'], 'mismatch')
        # statusを除外に改善し、従来正しかったカテゴリを外すとmixed。
        self.raw['expectations']['https://evaluation.example.org/dashboard']['expected']['category'] = 'AIコーディング'
        raw['selection']['rules'].append({'label': 'management', 'weight': -3, 'terms': ['impact dashboard']})
        self.candidate.write_text(yaml.safe_dump(raw))
        self.assertEqual(self.evaluate(compare=True)[1]['dashboard']['change'], 'mixed')
        self.raw['feeds'] = {url: [] for url in self.raw['feeds']}
        self.raw['expectations'] = {}
        code, rows, out, err = self.evaluate()
        self.assertEqual(code, 0, err)
        self.assertEqual(rows, {})
        self.assertIn('confirmed=0 match=0 mismatch=0 pending=0', out)
        self.assertEqual(self.evaluate(check=True)[0], 2)

    def test_quality_cli_is_repeatable_read_only_and_does_not_use_api_key(self):
        protected = ['config', 'logs', 'data', 'samples', 'tests/fixtures']
        def snapshot():
            return {p: p.read_bytes() for root in protected for p in (ROOT / root).rglob('*') if p.is_file()}
        before = snapshot()
        with mock.patch.dict('os.environ', {'BRAVE_API_KEY': SECRET}), \
                mock.patch('collect.write_log') as write, mock.patch('collect.save_json') as save, \
                mock.patch('collect.update_months') as months, mock.patch('brave.run_probe') as api, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(collect.main(['--dry-run', '--check-quality', '--reconsider-excluded']), 0)
        for action in (write, save, months, api, network):
            action.assert_not_called()
        self.assertNotIn(SECRET, out.getvalue())
        command = [sys.executable, str(ROOT / 'scripts/collect.py'), '--dry-run', '--check-quality', '--reconsider-excluded']
        first = subprocess.run(command, capture_output=True, check=True).stdout
        second = subprocess.run(command, capture_output=True, check=True).stdout
        self.assertEqual(first, second)
        self.assertEqual(snapshot(), before)
