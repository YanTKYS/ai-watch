# Gemini 4 Hydrogen 週次レポート PoC（手動・1回だけ）

[Issue #58](https://github.com/YanTKYS/ai-watch/issues/58)。ai-watchの**既存の公式ニュース**から、読む価値のある日本語の週次レポートを `gemini-4-hydrogen` で作れるかを確かめる手動の実験です。API疎通の確認ではなく、**レポートの正確性と情報価値**を人が評価するためのものです。

- 対象は `YanTKYS/ai-watch` です。news-watch（自治体DX記事・PLaMo週刊）ではありません。
- 現在のai-watchに週次レポート生成機能はありません。この実験は公開サイト・日刊収集・Grok/Perplexity/Muse・BeatAPI PoCに触れません。
- 以前のGeminiで503が続いた経験は**news-watch側の実測**です。ai-watch自身でGemini週刊が失敗した事実ではありません。

## 入力（固定の1週間）

| 項目 | 内容 |
| --- | --- |
| 週 | 2026-W45（取得日 2026-11-02〜2026-11-08） |
| 正本 | `logs/2026/2026-11.md`（取得日 `Retrieved` で選択、同一URLは最初の1件） |
| 照合 | `data/search-index.json`（派生データ）の同じ週のURL集合が正本と一致しなければ通信前に停止 |
| 件数 | 21記事（5カテゴリ・6フィード）。上限に合わせて減らさず、上限超過は**削らずに停止** |
| 固定 | `manifest-2026-W45.json` に記事ID・URL・順序・SHA-256を記録。再計算値と違えば通信前に停止 |
| モデルへ渡す情報 | タイトル・カテゴリ・配信元・公開日・取得日・保存済みの `notes`/`highlights`。**記事本文は取得していません** |
| 渡さないもの | 記事URL（出典は検証済みのローカル記録から付与）、Grok/Perplexity/Museの原記録、追加検索 |

21件のうち14件はタイトルとメタデータだけです（抜粋なし）。レポートはその限界を明記する必要があります。公開日（Published）と取得日（Retrieved）は別で、「今週公開」と断定しません。

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
- 出力は、週間概況・主要トピック3〜6件（何が変わったか／影響／根拠／根拠の限界／出典ID）・実務での注目点1〜5件。目安は全体で概ね1,000〜1,800字。**長さや記事数を満たすために内容を削ったり水増ししたりしません**（構造検証の範囲は500〜4,000字）。

### 未検証の前提

このPRの作成環境では公式ドキュメント（`docs.cloud.google.com`、`blog.google`）に接続できず、**次の値は公式仕様で未確認**です。レビュー時に公式の開発者ガイドと照合してください。

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
