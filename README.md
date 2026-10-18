# ai-watch

生成AI（モデル・AIコーディング・エージェント・MCP・API料金/制限）の新着情報を日刊で収集し、
GitHub Pagesで閲覧・全期間横断検索するツールです（v0.1.0）。
[news-watch](https://github.com/YanTKYS/news-watch) の日刊収集・ログ形式・横断検索・UIを流用しています（週刊・月刊は持ち込んでいません）。

## 収集の仕組み

| 情報源 | 用途 | 保存するもの |
| --- | --- | --- |
| 公式フィード（RSS / Atom・GitHub Releases） | 日刊ログ・検索インデックス | タイトル・URL・公開日・配信元名のみ（本文・要約は保存しない） |
| Brave Search API（X検索2件・一般Web検索2件） | 取得品質の評価 | **件数の集計のみ**（検索結果のURL・タイトル・説明文は保存しない） |

- Brave Search APIの[利用規約](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service)は、
  ストレージ権付きプラン以外での検索結果の保存・キャッシュ・データベース化を認めていません。
  そのため検索結果は実行中のメモリ上で集計に使うだけで、`logs/`・`data/seen.json`・`data/search-index.json`・Actionsログには出しません。
  X投稿もX側のデータを保存・再公開しません（X APIやページ本文の取得もしていません）。
- 公式フィードは初期段階では次の6件に絞っています（`config/sources.yml`）。
  OpenAI News / Google DeepMind News / GitHub Changelog（AI関連の記事のみ）/ Claude Code Releases /
  OpenAI Codex Releases（プレリリース除外）/ MCP Specification Releases。
  Anthropicのニュースには公式RSSが無いため、Claude Code の GitHub Releases を使っています。
- Jev・Gemini は v0.1.0 では呼び出しません（ワークフローにもキーを渡していません）。

## セットアップ

1. **Settings → Secrets and variables → Actions** に Repository secret `BRAVE_API_KEY` を登録します（登録済み）。
   未設定でも公式フィードの収集は動き、Brave検索だけを飛ばします。
2. **Actions** タブでワークフローを有効化します。
3. **Settings → Pages → Build and deployment → Deploy from a branch → `main` → `/ (root)`** で公開します。

## 実行

- **自動実行**: 毎日 JST 6:41 頃（`.github/workflows/collect.yml`。news-watch の 7:17 と時刻をずらしています）。
  変更があったときだけ `logs/`・`data/` をcommitします。
- **手動実行**: Actions → `Collect AI news` → Run workflow。`skip_brave` を選ぶと公式フィードだけを取得します。
- **ローカル実行**（任意）: `pip install -r requirements.txt` のあと `python scripts/collect.py [--skip-brave]`
  （Brave検索をする場合は環境変数 `BRAVE_API_KEY`）。検索インデックスは `python scripts/search_index.py` で再生成します。
- **テスト**（APIキー不要・通信なし。Node.js があればブラウザ側の検索関数も確認）: `python -m unittest discover -s tests`

## API利用量の制御（Brave Search API）

- 1日（JST）最大4リクエスト（`scripts/brave.py` の `MAX_DAILY_REQUESTS`。設定 `brave.daily_limit` で下げられますが上げられません）。
  検索語が上限を超える設定はAPIを呼ばずにエラーで停止します。
- **1日1回だけ**実行します。同じ日に再実行（手動実行を含む）してもAPIは呼びません。
- 利用件数は `data/brave-usage.json` に日付ごとに記録し、各リクエストの直前に書き込みます。
  このファイルが読めない場合はAPIを呼びません。収集ステップが失敗してもcommitします。
- 1検索語につき1リクエスト（`count=20`）。ページング・自動リトライなし。
- 月の上限は 4 × 31 = 124 リクエスト。news-watch（現在 5検索語/日 ≒ 155/月）と合わせても約280/月です。

## 設定（`config/sources.yml`）

コードを変えずに次を調整できます。

- `categories`: カテゴリ（ログの見出し・表示順）と、フィード記事の分類に使うキーワード。`classify_order` で優先順位を指定。
- `feeds`: 公式フィード（上限10件）。`category`（既定の分類）、`classify`、`require_keywords`（いずれかの語を含む記事だけを収集）、
  `title_prefix`、`exclude_title_patterns`（正規表現）。`max_age_days` より古い記事は収集しません。
- `brave.queries`: 検索語（`id`・`kind: x|web`・`category`・`q`・`search_lang`・`country`・`freshness`）。
  `kind: x` には `site:x.com` を含めます。
- `quality`: 品質集計に使う語（根拠を示す語・誇張表現）。

## X検索の取得精度の確認

Actionsログの `Brave ...` 行と `data/brave-usage.json` に、検索語ごとの件数が残ります。

| 項目 | 意味 |
| --- | --- |
| `results` | 結果件数 |
| `x_posts` / `x_profiles` / `x_other` / `non_x` | 実際の投稿（`x.com/{user}/status/{id}`）／プロフィール／その他のx.comページ／x.com以外 |
| `x_authors` | 投稿者の種類数 |
| `dated` / `recent` | 公開日あり／7日以内 |
| `on_topic` / `evidence` / `hype` | カテゴリのキーワード／根拠（リリースノート・ベンチマーク・検証・バージョン番号など）／誇張表現を含む件数 |
| `candidates` | 保存できるなら採用候補になる件数（話題に一致・誇張なし・7日以内・Xは実際の投稿のみ） |
| `duplicates` / `official_overlap` | 同じ実行の別の検索語で既出／公式フィードで収集済み |

実行の最後に直近7日間の集計（`x_post_rate` など）も表示されます。投稿者の人気・フォロワー数は判定に使いません。
精度が不十分な場合は `brave.queries` の検索語・`freshness` を調整してください。

## 出力

- `logs/YYYY/YYYY-MM.md`: 日付 → カテゴリ → 記事（`URL`・`Source`・`Feed`・`Published`・`Retrieved`）。
- `data/seen.json`: 収集済みURL（重複排除）。`data/months.json`: 月の一覧。
- `data/search-index.json`: 横断検索用インデックス（`logs/` の派生データ）。
- `data/brave-usage.json`: Brave APIの利用件数と品質集計（直近90日）。

URLが異なる同一話題は、まず実際の収集状況を確認するため、タイトルが同じ記事の件数をActionsログに出すだけにしています。

## GitHub Pagesで読む

`index.html` / `parser.js` / `app.js` / `style.css` / `favicon.svg`。日付別・カテゴリ別のカード表示、月の切り替え、
新しい順／古い順、全期間横断検索（タイトル・カテゴリ・情報源・配信元。部分一致・空白区切りのAND・50件ずつ追加表示）、
ライト／ダークモードに対応しています。検索は `data/search-index.json` をブラウザで読むだけで、外部APIは使いません。

- 公開URL例: `https://yantkys.github.io/ai-watch/`
- サンプルデータ（架空の記事、`samples/`）: `https://yantkys.github.io/ai-watch/?sample`
- ローカル確認: リポジトリ直下で `python -m http.server` を起動し、`http://localhost:8000/`（サンプルは `/?sample`）を開きます。

## 今後の拡張

- X公式APIへ移行する場合は `scripts/brave.py` の `search()` を差し替えます（品質集計 `evaluate()` はそのまま使えます）。
- 検索結果の保存は、ストレージ権の付いたプラン・各サービスの利用条件を確認してから検討します。
- Jev（関連性判定）・Gemini（週刊・月刊）は、収集品質と利用条件を確認したうえで導入を判断します。
