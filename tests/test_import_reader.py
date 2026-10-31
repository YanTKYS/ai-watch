import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ImportReader(unittest.TestCase):
    def test_offline_import_boundaries(self):
        result = subprocess.run(['node', '--test', '--test-reporter=tap', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# pass 10', result.stdout)
