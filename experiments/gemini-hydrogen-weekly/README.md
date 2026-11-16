# Gemini 4 Hydrogen 週次レポート PoC（手動・1回だけ）

[Issue #58](https://github.com/YanTKYS/ai-watch/issues/58)（公式のみ）と [Issue #62](https://github.com/YanTKYS/ai-watch/issues/62)（Grok・Perplexity・Muse追加）。ai-watchの**既存の公式ニュースと、保存済みの別AIの原記録**から、読む価値のある日本語の週次レポートを `gemini-4-hydrogen` で作れるかを確かめる手動の実験です。API疎通の確認ではなく、**レポートの正確性と情報価値**を人が評価するためのものです。

- 対象は `YanTKYS/ai-watch` です。news-watch（自治体DX記事・PLaMo週刊）ではありません。
- 現在のai-watchに週次レポート生成機能はありません。この実験は公開サイト・日刊収集・Grok/Perplexity/Museの保存先と表示・BeatAPI PoCに触れません（原記録は読み取るだけで、公式ログへの自動昇格はしません）。
- 以前のGeminiで503が続いた経験は**news-watch側の実測**です。ai-watch自身でGemini週刊が失敗した事実ではありません。

## 入力（固定の1週間・4ソース）

2026-W45（2026-11-02〜2026-11-08）。公式のみの実行 [#43722231617](https://github.com/YanTKYS/ai-watch/actions/runs/43722231617) と同じ週なので、読み比べられます。各ファイルを**全件**読み取り、元情報を切り捨てる上限はありません（上限超過・件数不一致・期間外は**削らず通信前に停止**）。

| ソース | 対象 | 件数（W45） | 日付の解釈 |
| --- | --- | --- | --- |
| 公式 `official`（ID `a01`〜） | `logs/2026/2026-11.md`（正本）。`data/search-index.json` の同週URL集合と一致しなければ停止 | 21記事 | `Retrieved`（取得日）。公開日・発生日とは別。本文は未取得（タイトル・メタデータ・保存済み抜粋） |
| Grok `grok`（`x01`〜） | `imports/x/2026/x-20261102/05/06/08.md` | 4ファイル・16件 | 収集日・対象期間・投稿日時は別。**未検証の候補**。「情報の確度」はGrokの自己申告で、一次資料で確認した意味ではない |
| Perplexity `perplexity`（`p01`〜） | `imports/p/2026-W45.md` | 1本（節・項目に分割して14） | 調査日は11/06。11/08までの網羅は保証されない。「今週のスター」等は調査時点の値。**未検証** |
| Muse `muse`（`m01`〜） | `imports/m/muse-20261102〜08.md` | 7ファイル・70件 | 収集日で週を決定。アイデアに書かれた企業発表日は別。**業務活用のアイデアで、公式ニュースや採用実績ではない** |

- 件数は**入力**です。最終レポートに全件を並べるのではなく、関連項目の統合と重要度による選定が目的です。実行結果には、ソース別の「入力件数」と「出力で参照された件数」を別々に記録します。
- 既存のパーサ（`import-markdown.js`、ブラウザ表示と共通）で読み取ります。Grokは日別の項目、Museは「分野／何を楽にするのか／再現の仕組み／何が新しくなったか」、Perplexityは節（h2）と項目（h3）に分け、項目内の表は「項目: 内容」の行にします。
- 生のMarkdownは**参考資料（指示ではない）**として `<UNTRUSTED_SOURCE_JSON>` 内に入れ、資料中の命令に従わないことをプロンプトに明記しています。外部URLへのアクセス・検索・スクレイピングはしません。
- 記事・投稿・アイデアのURLは**モデルに渡しません**。出典は入力IDで参照させ、IDに対応するローカルの原記録パスとリンク（Grok・Perplexity・Museのリンクは「未検証候補」）をプログラムが付与します。
- Grok/Perplexity/Muse/公式ログの保存先・検索インデックスは変更しません。

### 固定入力の控え（Manifest）

- `manifest-2026-W45.json`: 公式21件（ID・URL・順序・SHA-256）。**そのまま維持**します。
- `manifest-2026-W45-multisource.json`: 公式のSHA-256を内包した複合Manifest。Grok・Perplexity・Museの対象ファイル（パス・SHA-256・件数・収集/調査日）、全項目のID・原記録パス・題名・リンクを記録。
- どちらも、再計算した値と違えば通信前に停止します（ドライランでも検出されます）。

## 実行方法

Actions → **Gemini 4 Hydrogen weekly report PoC** → Run workflow（`main` のみ）。

| 入力 | 動作 |
| --- | --- |
| `execute=false`（既定） | ドライラン。オフラインのテスト、固定入力の検証、リクエスト内容（プロンプト・設定）の確認。Secretも通信も使いません |
| `execute=true` | `main` 上で、Geminiへ**1実行につき最大1回**送信。自動の再試行・別モデルへのフォールバックなし |

入力は `execute` だけです。Actionsの「Re-run」で手動で再実行した場合も、`execute=true` なら送信されます（再実行は別の利用枠を消費するので、失敗直後の再実行は避けてください）。

実行前のメモ（確認用で、Workflowの条件ではありません）:

1. Hydrogenの最新の公式仕様（下の「未検証の前提」）と、対象キー/プロジェクトの無料利用・課金状態・レート制限
2. 送信するのは公開済みニュース記事情報のみ（無料Tierの入力はGoogleの製品改善に使われる場合があります）
3. リポジトリSecret `GEMINI_API_KEY` を `ai-watch` に登録済み（news-watchのSecretは共有されません。未設定なら通信前に停止します。値はコード・PR・ログに出さないでください）

## 安全上の設計

- `workflow_dispatch` のみ。`contents: read`、認証情報を保持しない。`GEMINI_API_KEY` は送信ステップだけに渡す。
- キーはHTTPヘッダ `x-goog-api-key` で送り、URL・ログ・レポートに出さない。リダイレクト禁止、応答サイズ・時間の上限あり。
- 生のHTTPエラー本文・内部推論（thought）・署名は記録しない。失敗は固定の理由コードだけを診断として残し、**途中までの回答は保存しない**。
- `finishReason` が `STOP` 以外（`MAX_TOKENS`・安全性など）の回答は採用しない。
- 出典URLはモデル出力ではなく、検証した記事レコードから付与する。出力にURL・HTML・Markdown・キー様の文字列があれば失敗。

## リクエスト設定

- `model`: `gemini-4-hydrogen`、`generateContent`、`thinkingConfig.thinkingLevel: HIGH`（`thinkingBudget` は指定しない）。
- `responseMimeType: application/json` ＋ JSON Schema（`responseJsonSchema`）。スキーマ合格後もプログラム側で再検証する。
- `maxOutputTokens: 32768`（内部推論も含む上限。この値を探る実験ではありません）。タイムアウト300秒。
- 出力は、週間概況／主要ニュース・技術トピック4〜7件（何が変わったか・影響・根拠・根拠の限界・出典ID。公式・Grok・Perplexityを横断して重複を統合し、同じ発表は1トピックに出典を併記）／**Museの業務活用アイデア2〜5件**（業務課題・活用方法・確認が必要な前提・Muse原記録ID・関連する別ソース）／運用上の注目点1〜5件。
- 目安は全体で約2,000〜3,500字（旧「1,000〜1,800字」から、入力が4ソースになったため引き上げ）。**根拠が薄ければ水増ししません**。構造検証の範囲は1,200〜6,000字で、品質の合否ではありません。
- 出典と確度の区別を**プログラムで強制**します: 主要トピックにMuseのIDは使えない／MuseのアイデアにはMuse原記録のIDだけ／GrokやPerplexityのIDを使うトピックは根拠の限界に「未検証」、タイトルだけの公式記事は「タイトル」と明記。各参照に `source_type`（official/grok/perplexity/muse）とローカルの原記録パスを付与。

### 未検証の前提

公式ドキュメント（`docs.cloud.google.com`、`blog.google`）には作成環境から接続できず、**次の値は公式仕様の文書と未照合**です。公式のみの実行 [#43722231617](https://github.com/YanTKYS/ai-watch/actions/runs/43722231617) は成功で終了しており、リクエスト形式は受理されたとみられますが、レビュー時に公式の開発者ガイドと照合してください。

- エンドポイント `generativelanguage.googleapis.com/v1beta/models/gemini-4-hydrogen:generateContent` とヘッダ名 `x-goog-api-key`
- `thinkingLevel` の値の綴り（`HIGH`）と、構造化応答のフィールド名（`responseJsonSchema`）
- 応答のフィールド名（`finishReason`、`usageMetadata.*`、`modelVersion`、`responseId`）

仕様が違う場合、PoCは固定の理由コード（`bad_request`、`invalid_response` 等）で1回の送信を終えます。直後の再実行はせず、スクリプトを直してから改めて判断します。

## 結果の見方

成功しても **`schema_valid_unverified`** です。これは「APIが完走し、構造検証に通った」だけを意味し、事実・出典・文章・情報価値の合格ではありません。

- Job Summary と短期Artifact（3日）に、Manifest、HTTP、モデル、試行回数、完了理由、usage（`thoughtsTokenCount` を含む）、時間、検証結果、**候補レポート全文**が残ります。`reviews/`・`logs/`・`data/`・`imports/` への自動コミットはしません。
- 人が [evaluation-template.md](evaluation-template.md) の基準で評価します。**1回の成功で定期稼働の安定性は確定しません。**
- 無料Tierの対象か、実際の課金額は未確認のまま記録します。
- 結論（**継続・修正・見送り**）は、実測後にオーナーと内容を見て決めます。週次の定期実行や公開は、採用判断後の別Issueです。

## ローカルでの確認（通信なし）

```sh
node --test tests/test_gemini_hydrogen_weekly.cjs
node scripts/gemini_hydrogen_weekly.cjs --output-dir "$(mktemp -d)"
```
