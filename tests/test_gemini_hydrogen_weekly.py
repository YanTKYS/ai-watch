"""Run the secretless Node mocks in existing CI; inspect the manual PoC workflow offline."""
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github/workflows/gemini-hydrogen-weekly-poc.yml'


class GeminiHydrogenWeekly(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_offline_mock_suite(self):
        result = subprocess.run(['node', '--test', '--test-reporter=tap', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# fail 0', result.stdout)

    def test_manual_main_only_minimal_permissions_and_secret_scope(self):
        text = WORKFLOW.read_text()
        wf = yaml.safe_load(text)
        triggers = wf.get('on', wf.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})  # no push / schedule / pull_request
        inputs = triggers['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs), {'execute', 'spec_confirmed'})
        for name in inputs:  # dry run is the default
            self.assertIs(inputs[name]['default'], False)
            self.assertEqual(inputs[name]['type'], 'boolean')
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        self.assertIs(wf['concurrency']['cancel-in-progress'], False)
        job = wf['jobs']['poc']
        for guard in ["github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'", "github.repository == 'YanTKYS/ai-watch'"]:
            self.assertIn(guard, job['if'])
        self.assertNotIn('env', job)
        steps = job['steps']
        self.assertIs(steps[0]['with']['persist-credentials'], False)
        live = [s for s in steps if 'GEMINI_API_KEY' in s.get('env', {})]
        self.assertEqual(len(live), 1)  # the Secret reaches the live step only
        self.assertEqual(live[0]['env']['GEMINI_API_KEY'], '${{ secrets.GEMINI_API_KEY }}')
        for condition in ('inputs.execute', 'inputs.spec_confirmed', 'github.run_attempt == 1'):
            self.assertIn(condition, live[0]['if'])
        self.assertEqual(text.count('secrets.'), 1)
        self.assertEqual(sum('--live' in s.get('run', '') for s in steps), 1)
        index = steps.index(live[0])
        self.assertLess(next(i for i, s in enumerate(steps) if 'node --test' in s.get('run', '')), index)  # offline tests first
        self.assertLess(next(i for i, s in enumerate(steps) if 'gemini_hydrogen_weekly.cjs' in s.get('run', '') and '--live' not in s['run']), index)
        artifact = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertLessEqual(artifact['with']['retention-days'], 7)
        self.assertNotIn('*', artifact['with']['path'])
        for prohibited in ['git push', 'git commit', 'collect.py', 'plamo_probe.py', 'curl ', 'schedule:', 'pull_request:', 'pull_request_target']:
            self.assertNotIn(prohibited, text)

    def test_experiment_documents_exist(self):
        base = ROOT / 'experiments/gemini-hydrogen-weekly'
        for name in ('README.md', 'evaluation-template.md', 'manifest-2026-W45.json'):
            self.assertTrue((base / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()
