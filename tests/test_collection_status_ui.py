import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class CollectionStatusUI(unittest.TestCase):
    def test_offline_status_display(self):
        result = subprocess.run(['node', '--test', '--test-reporter=tap', str(Path(__file__).with_name('test_collection_status.cjs'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 9', result.stdout)
        self.assertIn('# pass 9', result.stdout)
