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
- 公式フィードは次の7件です（`config/sources.yml`）。
  OpenAI News / Google DeepMind News / GitHub Changelog（AI関連の記事のみ）/ Claude Code Releases /
  OpenAI Codex Releases（プレリリース除外）/ MCP Specification Releases / Anthropic SDK Releases。
  Anthropicのニュースには公式RSSが無いため、Claude Code と公式SDK（Claude API の変更）の GitHub Releases を使っています。
- **記事の選定**（v0.1.3）: 基準は「読むと AI・AIコーディングツールについて新しい技術的知見が得られるか」です。
  - 幅広い記事を配信するニュース（OpenAI・DeepMind）は、タイトル・説明文に `selection.rules` で点数を付け、
    新モデル・提供開始・API・料金変更・技術的な検証などを採用し、導入事例・政策・教育などは原則として採用しません
    （減点の規則があっても、技術的な信号が十分あれば採用されます）。1回の収集で1フィードから最大5件で、
    上限を超えた記事は記録せず、次回の収集で（公開から7日以内なら）改めて評価します。
  - リリース（Claude Code・Codex・MCP・SDK）は、リリースノートの項目を「新機能・変更・破壊的変更・修正・雑務」に機械的に分類し、
    修正・雑務だけのリリースを除外します。判定できないリリースは見落とさないよう採用します。
    同じ収集で採用したリリースは1件にまとめ、項目数（`Notes`）、公式リリースノートから機械的に選んだ最大3項目
    （`Highlight`。破壊的変更 > 新機能 > 変更の順、原文のまま・バージョン付き）、各リリースへのリンク（`Release`）を添えます。
    要約や翻訳は作らず、項目を判定できない場合は抜粋しません。
  - 不採用の記事は理由とともに `data/seen.json` に記録し（`excluded`）、次回以降に復活させません。
    選定ルールを変えた後は、手動実行の `reconsider_excluded`（`--reconsider-excluded`）で、
    フィードに残っている（7日以内の）不採用記事を現在の設定で再評価できます。
    Actionsログに記事ごとの点数・判定・理由と、理由別の件数（`rejected by selection`）が出ます。
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
  `reconsider_excluded` を選ぶと、不採用として記録済みの記事を現在の選定ルールで再評価します。
- **ローカル実行**（任意）: `pip install -r requirements.txt` のあと `python scripts/collect.py [--skip-brave]`
  （Brave検索をする場合は環境変数 `BRAVE_API_KEY`）。検索インデックスは `python scripts/search_index.py` で再生成します。
- **テスト**（APIキー不要・通信なし。Node.js があればブラウザ側の検索関数も確認）: `python -m unittest discover -s tests`
  公式フィードの解析は、実際の配信形式（RSS 2.0・WordPress・GitHub Releases の Atom）を模した合成データ `tests/fixtures/` で確認しています。
  実サイトから取得できるかは、GitHub Actions での実行ログで確認してください。フィードごとに
  `feed ok: ... status=200 content_type=... entries=N` が出ます。失敗したフィードは `feed failed` の次の行の
  `diagnostics:` に、HTTPステータス・Content-Type・先頭の形式（`start=xml-declaration` / `html` など）・
  XMLの解析失敗位置と前後30文字が出ます（本文全体は出しません）。Brave枠を使わずに確認する場合は `skip_brave` で手動実行します。
  `Content-Encoding: gzip` のフィード（Google DeepMind News など）は展開してから解析します
  （受信データ10MB・展開後30MBまで。`bytes` は受信時、`decoded_bytes` は展開後のサイズ）。

## API利用量の制御（Brave Search API）

- 1日（JST）最大4リクエスト（`scripts/brave.py` の `MAX_DAILY_REQUESTS`。設定 `brave.daily_limit` で下げられますが上げられません）。
  検索語が上限を超える設定はAPIを呼ばずにエラーで停止します。
- **1日1回だけ**実行します。同じ日に再実行（手動実行を含む）してもAPIは呼びません。
- 利用件数は `data/brave-usage.json` に日付ごとに記録し、各リクエストの直前に書き込みます。
  このファイルが読めない場合はAPIを呼びません。収集ステップが失敗してもcommitします。
- 1検索語につき1リクエスト（`count=20`）。ページング・自動リトライなし。
- 月の上限は 4 × 31 = 124 リクエスト。news-watch（現在 5検索語/日 ≒ 155/月）と合わせても約280/月です。

## 設定（`config/sources.yml`）

選定ルールを変える前に `python scripts/collect.py --dry-run` で、同梱の合成データを通信・書き込みなしで評価できます。
`--compare-config` と `--reconsider-excluded` による比較例・結果は [選定ルールのdry-run](docs/selection-dry-run.md) を参照してください。
`--evaluate` で確定した期待値との一致・不一致・要確認を集計し、`--check-quality` では固定した重要例の不一致を終了コード3で検出できます。

情報源の役割・収集範囲・記事の有用性・追加候補は [情報源の品質評価](docs/source-quality.md)、
設定と保存実績の一覧は [情報源一覧](docs/source-inventory.md) を参照してください。
一覧は `python scripts/source_report.py --since YYYY-MM-DD --until YYYY-MM-DD` で再集計できます
（通信なし・収集データの変更なし、更新手順と数値の注意点は品質評価資料に記載）。

コードを変えずに次を調整できます。

- `categories`: カテゴリ（ログの見出し・表示順）と、フィード記事の分類に使うキーワード。`classify_order` で優先順位を指定。
- `feeds`: 公式フィード（上限10件）。`category`（既定の分類）、`classify`、`select`（`all` / `score` / `release_notes`）、
  `require_keywords`（いずれかの語を含む記事だけを収集）、`title_prefix`、`exclude_title_patterns`（正規表現）。
  `max_age_days` より古い記事は収集しません。
- `selection`: 記事の点数付け（`min_score`・`max_new_per_feed`・`rules`）。規則は `label`・`weight`・`in`
  （`title` / `summary` / `any` / `categories`）・`terms` / `patterns` で書きます。
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

- `logs/YYYY/YYYY-MM.md`: 日付 → カテゴリ → 記事（`URL`・`Source`・`Feed`・`Notes`・`Highlight`・`Release`（リリースのみ）・`Published`・`Retrieved`）。
- `data/seen.json`: 収集済みURL（重複排除）。不採用の記事は `excluded`（理由）、1件にまとめたリリースは `grouped_into` を持ちます。
  `data/months.json`: 月の一覧。
- `data/search-index.json`: 横断検索用インデックス（`logs/` の派生データ）。
- `data/brave-usage.json`: Brave APIの利用件数と品質集計（直近90日）。

URLが異なる同一話題は、まず実際の収集状況を確認するため、タイトルが同じ記事の件数をActionsログに出すだけにしています。

## GitHub Pagesで読む

`index.html` / `parser.js` / `app.js` / `style.css` / `favicon.svg`。日付別・カテゴリ別のカード表示、月の切り替え、
新しい順／古い順、全期間横断検索（タイトル・カテゴリ・情報源・配信元。部分一致・空白区切りのAND・50件ずつ追加表示）、
ライト／ダークモードに対応しています。検索は `data/search-index.json` をブラウザで読むだけで、外部APIは使いません。
検索結果にもリリースの項目数・主な変更・各バージョンへのリンクを表示し、抜粋にない個別バージョン名でも検索できます。
月一覧・日刊ログ・検索データの読み込みに失敗した場合は、表示される「再試行」から月・並び順・検索語を保って読み直せます。

- 公開URL例: `https://yantkys.github.io/ai-watch/`
- サンプルデータ（架空の記事、`samples/`）: `https://yantkys.github.io/ai-watch/?sample`
- ローカル確認: リポジトリ直下で `python -m http.server` を起動し、`http://localhost:8000/`（サンプルは `/?sample`）を開きます。

## 今後の拡張

- X公式APIへ移行する場合は `scripts/brave.py` の `search()` を差し替えます（品質集計 `evaluate()` はそのまま使えます）。
- 検索結果の保存は、ストレージ権の付いたプラン・各サービスの利用条件を確認してから検討します。
- Jev（関連性判定）・Gemini（週刊・月刊）は、収集品質と利用条件を確認したうえで導入を判断します。
