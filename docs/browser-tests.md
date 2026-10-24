# Chromium E2E（F13 第1段階）

Python/Nodeの高速な回帰と品質チェックに加え、実際のHTML・JavaScriptをChromiumで操作する4ケースをPR CIで実行する。テストはローカルHTTP配信だけを利用し、公開Pages・公式フィード・外部APIには接続しない。

## セットアップと実行

必要な環境はNode.js 22以上（CIは22）、npm、Python 3（CIは3.12）。製品のPython依存とは別に、`@playwright/test` **1.64.1**を `devDependencies` と `package-lock.json` で固定する。ChromiumのリビジョンもこのPlaywright版に対応するものを使用する。

リポジトリのルートで実行する。

```sh
npm ci
npx playwright install chromium
npm run test:e2e
```

初回セットアップのパッケージ・ブラウザ取得にはネットワークが必要。LinuxでOSライブラリも必要な場合は `npx playwright install --with-deps chromium` を使う（OSパッケージの導入権限が必要）。CIではUbuntu 24.04にこの方法でChromiumと必要なライブラリだけを導入し、Firefox/WebKitは導入しない。

Playwrightが `python3 -m http.server 4173 --bind 127.0.0.1` を起動し、終了時に停止する。ポート4173を空けて実行する。既存サーバーの再利用は無効で、他のチェックアウトの画面を誤って検証しない。Pythonの収集処理やPyYAMLはE2Eジョブで実行・導入しない。

配布元に接続できないローカル環境では、次のように既存のChromiumを指定できる。これはバージョンが異なる代替確認であり、CIでの対応版確認とは区別する。通常は指定しない。

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:e2e
```

## 4ケースの担当範囲

| ケース | 幅 | 主な確認 |
| --- | --- | --- |
| 日刊・キーボード | 1280px | 実sample、最初のTabでスキップリンク、Enterで本文、h2→h3→h4→h5、日付のEnter/Space開閉、月/並び順とフォーカス維持、本番状態を取得しないこと |
| 検索・追加表示 | 320px | sampleの検索応答だけ120件の合成記事に差し替え、0件、50→100→120、h2→h3、通知、最後の追加見出しへのフォーカス、次のTab、クリアで日刊・入力欄へ復帰 |
| エラー・再試行 | 375px | sampleログの初回503、再試行待機中のボタン維持と連打防止、再失敗時のフォーカス、実sampleへの復帰と月見出しへの移動 |
| 収集状態の独立性 | 1280px | 本番モードのデータ要求を既存sampleへ差し替え。正常0件/一部失敗/404/破損JSONの各状態でも記事・検索を使え、記事操作の通知と混ざらないこと |

同じブラウザで幅を代表的に使い分け、全ケース×全幅のマトリクスにはしない。記事/状態の差し替えはブラウザのルート処理だけで、`logs/`・`data/`・`samples/` を書き換えない。外部originへのリクエストを遮断し、試行自体もテスト失敗にする。未処理のページ例外も失敗にする。

固定秒数のsleepで結果を待たず、DOM・通知・フォーカスをPlaywrightの再試行付きアサーションで待つ。再試行テストでは応答を保持して待機中を確認し、明示的に応答を返す。各ケースの上限30秒、並列workerは1、テストの自動再実行は0回。ローカルとCIの実測所要時間は対応PRに記録する。

## CIと失敗調査

`.github/workflows/test.yml` の独立した `e2e` ジョブで実行する。既存の `test` ジョブ（unittest・Node回帰・固定品質チェック3セット）は維持する。どちらもPR/メインへのpushで動き、E2EへSecretsを渡さず、収集ワークフローも呼ばない。

失敗したテストだけ `test-results/` に `trace.zip`・失敗時のスクリーンショット等を残す。CIでは `chromium-e2e-failure-<実行試行番号>` artifactを7日間保存する。成功時はトレース/画面を保持せず、artifactもアップロードしない。インストール等でテスト開始前に失敗した場合はテストのトレースがないため、Actionsのステップログを確認する。

Actionsの失敗runのArtifactsからZIPをダウンロードし、`test-results/` へ展開する（ZIP内はケース名のディレクトリ）。次のように対応ケースのトレースを開く。

```sh
npx playwright show-trace test-results/<ケースのディレクトリ>/trace.zip
```

ローカルの失敗ログにも実際のファイルパスが出る。`node_modules/`・`test-results/`・`playwright-report/` はGit管理対象外。トレースにはテスト用のローカル通信と合成/sampleデータを用い、本番APIの結果は入れない。

## 今後の追加と境界

新しい閲覧機能は `tests/e2e/pages.spec.cjs` に代表操作を少数追加する。非同期応答の大量の順序、分類・採否、データの細かな異常値は既存Python/Nodeテストへ残す。F01/F02の実装後はフィルターやURL復元/履歴の代表ケースを足す。

実スクリーンリーダーの音声・実OSの日本語IMEはF25、公開Pagesの配信版確認はF24、性能測定はF14の対象。今回の4ケースやChromiumのみの成功で、これらも検証済みとは扱わない。
