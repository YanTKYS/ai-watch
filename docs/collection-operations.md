# 収集の実行・診断とBrave品質観測

現在の操作手順とログの読み方を扱う。[初期設定と基本コマンド](../README.md#セットアップと基本操作)、[情報源・選定設定](source-quality.md)、[通信しない選定検証](selection-dry-run.md)は各資料を参照。過去の取得実績・接続制限は[2026年10月の評価記録](source-quality.md#取得成否の確認と観測限界)として区別する。

## 手動実行と除外記事の再評価

本番の入口はActionsの **Collect AI news**（[collect.yml](../.github/workflows/collect.yml)）。`skip_brave`を選ぶとBraveを呼ばず公式フィードだけを取得する。手動実行でもログ・履歴・状態は更新される。

`reconsider_excluded`は、選定ルール変更後に**フィードに残る公開7日以内の除外記事**を現在の設定で再評価するオプション。通常実行ではseenの除外は復活しない。採用済み・集約済みの記事を再選定・訂正する操作ではなく、過去ログ全体も再取得しない。まず[dry-runの比較](selection-dry-run.md)を確認する。

ローカルの対応オプションは`--skip-brave`・`--reconsider-excluded`。`--dry-run`を付けない収集は実フィードへ接続し、`logs/`・`data/`へ書き込む。

## Actionsの確認順序

1. **Collect**: 公式フィード別の取得・解析、記事の選定、Braveの利用/品質集計を確認する。
2. **Update search index**: 保存済みMarkdownからの検索生成を確認する。収集と別段階で、生成失敗でも日刊のcommit処理は継続する。
3. **Record collection and index status**: 収集と検索生成の実際の成否を公開状態へ対応付ける。
4. **Commit and push if there are changes**: `logs/`・seen・months・Brave利用記録・検索インデックス・収集状態の保存を確認する。キャンセル以外は収集失敗時もこの処理を試みるが、commit/push成功まで保証するものではない。
5. **Pages配信**: 公開元のcommitがサイトに反映されたかを別に確認する。

一部フィードが失敗しても残りを処理するので、Actions成功だけで全フィード成功と判断しない。全フィード失敗は非0終了。状態の項目・36時間超の遅延判定・配信方式の注意は[収集状況と鮮度](collection-health.md)へ。新着がなくても収集状態は保存される。

## 公式フィードの診断

成功時は次の形式で、取得・解析したエントリ数が出る。`entries`は採用記事数ではない。

```text
feed ok: ... status=200 content_type=... bytes=... decoded_bytes=... entries=N
```

失敗時は`feed failed`に続く`diagnostics:`を見る。

| 記録 | 確認すること |
| --- | --- |
| `status` / `content_type` / `final_url` | HTTPエラー、XML以外の応答、転送先。到達制限は配信元の障害と区別する |
| `content_encoding` / `bytes` / `decoded_bytes` | gzipの受信サイズと展開後サイズ。未取得・未展開は`-`の場合がある |
| `start` / `first_element` / `leading_whitespace` / `bom` | XML宣言・HTML等の形式、先頭要素、空白・BOMの有無 |
| `parse_error` / `context` | XML解析失敗位置とその前後30文字。本文全体は出さない |

`Content-Encoding: gzip`は展開後に解析する。上限は受信10,000,000バイト、展開後30,000,000バイト。サイズ超過・壊れたgzip・不正XMLは取得/解析失敗として扱う。DOCTYPE・ENTITYを含むXMLは拒否する。1フィード1リクエストで、ページング・自動リトライはしない（実装: [feeds.py](../scripts/feeds.py)）。

取得成功でも記事がない場合は、公開日・既読・タイトル必須語・除外規則を確認し、その後に`selection:`、`adopted` / `rejected`、理由別の`rejected by selection`を見る。点数・分類と履歴の説明は[記事選定](source-quality.md#現在の記事選定)・[判定出力](selection-dry-run.md#出力の読み方)へ。

URLが違う同一話題は自動で統合しない。タイトルが同じ記事の件数をActionsログに出して観測する段階で、話題重複が解消された意味ではない。

### 通信なしの検証と実取得の違い

`python -m unittest discover -s tests`は合成フィクスチャによる回帰確認。`tests/fixtures/`にはRSS 2.0・WordPress・GitHub Releases Atom等を模した入力がある。解析テスト成功は実サイトの到達性を保証しない。選定ルールの[dry-run](selection-dry-run.md)も通信・書き込みをしない。

実取得を調べる際は、既存のActions実行ログから確認する。新たな実行が必要なら`skip_brave`でBraveの消費を避けられるが、公式フィードへの通信とデータ更新は発生する。ブラウザ操作の回帰は別の[Chromium E2E](browser-tests.md)が担当する。

## Braveの利用制御と保存制約

Braveは記事の収集経路ではなく、検索の取得品質を観測する処理。[Brave Search API利用規約](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service)を根拠に、ストレージ権のないプランで検索結果を保存・キャッシュ・データベース化しない方針を取る。検索結果は実行中のメモリ上でのみ集計し、URL・タイトル・説明文を`logs/`、seen、検索インデックス、Actionsログへ出さない。検索結果を保存する方式へ変える場合は、実際のプランの保存権限と各サービスの条件を別途確認する。

このBrave観測ではX APIやXページ本文を取得せず、X投稿本文の保存・再公開もしない。別途試験保存された`imports/x/`を同じ取得経路とみなさない。Grok/Xの本文確認・利用条件・運用境界は[Grok評価](grok-x-evaluation-2026-10.md)を参照。

- `BRAVE_API_KEY`は任意。未設定や`skip_brave`の場合、公式収集を続けてBraveだけをスキップする。
- JST日付ごとに最大4リクエスト（[brave.py](../scripts/brave.py)の`MAX_DAILY_REQUESTS`）。`brave.daily_limit`で下げられるが増やせない。現在はX系2・Web系2の4検索語。検索語数が設定上限を超えると、APIを呼ばず設定エラーにする。
- 同日の利用記録が1件以上あれば、手動再実行も含め追加呼び出しをしない。途中で失敗しても当日の残り枠を再開・補充しない。
- 利用件数を各リクエストの**直前**に`data/brave-usage.json`へ書く。したがって失敗した要求も消費数に含む。既存記録が読めない・壊れている場合は呼び出さない。ファイル未作成は空履歴として扱うため、利用記録を消して回数をリセットしない。
- 1検索語1リクエスト、`count=20`。ページング・自動リトライはない。記録は直近90日を基準に古い日付を削除する。
- 日次消費は利用記録の`requests`、月次消費はその月の値の合計で確認する。設定と記録を保って毎日最大4回なら31日で124回が上限だが、固定使用量や他リポジトリ・アカウント全体の使用量ではない。月次の独立した上限制御は実装していない。

### 品質メトリクスの読み方

Actionsの`Brave ...`行と`data/brave-usage.json`に検索語ごとの集計が残る。実装は[brave.pyのevaluate](../scripts/brave.py)。

| 項目 | 意味・限界 |
| --- | --- |
| `results` | URLを正規化できた検索結果の件数 |
| `x_posts` / `x_profiles` / `x_other` / `non_x` | 投稿形式URL / プロフィール / その他のXページ / X以外。投稿本文の実在・内容を確認した件数ではない |
| `x_authors` | 投稿形式URLから取り出した投稿者ハンドルの種類数。本人性・人気・フォロワー数は検証しない |
| `dated` / `recent` | 検索結果の`page_age`を日付として読めた件数 / 評価日から0〜7日前。公式発表日時やX投稿日時の検証ではない |
| `on_topic` / `evidence` / `hype` | タイトル・説明文にカテゴリ語 / 根拠語や版番号 / 誇張語がある件数。事実の裏付けや人手の品質評価とは別 |
| `candidates` | 話題一致・誇張語なし・0〜7日前・X系は投稿形式URL、という条件を満たす件数。保存も採用もしない。根拠語の存在は必須条件ではない |
| `duplicates` / `official_overlap` | 同じ実行の検索語間でURL既出 / seenの既知URLと完全一致。後者は除外・集約履歴も含み、話題単位の重複ではない |

`candidates`から重複件数を自動で差し引いてはいない。集計から有用な新規ニュース数・早期発見数・既存収集の網羅率を推定しない。結果URLを残さないため、後から個別の検索結果を復元することもできない。

最後に直近7日間の`x_post_rate`等の集計を表示する。精度を調整するときは`brave.queries`の検索語・`freshness`と`quality`の語を見直す（[設定の入口](source-quality.md#設定の入口)）。実APIでの再実行は消費を伴うため、通常のドキュメント・テスト確認には使わない。

## 独立した外部検索の検証

PLaMoの手動評価ワークフローは存在するが、2026年10月の[評価結果](plamo-evaluation-2026-10.md)で本番採用見送り・追加検証は一時終了。再開判断や費用・保存条件は[専用手順](plamo-probe.md)へ。Grokは[既存13件の評価と運用設計](grok-x-evaluation-2026-10.md)へ。本書の通常収集手順からこれらを起動しない。
