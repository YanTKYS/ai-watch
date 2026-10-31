# ai-watch

生成AI（モデル・AIコーディング・エージェント・MCP・API料金/制限）の公式情報を日刊で収集し、GitHub Pagesで閲覧・全期間横断検索するツールです。

**[公開サイトを開く](https://yantkys.github.io/ai-watch/)** · [架空データのサンプル](https://yantkys.github.io/ai-watch/?sample)

月・日付別の閲覧、キーワード検索、カテゴリ・情報源・取得期間の絞り込み、表示条件・記事の共有URL、ライト/ダークモードに対応しています。閲覧・検索にAPIキーは不要です。Grokの日次候補とPerplexityの週次調査も、上部の表示切替から別枠で読めます（[表示方式・公開APIの制約](docs/import-reader.md)）。

## 情報源と保存方針

| 経路 | 役割 | 保存するもの |
| --- | --- | --- |
| 公式RSS / Atom・GitHub Releases | 選定した更新を日刊ログと検索に公開 | タイトル・URL・公開日・配信元等。リリースは項目数・原文の短い抜粋・個別リンクも保持 |
| Brave Search API | X・一般Web検索の取得品質を観測 | **利用件数と品質の集計のみ。検索結果を本番記事として保存しない** |

公式フィードはOpenAI News、Google DeepMind News、GitHub Changelog、Claude Code、OpenAI Codex、MCP仕様、Anthropic Python SDKの7件です。技術的な更新を選定し、同じ収集の採用リリースはフィードごとにまとめます。対象・対象外と選定方法は[情報源・記事選定](docs/source-quality.md)を参照してください。

Braveの結果URL・タイトル・説明文はログ・検索データ・Actionsログに保存しません。ストレージ権のない検索結果の保存・再公開を前提にしない方針です。[利用条件の根拠・API制御・品質集計](docs/collection-operations.md#braveの利用制御と保存制約)を確認してください。

## セットアップと基本操作

自分のリポジトリで運用する場合:

1. **Actions** タブでワークフローを有効化します。公式フィードの収集に外部APIのSecret・Variableは不要です。
2. Braveの品質観測も行う場合のみ、**Settings → Secrets and variables → Actions** にRepository secret **`BRAVE_API_KEY`**を登録します。未設定ならBraveだけをスキップします。
3. **Settings → Pages → Build and deployment → Deploy from a branch** で **`main` / `/ (root)`** を選びます。公開元へのcommitとPages配信の成功は別に確認します（[配信との境界](docs/collection-health.md#actionsでの記録と配信の境界)）。

- **定期収集**: `Collect AI news`（[collect.yml](.github/workflows/collect.yml)）は毎日 **JST 06:41（UTC 21:41）予定**。Actionsの開始は遅れる場合があります。`logs/`・`data/`の差分をcommitし、採用0件でも収集状態を更新します。
- **手動収集**: Actions → **Collect AI news → Run workflow**。`skip_brave`で公式フィードのみ実行できます。選定変更後の`reconsider_excluded`は[除外記事の再評価](docs/collection-operations.md#手動実行と除外記事の再評価)を参照してください。
- **設定変更**: [config/sources.yml](config/sources.yml)が入口です。変更前に通信・書き込みなしの`python scripts/collect.py --dry-run`で確認できます（[設定項目](docs/source-quality.md#設定の入口)・[比較と品質チェック](docs/selection-dry-run.md)）。

### ローカルで使う

リポジトリ直下で実行します。Python 3.12（CIと同じ）を推奨します。

```sh
pip install -r requirements.txt
# 実際に公式フィードへ接続し、logs/・data/を更新
python scripts/collect.py --skip-brave
# 保存済みログから検索インデックスを再生成（外部通信なし）
python scripts/search_index.py
# 静的サイトを確認
python -m http.server
```

`http://localhost:8000/`（サンプルは`http://localhost:8000/?sample`）を開きます。Braveも実行する場合は環境変数`BRAVE_API_KEY`を設定し、`--skip-brave`を外します。

テストは`python -m unittest discover -s tests`（APIキー不要・実行中の外部通信なし）。Node.jsがあればブラウザ側の関数も検証します。Chromium E2Eの依存導入と実行は[ブラウザテスト](docs/browser-tests.md)を参照してください。初回の依存取得には通信が必要です。

## 保存先と運用上の要点

| 保存先 | 役割 |
| --- | --- |
| `logs/YYYY/YYYY-MM.md` | 日刊記事の正本。本文全体や生成要約は保存しない |
| `data/seen.json` | URLの採用・除外・リリース集約履歴。既知の除外は通常再実行では復活しない |
| `data/months.json` / `data/search-index.json` | ログから作る月一覧と横断検索用データ |
| `data/brave-usage.json` | Braveの利用件数・品質集計 |
| `data/collection-status.json` | 公式フィード収集・検索生成の最後に公開された状態 |

収集・検索生成・Pages配信は別段階です。新着0件と取得失敗を区別して、[収集状況と鮮度](docs/collection-health.md)・[実行ログの調べ方](docs/collection-operations.md)を確認してください。

外部検索の検証は本番収集と分離しています。**PLaMoは2026年10月に検証済み・本番採用見送り**（[評価](docs/plamo-evaluation-2026-10.md)・[検証手順](docs/plamo-probe.md)）。Grokの`imports/x/`とPerplexityの`imports/p/`は原記録を別枠で閲覧でき、**公式ログ・検索への自動取り込みはありません**。X投稿の未確認事項と運用境界は[Grok評価](docs/grok-x-evaluation-2026-10.md)を参照してください。

## 詳細ドキュメント

| 用途 | 参照先 |
| --- | --- |
| 設定・記事選定 | [情報源・選定方針](docs/source-quality.md) / [dry-run・設定比較](docs/selection-dry-run.md) / [生成された情報源一覧](docs/source-inventory.md) |
| 運用・障害調査 | [実行・診断・Brave品質観測](docs/collection-operations.md) / [収集状況と鮮度](docs/collection-health.md) |
| 閲覧UI | [Grok・Perplexityの原記録](docs/import-reader.md) / [絞り込み](docs/article-filters.md) / [共有URL・履歴](docs/view-urls.md) / [キーボード・通知・再試行](docs/accessibility.md) |
| 検証・意思決定 | [ブラウザE2E](docs/browser-tests.md) / [PLaMo評価](docs/plamo-evaluation-2026-10.md) / [Grok評価](docs/grok-x-evaluation-2026-10.md) |
| 改善案 | [将来の候補と過去の棚卸](docs/feature-ideas.md)（採用決定・現行仕様とは別） |
