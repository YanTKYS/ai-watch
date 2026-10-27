# PLaMo Web検索の独立検証

本番への採用判断に向けた手動の評価だけを行う。オーナーがPRレビュー後に実APIを実行する。実装・単体テストではPLaMo APIや引用先へアクセスしない。

## 公式情報の確認（2026-10-27）

- [API利用方法](https://docs.plamo.preferredai.jp/ja/getting-started) と [APIリファレンスのWeb検索](https://docs.plamo.preferredai.jp/ja/api#web-検索) を参照。`POST https://api.platform.preferredai.jp/v1/chat/completions`、`plamo-3.1-prime`、Bearer認証、`web_search_options.search_context_size=low` を使う。
- 非ストリーミング応答の `choices[0].message.content` を短い要点にし、引用は `message.annotations[].url_citation` から抽出する。本文中のリンクを構造化引用として推測しない。`response_format` は引用が返らなくなるため使わず、検索と併用できない `temperature`・`n`・`tools` 等も送らない。
- トークン数は `usage` の3項目。Web検索回数は `plamo_usage_details` 内で `usage_type=web_search` の `token_consumed` の合計。欠落・不正・部分的な内訳は「不明」で、0やAPI要求数に置き換えない。`finish_reason=length` は打ち切りと案内する。
- [料金・データの扱い](https://docs.plamo.preferredai.jp/ja/pricing): 検索にはトークンとは別の費用があり、1回答で複数回検索しうる。Standardの検索単価キャンペーンは2027-01-31まで。Freeの入力・出力は保存・学習対象で、Web検索ではクエリや閲覧先URLが外部検索サービスへ送られる。個人情報を入力しない。
- [公式Chatマニュアル](https://docs.plamo.preferredai.jp/ja/chat#利用上限とデータの取り扱い) のFree Web検索は2026-11-30までの日次60回・月次200回という案内で、Deep Researchと共通。これをキー所有アカウントの残量や、将来のAPI無料保証とは扱わない。プラン・最新条件・アカウント全体の使用量はオーナーが実行前に確認する。
- [公式利用規約](https://plamo.preferredai.jp/info/terms) へのリンクは確認したが、調査ツールでは本文を取得できず、生成要点・引用URLの保存に関する個別条項は未確認。保存が無制限に許されるとは判断しない。オーナーはレビュー・実行前に最新条項と第三者出典の条件を確認し、許容できる場合だけ実行を選択する。

保存は短い生成要点と出典URL・タイトル・計測値に限定する。検索結果一覧・ページ本文・長文引用・reasoning・レスポンス全体は保存しない。Braveの検索結果・利用条件や既存保存仕様は変更せず、この検証のデータとも混ぜない。

## Actionsでの実行（レビュー後にオーナーが行う）

1. マージ後、Actionsの **PLaMo Web search probe (manual only)** → **Run workflow**。GitHubの新規手動ワークフローは既定ブランチにファイルが存在してから表示・起動できる。
2. `confirm_one_request=false` の既定では、調査期間・プロンプト・設定・照合用seenスナップショット情報のレポートだけを作る。通信・無料枠消費は0。
3. 規約・費用・残量を確認して `confirm_one_request=true` を選ぶと、登録済みのRepository Secret `PLAMO_API_KEY` を実行ステップにだけ渡し、1 POSTを試行する。401/429/5xx/タイムアウトでも再試行しない。リダイレクトにも追従しない。
4. Job Summaryおよび **plamo-probe-実行ID-試行番号** Artifactの `report.md` / `report.json` を確認する。API失敗でも整形した報告を残し、ジョブは失敗として扱う。Artifact保持は3日。Job Summaryや実行ログの保持はArtifactとは別のGitHub設定で、3日後の自動消去は保証しない。

自由入力のプロンプト・APIエンドポイント・モデル・ページング・クエリ展開・リトライ設定は設けない。`max_tokens=2048`、`reasoning_effort=none`、90秒タイムアウト、1MBの応答読み取り上限。これらは検索回数・入力トークン・費用の完全な上限ではない。並行起動は直列化するが、再実行は新たな1要求を消費する。日次・月次の永続カウンタやアカウント全体の使用量APIは利用しない。

キー・認証ヘッダー・HTTPエラー本文・未加工例外をログに出さない。レポートはフィールドを限定して生成し、既知のキーを伏せ、外部文字列をHTMLエスケープしたpre内で表示する。認証情報付き・非公開向け・不正URLは保存しない。URLを検証するための追加アクセスも行わない。

## 調査期間・再現用情報・比較の意味

日本時間の実行日を含む7暦日を調査する（両端含む、最終日は実行時点まで）。固定の公開ニュース調査プロンプトで、生成AI新モデル・AIコーディング・エージェント/MCP・API料金/制限をまとめて問い合わせる。公開日・発表元・一次情報URLを重視し、未確認の事実・期間外の記事は採らないよう指示する。

UTC実行日時、日本時間の期間、モデル、固定パラメータ、プロンプト全文と版、`seen.json` のSHA-256/URL数を記録する。同じ入力でも生成結果・検索対象が同じになる保証はない。

- 同一回答内の引用を、元の文字列の完全一致で重複除去する。追跡パラメータ・フラグメント・末尾スラッシュも保持する。
- `data/seen.json` のキーと完全一致した数、採用済み/リリース統合URLとの一致、不採用URLとの一致、未記録の新規引用候補数を分けて表示する。不採用として既知のURLを、新規候補や収集済み記事と誤表示しない。
- seenを読めない場合はAPIを呼ばず失敗する。既知URLを誤って新規と数えない。
- 引用は最大100 URL、タイトル160文字、回答は最大6行×160文字。上限超過・引用なし・使用量不明・打ち切りを案内する。
- これらはURL照合とプロバイダー申告値の集計。記事内容の重複、ニュースの新規性、公開日の正しさ、一次情報性、関連性・重要度はオーナーが出典を確認して判断する。

## ローカル確認とCI

APIキーなし・ネットワークなしで確認できる。

```sh
python scripts/plamo_probe.py --output-dir work/plamo-probe
python -m unittest discover -s tests -p test_plamo_probe.py -v
python -m unittest discover -s tests
```

`--live` は実API送信の明示指定であり、開発・CIでは使わない。出力先はリポジトリ内なら `work/` 以下だけを認め、`logs/`・`data/`・Pagesへ書かない。既存データは照合用の読み取りだけで、収集・再生成・commitは起動しない。

既存の `test.yml` にこの作業ブランチ `feat/plamo-manual-probe` のpushを追加し、**PRを作成する前に**キー不要のunit/品質チェック/Chromium CIを通す。PLaMoの新規ワークフロー自体は `workflow_dispatch` だけで、pushやPRから実APIを呼ばない。PR作成後も既存のPR CIを実行し、マージとAPI検証はオーナーに委ねる。
