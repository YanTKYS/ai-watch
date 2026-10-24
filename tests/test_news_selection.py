import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Base, ROOT, rss, collect  # noqa: E402

import selection
import selection_preview
import search_index


class NewsScoring(unittest.TestCase):
    def setUp(self):
        self.config = collect.load_config(ROOT / 'config/sources.yml')

    def keep(self, title, summary=''):
        points, _ = selection.score(self.config.selection, title, summary)
        return points >= self.config.selection.min_score

    def test_existing_changelog_technical_titles_survive(self):
        # 保存済みの代表的な見出し。RSSの説明文がなくても重要な更新を落とさない。
        for title in [
            'AI Scan for pull requests generally available',
            'Agentic autofix for code scanning alerts general availability',
            'Upcoming deprecation of selected GitHub Copilot models in mid-November',
            'Copilot model policy API for enterprise, orgs, and teams',
            'GitHub Copilot models deprecated on October 19, 2026',
            'Global default for Copilot features generally available',
            'Custom skills, agents, and MCP servers in usage metrics API',
            'Turn notifications into code with GitHub Copilot in Teams',
            'GitHub Copilot in Visual Studio — September update',
        ]:
            with self.subTest(title=title):
                self.assertTrue(self.keep(title))
        self.assertFalse(self.keep('Industry comparisons in the Copilot impact dashboard'))

    def test_reporting_family_and_programmatic_interfaces_are_distinct(self):
        for title in ['Copilot usage reports for business leaders', 'Copilot adoption analytics for team leads',
                      'ROI for Copilot teams', 'Return on investment report for GitHub Copilot']:
            with self.subTest(title=title):
                self.assertFalse(self.keep(title))
        for title in ['Copilot adoption analytics API', 'SDK for Copilot usage reports',
                      'CLI for Copilot impact dashboards', 'Copilot ROI reporting APIs',
                      'New code review controls in Copilot', 'Copilot rate limits and quota changes']:
            with self.subTest(title=title):
                self.assertTrue(self.keep(title))

    def test_technical_cases_research_and_availability_not_blanket_excluded(self):
        for title, summary in [
            ('How a retailer built a reproducible agent harness on the Responses API', 'Architecture and benchmark results.'),
            ('An update', 'We describe the architecture and report benchmark results.'),
            ('Gemini 10 system card', ''),
            ('Model inference API now available on Google Cloud', ''),
            ('Expanding API access in Europe', 'New regional endpoints are available now.'),
            ('Copilot data residency expands to Europe', ''),
            ('Copilot model policy API for organizations', ''),
            ('New API pricing and rate limits in Europe', ''),
        ]:
            with self.subTest(title=title):
                self.assertTrue(self.keep(title, summary))
        self.assertFalse(self.keep('How a bank equips employees with API access'))
        self.assertFalse(self.keep('How a retailer uses ChatGPT for stock planning'))
        # 既存の未確定例は、設定を変えても機械的な正解に変えない。
        raw = json.loads((ROOT / 'tests/fixtures/selection-evaluation.json').read_text())
        for slug in ('terminal', 'biology', 'cloud', 'languages', 'region'):
            self.assertIsNone(raw['expectations']['https://evaluation.example.org/' + slug]['expected'])

    def test_predeclared_news_validation_uses_shared_offline_quality_check(self):
        with redirect_stdout(io.StringIO()) as out, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('no network')) as network:
            code = selection_preview.preview(ROOT / 'config/sources.yml', None,
                                             ROOT / 'tests/fixtures/selection-news-validation.json', check_quality=True)
        self.assertEqual(code, 0)
        self.assertIn('confirmed=13 match=13 mismatch=0 pending=0', out.getvalue())
        network.assert_not_called()


class NewsCollection(Base):
    config_text = (ROOT / 'config/sources.yml').read_text()

    def feed_titles(self, titles):
        config = collect.load_config(self.config)
        self.feeds = {f.url: rss() for f in config.feeds}
        self.feeds['https://github.blog/changelog/feed/'] = rss(*[
            (title, f'https://github.blog/changelog/example-{i}', '2026-10-24')
            for i, title in enumerate(titles)])

    def test_new_reporting_rejection_persists_without_overwriting_prior_history(self):
        titles = ['Copilot model policy API for enterprise, orgs, and teams',
                  'Custom agents and MCP servers in the Copilot usage metrics API',
                  'GitHub Copilot models deprecated next month',
                  'Copilot data residency expands to Europe',
                  'Copilot code review supports repository instructions',
                  'Industry comparisons in the Copilot impact dashboard']
        self.feed_titles(titles)
        self.seen.parent.mkdir(parents=True)
        old = {'first_seen': '2026-10-18', 'excluded': 'customer_story'}
        self.seen.write_text(json.dumps({'https://old.example/kept': old}))
        code, out, err = self.run_collect(today='2026-10-24', skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn('adoption_reporting=1', out)
        seen = json.loads(self.seen.read_text())
        self.assertEqual(seen['https://old.example/kept'], old)
        self.assertEqual(seen['https://github.blog/changelog/example-5'],
                         {'first_seen': '2026-10-24', 'excluded': 'adoption_reporting'})
        articles = search_index.build_index(self.logs)
        self.assertEqual(len(articles), 5)
        self.assertNotIn('impact dashboard', self.log_text())
        self.assertEqual(next(a for a in articles if 'policy API' in a['title'])['category'], 'API・料金・制限')
        before = self.log_text()
        self.assertEqual(self.run_collect(today='2026-10-25', skip_brave=True, reconsider_excluded=True)[0], 0)
        self.assertEqual(self.log_text(), before)
        self.assertEqual(json.loads(self.seen.read_text())['https://github.blog/changelog/example-5']['first_seen'], '2026-10-24')
        self.assertEqual(self.brave_calls(), [])

    def test_limit_overflow_is_retriable_not_permanently_excluded(self):
        self.feed_titles([f'Copilot code review supports option {i}' for i in range(7)])
        code, out, err = self.run_collect(today='2026-10-24', skip_brave=True)
        self.assertEqual(code, 0, err)
        self.assertIn('over_limit=2', out)
        seen = json.loads(self.seen.read_text())
        self.assertEqual(len(seen), 5)
        self.assertFalse(any('excluded' in v for v in seen.values()))
        self.assertEqual(self.run_collect(today='2026-10-25', skip_brave=True)[0], 0)
        self.assertEqual(len(json.loads(self.seen.read_text())), 7)
        self.assertEqual(len(search_index.build_index(self.logs)), 7)
