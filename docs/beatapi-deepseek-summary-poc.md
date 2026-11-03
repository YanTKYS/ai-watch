# BeatAPI DeepSeekによるニュース要約・横断整理PoC

既に公開した公式ニュース記録を、記事別の短い日本語要約と複数記事の共通点・相違点に整理できるか、人が評価する独立した手動PoC。[Issue #47](https://github.com/YanTKYS/ai-watch/issues/47)の実装であり、本番採用・自動記事採用ではない。**この実装PRではライブAPIを呼ばない。オーナーがレビュー・マージした後、mainの手動Actionsで実行する。**

## 対象と前PoCとの差

モデルは`deepseek-v4.1-flash-free`、送信先は`POST https://direct.beatapi.io/v1/chat/completions`だけ。`stream:false`、`max_tokens:2048`を要求し、JSON mode・tools・検索・推論オプションを指定しない。他モデル・有料兄弟ID・別APIへのフォールバック、モデル一覧取得、チャージは行わない。

公式資料確認日: 2026-11-03。[無料モデルと制限](https://docs.beatapi.io/free-models)では無料専用IDのトークン単価はないと案内されるが、コンテキスト・出力上限・速度・提供継続は保証されない。[DeepSeek Chat Completions](https://docs.beatapi.io/api-reference/text-api/deepseek-chat-completions)の仕様を参照するが、有料版の能力を無料IDへ当てはめない。**実請求額・残高変化は本PoCでも別途未確認**とする。

[poc-lab/beatapi](https://github.com/YanTKYS/poc-lab/tree/main/beatapi)の2026-11-03初回実測は、架空文1件・1回のDeepSeek要約/分類でHTTP 200、JSON成立、簡易判定合格、13,803ms、599 tokensだった。生成全文を保存しておらず、実ニュース複数件の横断整理・日本語品質・事実整合性・安定性の確認ではない。

今回は既存公式ニュースを最大6件送り、検証済みの**実際の生成文**をJob Summaryと1日artifactに保存して人手評価する。前PoCの通信制限を参考にするが、poc-labのコード・Workflow・データは変更しない。

## 入力と再現可能な選定

CLIの入力は`data/search-index.json`に固定する。別ファイル指定・インデックス再生成・原サイト本文取得はできない。`data/seen.json`、環境変数、Secrets、Actionsログ、非公開データ、`imports/x|p|m`、Brave結果を入力へ足さない。参照URLを保存するだけで、そのURLへ通信する処理はない。

`latest-category-first-v1`の選択規則:

1. UTF-8のJSON配列を読み、現在の公式7フィード名と対応するホスト・パス、実在する取得日/公開日を検査する。将来のフィード追加はPoC側もレビューして許可する。
2. 取得日の降順、公開日の降順、正規化URLの昇順、許可項目のJSONの昇順で決定的に並べる。公開日欠損は`null`とし、取得日で補完しない。
3. URLを重複排除する（比較時のみURL正規化・フラグメント除去。参照には元レコードのURLを保持）。まず各カテゴリの最新記事を1件ずつ、最大6件まで選ぶ。残枠は未選択の最新記事で埋める。カテゴリ数が少なくても架空の多様性を作らない。
4. IDは比較用URLのSHA-256先頭16桁に`a-`を付ける。入力全体のSHA-256、選択ID、選定規則版、取得日範囲、入力文字数をレポートへ記録する。同じファイル内容から同じ選定を再現できる。カテゴリの代表性を優先するため、単純な上位6件より古い記事が含まれる場合がある。

送信項目はID、タイトル、原URL、配信元・ホスト、カテゴリ、Published、Retrieved、notes、highlights、根拠範囲・切断記録に限定する。元の`releases`や未知フィールドもコピーしない。

| 上限 | 値 |
| --- | --- |
| 入力ファイル | 2,000,000 bytes、通常ファイルのみ |
| 記事 | 最大6件、URL512文字以内 |
| 記事文字列 | タイトル180字、カテゴリ60字、notes300字、highlights最大3件×180字 |
| 記事JSON / 全入力JSON | 1,900 / 12,000 Unicodeコードポイント以内 |
| 出力要求 | 2,048 tokens（無料モデルの保証値ではない） |
| API応答 / 生成JSON | 65,536 bytes / 6,000 Unicodeコードポイント以内 |
| ライブ要求全体 | ヘッダー待ち・本文読込を含め90秒、1要求のみ |

長文は上記の欄単位で切断して記録し、原データは変更しない。URLは切断せず、不適切なURL・非公式フィード・不正日付のレコードは候補から除外する。空入力・候補0件・不正JSON・予算超過・認証文字列の混入は通信前に停止する。検査は機密情報を網羅検知する保証ではなく、公開済みの公式ニュース派生データだけを読む境界と組み合わせる。

## プロンプトとスキーマ

プロンプト版は`ai-watch-beatapi-summary-v1`。全文は[scripts/beatapi_deepseek_summary.cjs](../scripts/beatapi_deepseek_summary.cjs)の`payload()`を参照する。systemメッセージで入力資料を信頼できないデータと宣言し、userメッセージ内のJSONを専用区切りで包む。資料中の山括弧等はJSONのUnicodeエスケープにして区切りを閉じられなくする。資料中の命令へ従わず、URLアクセス・事実追加・将来予測・検証済み判定をしないよう求める。

Publishedは原記事の公開日、Retrievedは当サイトの取得日。どちらも本文取得済みを意味しない。notes/highlightsがない記事は`evidence_level:title_metadata`、ある場合は`notes_highlights`。前者の要約には必ず「タイトルから確認できる範囲」を含める。後者も、抜粋が原記事の全情報であるとは扱わない。

要求JSONの形（合成例）:

```json
{
  "articles": [
    {"id": "入力ID1", "summary": "タイトルから確認できる範囲：機能公開の案内です。", "basis": "title_metadata"},
    {"id": "入力ID2", "summary": "提供された抜粋では対応機能を案内しています。", "basis": "notes_highlights"}
  ],
  "themes": [
    {"title": "機能の更新", "article_ids": ["入力ID1", "入力ID2"], "common": "共通点です。", "differences": "対象機能が異なります。", "takeaway": "原記事で対象範囲を確認してください。"}
  ]
}
```

全記事IDが1回ずつ必要。basisは入力と一致させる。要約は日本語1〜2文・180字以内、テーマは0〜3件で、各テーマに異なる既知IDを2件以上付ける。関連が乏しければ0テーマでよい。同じID集合の重複テーマ、追加キー、未知/重複/欠損ID、URL生成、HTML/不審なMarkdown/制御文字、過長な欄、既知キー・認証文字列の混入を拒否する。

JSON囲み除去・構造補修・別モデルでの修正は行わない。重複JSONキー、過度の入れ子、モデル不一致、`finish_reason`が`stop`以外、空・不正な応答も失敗にする。生成URLを受け入れる欄はなく、出典は**検証済み入力IDからプログラム側で付与**する。

## 手動Actionsの手順と停止条件

1. このPRをオーナーがレビューし、ユーザーがmainへマージする。PRや未レビューのブランチでライブ動作を試さない。
2. Actions → **BeatAPI DeepSeek news summary PoC** → Run workflow。ブランチは`main`、`confirm_one_request`は既定のfalseで実行し、入力記事・選択ID・SHA-256・日付・根拠範囲をJob Summaryで確認する。登録済みSecretの表示・再登録・取得は不要。
3. 送信可能な公開データであること、モデルID、現在の公式制限、同一アカウントの他PoC実行を確認する。データが更新されていれば新しい事前確認を行う。
4. 送信する場合だけ新たに手動実行し、`confirm_one_request:true`にする。同じcheckout内でキー不要のモックテスト・入力確認を行った後、ライブステップ1か所だけへ`secrets.BEAT_API_KEY`を渡す。コード側もmain・Workflow名・リポジトリ・明示確認・初回attemptを検査する。
5. 成否を問わずJob Summaryと`beatapi-summary-<run_id>-<run_attempt>`の`report.json`/`report.md`を確認する。artifactは1日。生成内容は未検証で、本番サイト等へ自動保存しない。

Workflowは`workflow_dispatch`だけで、push/PR/scheduleでは起動しない。main以外はジョブをスキップする。権限は`contents:read`、checkoutは`persist-credentials:false`。ジョブは5分、同Workflowの同時実行は直列化するが、**poc-lab等の別Workflowを含むアカウント全体の制限は保証しない**。

無料枠は初回チャージ前、アカウント全体で成功1回/分。前の成功から少なくとも60秒以上、余裕を持って空け、同じキー・アカウントの別実行も確認する。429・HTTP失敗・タイムアウトの直後に自動/即時再実行しない。タイムアウトでもサーバー側生成が取り消されたとは断定できない。401/403は設定・権限を確認し、モデル不一致では原因確認まで止める。リダイレクト・自動再試行・待機ループはなく、HTTPエラー本文は読まない。

Actionsの「Re-run jobs」ではライブステップをスキップし、入力確認だけを行う。追加のライブ試験には、前回の状況を確認してから新たな手動dispatchが必要。無料モデルの提供継続や実請求額を確認済みとは扱わない。

## 結果の読み方・人手評価

`plan_only`は未送信、`schema_valid_unverified`は構造検査だけ成功、`failed`は定型reasonで停止。`requests_sent`は0/1で、サーバーの受理回数を保証しない。HTTP、許可済み応答モデル、安全な応答ID、finish_reason、使用量、経過時間も記録する。使用量・応答IDの欠損/不正値は`null`。生レスポンス・推論文・HTTPエラー本文・認証ヘッダー・Secretは保存しない。

実際の短い要約・共通点・相違点・読者向けの整理は、検証成功時だけ全文保存する。危険な文字列や不正JSONの一部を修復・転載しないため、失敗時は生成文を残さずreasonと観察値を確認する。入力メタデータとモデル生成結果は別欄で、Job Summaryでは外部文字列をHTMLエスケープしたpre内のテキストとして表示する。

artifactのコピーで各`human_review`を人が記入する。記事別は事実整合性・提供情報による裏付け・自然な日本語・重要情報の欠落、テーマ別は無理な関連づけ・重複・有用性を、原記事と入力の両方に照らして評価する。モデルが入力にない事実を足していないか、タイトルだけの記事を本文既読のように説明していないか、PublishedとRetrievedを混同していないかも確認する。構造合格を文章品質や採用の合格へ自動変換しない。

## オフライン検証とローカル事前確認

Node.js 22以上の標準ライブラリのみで動く。追加のSDK・npm依存は不要。

```sh
node --test tests/test_beatapi_summary.cjs
python -m unittest discover -s tests
# 固定入力から計画だけを保存。キー・通信は不要
node scripts/beatapi_deepseek_summary.cjs --output-dir /tmp/ai-watch-beatapi-summary
```

ローカルの`--live`はActionsの実行条件を満たさなければ拒否する。キーをローカルへコピーして試す手順は設けない。CLIの入力は固定、出力は一時領域・ActionsのRUNNER_TEMP・リポジトリのwork以下に限り、既存本番ディレクトリや出力シンボリックリンク/ハードリンクを拒否する。レポート保存先は送信前に確認する。

Nodeのモックは実fetchを禁止し、6件選定・複数カテゴリ・URL重複・長文切断・ID/URL対応・不正JSON・打ち切り・未知モデル・サイズ上限・機密除外・ヘッダー/本文タイムアウト・429・無再送・表示無害化・出力先境界を検証する。Pythonのラッパーで既存CIにも組み込み、Workflowの手動限定・main制限・Secretのステップ範囲・短期artifactを検査する。既存Workflowの変更は不要。

このPRでの確認はオフラインだけ。実ニュースでの生成品質、無料モデルの出力上限、実請求額・残高変化、安定性は未確認。`logs/`・`data/`・`imports/`・Pages・Releases・READMEへの生成結果の自動コミットは行わない。
