import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Base, rss  # noqa: E402

import selection  # noqa: E402
import search_index  # noqa: E402
import yaml  # noqa: E402


class ReleaseClassification(unittest.TestCase):
    def test_explicit_work_scopes_and_targets_are_chores(self):
        lines = [
            'internal: remove an unused build upload',
            '**internal:** remove an unused build upload',
            '[VSCode] docs: remove the obsolete --old-flag example',
            'ci: add a workflow', 'build: improve the artifact upload',
            'mcp: remove the stray `await` from the async `tool_runner` examples',
            'Removed outdated snippets', 'Added documentation for an API parameter',
            'Improved examples', 'feat(examples): add a demo',
        ]
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(selection.classify_item(line, None), 'chore')
                self.assertEqual(selection.release_verdict(selection.release_counts(line)), 'minor')

    def test_real_release_excerpts_keep_public_removal_and_drop_maintenance(self):
        # Read-only GitHub API確認: anthropics/claude-code v2.1.303 / v2.1.300、
        # anthropics/anthropic-sdk-python v2.3.0 (2026-10-24)。短い判定対象だけを引用。
        routine = '- Bug fixes and reliability improvements'
        maintenance = ('* **internal:** remove preview build upload from CI\n'
                       '* **mcp:** remove the stray `await` from the async `tool_runner` examples')
        removed = ('- Removed the `--sandbox` and `--no-sandbox` flags from `claude remote-control`, '
                   'which had no effect; passing either now exits with an error.')
        self.assertEqual(selection.release_counts(routine)['fix'], 1)
        self.assertEqual(selection.release_counts(maintenance)['chore'], 2)
        self.assertEqual(selection.release_counts(maintenance)['breaking'], 0)
        self.assertEqual(selection.release_verdict(selection.release_counts(routine + '\n' + maintenance)), 'minor')
        self.assertEqual(selection.pick_highlights([('v1', routine + '\n' + maintenance)]), [])
        self.assertEqual(selection.release_counts(removed)['breaking'], 1)
        self.assertIn('--sandbox', selection.pick_highlights([('v1', removed)])[0])

    def test_public_changes_are_not_hidden_by_example_mentions_or_chore_sections(self):
        for line, section in [
            ('Removed the --old flag and updated examples', None),
            ('Removed the API parameter from the client and updated examples', None),
            ('Removed the --legacy-mode flag', 'chore'),
            ('api: removed the public API argument', 'chore'),
            ('feat!: remove a request parameter', 'chore'),
            ('BREAKING CHANGE: removed a public method', 'chore'),
        ]:
            with self.subTest(line=line):
                self.assertEqual(selection.classify_item(line, section), 'breaking')
        self.assertEqual(selection.classify_item('Updated an internal build step', 'chore'), 'chore')
        self.assertEqual(selection.classify_item('api: add an example parameter', 'feature'), 'feature')
        self.assertEqual(selection.classify_item('Improved CLI startup by 20%', None), 'change')

    def test_routine_summary_formats_and_heading_counts(self):
        for content in ['Bug fixes and reliability improvements',
                        '<p>Bug fixes and reliability improvements.</p>',
                        '## Changes\n- **Bug fixes and reliability improvements**',
                        '<h2>Bug fixes and reliability improvements</h2>',
                        '# Bug fixes and performance improvements\n']:
            with self.subTest(content=content):
                self.assertEqual(selection.release_counts(content),
                                 {'feature': 0, 'change': 0, 'breaking': 0, 'fix': 1, 'chore': 0, 'other': 0})
        counts = selection.release_counts('## Bug fixes\n- Fixed A\n- Fixed B')
        self.assertEqual(counts['fix'], 2)  # 見出しを3項目目として数えない
        counts = selection.release_counts('## Bug fixes and reliability improvements\n## Features\n- Added a setting')
        self.assertEqual(counts['fix'], 1)
        self.assertEqual(counts['feature'], 1)

    def test_unknown_negations_and_mixed_releases_remain_conservative(self):
        for text in ['', 'See the changelog.', 'No flags were removed.', 'Unrecognized release description']:
            with self.subTest(text=text):
                self.assertEqual(selection.release_verdict(selection.release_counts(text)), 'unknown')
        mixed = ('Bug fixes and reliability improvements\nAdded a new setting\n'
                 'internal: remove an old CI task\nRemoved the --legacy flag\nImproved startup')
        counts = selection.release_counts(mixed)
        self.assertEqual(counts, {'feature': 1, 'change': 1, 'breaking': 1, 'fix': 1, 'chore': 1, 'other': 0})
        self.assertEqual(selection.release_verdict(counts), 'notable')
        highlights = selection.pick_highlights([('v2', mixed)])
        self.assertIn('破壊的変更', highlights[0])
        self.assertIn('新機能', highlights[1])
        self.assertIn('変更・改善', highlights[2])
        self.assertFalse(any('reliability' in h or 'CI task' in h for h in highlights))
        # Merged PRsは雑務専用の見出しではない。Conventional形式でない追加も落とさない。
        self.assertEqual(selection.release_counts('## Merged PRs\n- Added a command\n- Fixed a crash')['feature'], 1)


class ReleaseCollection(Base):
    def test_adoption_grouping_index_and_repeat_run_follow_shared_classification(self):
        raw = yaml.safe_load(self.config.read_text())
        raw['feeds'][2]['select'] = 'release_notes'
        self.config.write_text(yaml.safe_dump(raw))
        root = ET.Element('feed', xmlns='http://www.w3.org/2005/Atom')
        bodies = [
            ('v4', '<ul><li>Removed the --legacy flag</li></ul>'),
            ('v3', '<ul><li>Added a command</li><li>internal: remove CI upload</li></ul>'),
            ('v2', '<p>Bug fixes and reliability improvements</p>'),
            ('v1', '<h3>Internal</h3><ul><li>Removed an obsolete workflow</li></ul>'),
        ]
        for version, content in bodies:
            entry = ET.SubElement(root, 'entry')
            ET.SubElement(entry, 'title').text = version
            ET.SubElement(entry, 'link', href=f'https://github.com/example/tool/releases/tag/{version}')
            ET.SubElement(entry, 'updated').text = '2026-10-18T00:00:00Z'
            ET.SubElement(entry, 'content', type='html').text = content
        self.feeds = {raw['feeds'][0]['url']: rss(), raw['feeds'][1]['url']: rss(),
                      raw['feeds'][2]['url']: ET.tostring(root)}
        code, out, err = self.run_collect(skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn('fixes_only=2', out)
        text = self.log_text()
        self.assertEqual(text.count('#### Tool'), 1)
        self.assertIn('2 リリース', text)
        self.assertIn('新機能 1 / 変更・改善 0 / 破壊的変更・廃止 1 / 修正 0', text)
        self.assertNotIn('CI upload', text)
        self.assertNotIn('reliability', text)
        seen = json.loads(self.seen.read_text())
        prefix = 'https://github.com/example/tool/releases/tag/'
        self.assertEqual(seen[prefix + 'v3']['grouped_into'], prefix + 'v4')
        for version in ('v1', 'v2'):
            self.assertEqual(seen[prefix + version]['excluded'], 'fixes_only')
        index = search_index.build_index(self.logs)
        self.assertEqual(len(index), 1)
        self.assertEqual(len(index[0]['releases']), 2)
        self.assertEqual(len(index[0]['highlights']), 2)
        self.assertEqual(self.run_collect(skip_brave=True)[0], 0)
        self.assertEqual(self.log_text(), text)
