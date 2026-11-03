"""Run the secretless Node mocks in existing CI; inspect workflow permissions offline."""
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class BeatAPISummary(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_offline_mock_suite(self):
        result = subprocess.run(['node', '--test', '--test-reporter=tap', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# pass 30', result.stdout)
        self.assertIn('# fail 0', result.stdout)

    def test_manual_main_only_minimal_permissions_and_secret_scope(self):
        text = (ROOT / '.github/workflows/beatapi-deepseek-summary.yml').read_text()
        wf = yaml.safe_load(text)
        triggers = wf.get('on', wf.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch'})
        inputs = triggers['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs), {'confirm_one_request'})
        self.assertIs(inputs['confirm_one_request']['default'], False)
        self.assertEqual(inputs['confirm_one_request']['type'], 'boolean')
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        self.assertIs(wf['concurrency']['cancel-in-progress'], False)
        self.assertEqual(set(wf['jobs']), {'probe'})
        job = wf['jobs']['probe']
        for guard in ["github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'", "github.repository == 'YanTKYS/ai-watch'"]:
            self.assertIn(guard, job['if'])
        self.assertNotIn('env', job)
        steps = job['steps']
        self.assertIs(steps[0]['with']['persist-credentials'], False)
        live = [s for s in steps if 'BEAT_API_KEY' in s.get('env', {})]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]['env']['BEAT_API_KEY'], '${{ secrets.BEAT_API_KEY }}')
        self.assertIn('inputs.confirm_one_request', live[0]['if'])
        self.assertIn('github.run_attempt == 1', live[0]['if'])
        self.assertIn('--live', live[0]['run'])
        self.assertEqual(text.count('secrets.'), 1)
        self.assertLess(next(i for i, s in enumerate(steps) if 'node --test' in s.get('run', '')), steps.index(live[0]))
        self.assertEqual(sum('--live' in s.get('run', '') for s in steps), 1)
        artifact = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(artifact['with']['retention-days'], 1)
        self.assertIn('always()', artifact['if'])
        self.assertNotIn('*', artifact['with']['path'])
        summary = next(s for s in steps if 'GITHUB_STEP_SUMMARY' in s.get('run', ''))
        self.assertIn('always()', summary['if'])
        for prohibited in ['git push', 'git commit', 'collect.py', 'plamo_probe.py', 'curl ', 'schedule:', 'pull_request:']:
            self.assertNotIn(prohibited, text)


if __name__ == '__main__':
    unittest.main()
