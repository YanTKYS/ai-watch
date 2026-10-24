# 情報源一覧（生成物）

対象: 2026-10-18〜2026-10-24（記事は取得日、除外URLはfirst_seen基準）。

`scripts/source_report.py` により現行設定・Markdownログ・seenから生成。手編集しない。
公式性・有用性・到達性の評価は [source-quality.md](source-quality.md) を参照。

| 情報源 / 設定URL | 既定カテゴリ / タイトルによる再分類 | 選定 / タイトル必須語 / プレリリース等除外 | 保存記事 | 集約内の追加URL | 除外URL（推定） | 最新取得記事日 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| OpenAI News (https://openai.com/news/rss.xml) | AIモデル / あり | score / なし / なし | 4 | 0 | 27 | 2026-10-23 |
| Google DeepMind News (https://deepmind.google/blog/rss.xml) | AIモデル / あり | score / なし / なし | 2 | 0 | 4 | 2026-10-18 |
| GitHub Changelog (https://github.blog/changelog/feed/) | AIコーディング / あり | all / あり / なし | 10 | 0 | 0 | 2026-10-24 |
| Claude Code Releases (https://github.com/anthropics/claude-code/releases.atom) | AIコーディング / なし | release_notes / なし / なし | 7 | 4 | 1 | 2026-10-24 |
| OpenAI Codex Releases (https://github.com/openai/codex/releases.atom) | AIコーディング / なし | release_notes / なし / あり | 2 | 0 | 0 | 2026-10-24 |
| MCP Specification Releases (https://github.com/modelcontextprotocol/modelcontextprotocol/releases.atom) | MCP・連携技術 / なし | release_notes / なし / なし | 0 | 0 | 0 | — |
| Anthropic SDK Releases (https://github.com/anthropics/anthropic-sdk-python/releases.atom) | MCP・連携技術 / なし | release_notes / なし / あり | 4 | 4 | 0 | 2026-10-24 |

保存記事合計: 29件。うち現行設定にないFeed: 0件。
除外URL合計: 32件（未帰属: 0件）。

| 保存された除外理由 | URL数 |
| --- | ---: |
| customer_story | 11 |
| education_program | 2 |
| fixes_only | 1 |
| low_score | 12 |
| partnership | 1 |
| policy_society | 4 |
| responsibility | 1 |

## 数値の読み方

- 保存記事はURL重複排除後のカード数。集約内の追加URLはseenのgrouped_intoで対応付ける。合計はリリースの全変更項目数ではない。
- 除外はseenに残るURLの状態で、採否試行回数ではない。first_seenは最終除外日ではなく、再評価で状態が変わり得る。
- 除外のFeedは保存されていない。GitHubは設定内のリポジトリのreleases/tag/、その他は設定内で一意の同一ホストから推定。複数候補は未帰属。設定変更で推定は変わる。
- 年齢・必須語・プレリリース・重複による事前除外、over_limitはこの除外数に含まれない。分母がないため採用率は算出しない。
- 最新取得記事日は最終フィード取得成功日ではない。0記事は取得失敗を意味しない。取得成否はActionsのfeed ok/failedログで別途確認する。
