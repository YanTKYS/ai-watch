import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ViewURL(unittest.TestCase):
    def test_url_parsing_history_and_article_navigation(self):
        result = subprocess.run(['node', '--test', '--test-reporter=tap', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 11', result.stdout)
        self.assertIn('# pass 11', result.stdout)
