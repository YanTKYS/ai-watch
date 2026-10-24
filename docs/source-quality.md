# 情報源の品質評価と収集範囲

評価日: 2026-10-24（JST）。対象: `3389ed5` 時点の設定と2026-10-18〜24の取得記事。Issue [#6](https://github.com/YanTKYS/ai-watch/issues/6)、改善案F12に対応する。目的は「技術的に有益で、実際に読みたい更新」を残すための判断材料を用意すること。

**運用更新**: F17第1段階でリリース分類、第2段階でニュース選定を改善した。現在のGitHub Changelogは必須語通過後にscore方式を使う。以下の代表記事の評価・保存件数は過去の記録であり、再選定していない。[現在の比較結果](selection-dry-run.md) と [現行設定＋保存実績の生成一覧](source-inventory.md) を参照。情報源は7件のまま。

**結論**: 現行7フィードを維持し、先に選定の評価を改善する。導入事例の混入だけでなく、修正のみのリリースや内部変更を重要な更新として扱う例もある。情報源追加はGemini公式SDKを第一候補とするが、この変更では追加せず、F11のdry-runでノイズと重複を評価してから判断する。

## 一覧と更新方法

[生成された情報源一覧](source-inventory.md) に、現行設定のURL・カテゴリ・選定方法・保存記事数・集約数・除外URL数をまとめた。数値を本書で二重管理せず、次で更新する。

```sh
python scripts/source_report.py --since 2026-10-18 --until 2026-10-24 > /tmp/source-inventory.md
# 成功後に内容を確認し、資料の期間・定性評価も見直してから反映
cp /tmp/source-inventory.md docs/source-inventory.md
```

仮想環境では `.venv/bin/python` を使う。コマンド自身は標準出力のみで通信せず、収集・Brave呼び出し・ログの再生成はしない。設定を変更すると一覧の行と選定方式も追従する。古い期間の実績を現行設定と比較する用途であり、過去時点の設定を復元する機能ではない。

集計は検索インデックスを入力にせず、正本のMarkdownログを既存のパーサーで読む。保存済み29記事は集約後のカード数で、個々のリリース数や採否候補数とは異なる。除外のFeed情報はseenにないため、同一ホスト／GitHubリポジトリからの**推定**を明示し、曖昧なURLは未帰属にする。年齢・必須語・重複などで候補になる前に落ちた件数は復元できない。採用率・取得成功率の分母として使わない。

## 現行7フィードの役割と品質

すべて提供元の公式サイト、または提供元が管理するGitHubリポジトリ。公式であることと、個人の開発に有用であることは別に評価する。設定のカテゴリは既定値で、`classify: false` 以外はタイトルによって再分類される。

| 情報源 | 対象製品・役割／公式性の根拠 | 採用・除外の傾向と有用性 | 判断 |
| --- | --- | --- | --- |
| OpenAI News | OpenAI公式ニュース。GPT・ChatGPT・API・エージェントの発表を広く拾う | `score`。seenにはcustomer_storyやlow_score等の除外があるが、Terminal Xや生物学への活用例は採用された。Decisions APIのような直接的な開発者向け更新は有用。ニュース全体の点数閾値だけを上げると技術情報も落とす | 維持。事例と新API・モデル発表を分ける評価を優先 |
| Google DeepMind News | DeepMind公式ブログ。Gemini・研究・モデル発表 | `score`。Gemini 4 Argonの新モデル・ロボティクス更新を採用、研究応用等をlow_scoreで除外。研究ブログであり、Gemini APIのSDK変更や料金改定の網羅的な通知元ではない | 維持。Gemini開発者向けの不足は別候補で補う |
| GitHub Changelog | GitHub公式変更履歴。Copilot・モデル廃止・API・開発支援 | タイトル必須語の後は `all`。モデル廃止・policy APIは有用だが、impact dashboardの業界比較も採用。seenの除外0は全候補が有用という意味ではない（必須語で除いた記事は記録されない） | 維持。利用者に影響する更新と管理・効果測定を区別 |
| Claude Code Releases | `anthropics/claude-code`。CLI・IDE・実行環境の公式リリース | `release_notes`。複数リリースを集約。v2.1.306はfixes_onlyで除外する一方、v2.1.303の「Bug fixes and reliability improvements」は変更として採用。重要な設定変更がある日と、抽象的な修正説明だけの日が混在 | 維持。曖昧な修正文とbreaking判定の精度を検証 |
| OpenAI Codex Releases | `openai/codex`。Codex CLIの公式リリース | `release_notes`、プレリリース除外。0.164.0のプリセット・設定操作などは直接使える情報。CLIリリースはChatGPT内のCodex等の全更新を網羅しない | 維持。CLIの役割を明示し、関連サービス全体と混同しない |
| MCP Specification Releases | `modelcontextprotocol/modelcontextprotocol`。MCP仕様の公式リリース | `release_notes`、期間内の保存0。仕様更新は低頻度で、SDKや各MCPサーバーの更新は対象外。0件だけで価値や取得成否を判断できない | 維持。仕様改定の見逃し防止を件数より優先 |
| Anthropic SDK Releases | `anthropics/anthropic-sdk-python`。Claude APIのPython SDK | `release_notes`、プレリリース除外。APIバージョン対応や引数追加は有用。一方、Enterprise管理API、CI削除やサンプル修正が目立つ日もある。MCPカテゴリ固定だが実際にはClaude API一般も含む | 維持。カテゴリ名とAPI/SDKの役割の違いを説明。内部変更の強調を改善 |

## 取得成否の確認と観測限界

### Actionsの実績

GitHub APIで取得できた次の6実行は、いずれもジョブと `Collect` / `Update search index` ステップがsuccessだった。時刻は実行開始のJST表記で、設定上の予定時刻（6:41）とは区別する。

| 実行開始（JST） | Run | Collect / index |
| --- | --- | --- |
| 2026-10-19 08:35 | [39177192121](https://github.com/YanTKYS/ai-watch/actions/runs/39177192121) | success / success |
| 2026-10-20 09:36 | [39348647068](https://github.com/YanTKYS/ai-watch/actions/runs/39348647068) | success / success |
| 2026-10-21 09:05 | [39519204707](https://github.com/YanTKYS/ai-watch/actions/runs/39519204707) | success / success |
| 2026-10-22 09:09 | [39697936617](https://github.com/YanTKYS/ai-watch/actions/runs/39697936617) | success / success |
| 2026-10-23 09:07 | [39876208553](https://github.com/YanTKYS/ai-watch/actions/runs/39876208553) | success / success |
| 2026-10-24 08:58 | [40042548586](https://github.com/YanTKYS/ai-watch/actions/runs/40042548586) | success / success |

`gh run view … --log` のログ配信先 `results-receiver.actions.githubusercontent.com` はこの環境からForbiddenだった。詳細ログにあるfeed ok/failed、選定スコア内訳、必須語によるスキップ等は未確認。収集処理は部分失敗でも続行するため、**Actions成功を7フィード全件成功と読み替えない**。10/18の保存記事も存在するが、上の6実行だけで初期収集を説明できるとは限らない。

詳細を再確認する際はActionsのRunから `Collect` を開くか、到達できる環境で以下を実行する。フィード別の `feed ok:` / `feed failed:` と `selection:`、`adopted` / `rejected` を確認し、本文・秘密値・Braveの検索結果は資料へ転記しない。本文ログはこのPRに保存しない。

```sh
gh run view 40042548586 --repo YanTKYS/ai-watch --log
```

### 実フィードの読み取り確認（2026-10-24）

既存の `feeds.fetch()` → gzip展開 → `parse_feed()` を使い、設定URLへ読み取りのみ実行した。収集・保存・API枠消費は行っていない。

| フィード | 今回の確認結果 | 解釈 |
| --- | --- | --- |
| OpenAI News / Google DeepMind News / GitHub Changelog | プロキシのCONNECTが403 Forbidden | サイトの障害・不正形式とは判断できない。クラウドの許可先を確認して再検証が必要 |
| Claude Code Releases / OpenAI Codex Releases / Anthropic SDK Releases | HTTP 200、Atom解析成功、各10エントリ | この時点の到達性・解析は確認。過去の毎回の成功を示さない |
| MCP Specification Releases | HTTP 200、Atom解析成功、9エントリ | 期間内保存0でも今回の取得は成功 |

## 代表記事の評価

判断基準は「開発で何を試す・変える・避けるかが分かるか」。公式タイトルと保存済み抜粋による評価で、記事本文全体の精読や有用率の統計評価ではない。分類器の実行時スコアは詳細Actionsログ未取得のため断定しない。

| 記事・取得日 | 判断 | 根拠と次の評価観点 |
| --- | --- | --- |
| [Build more responsive apps with the Decisions API](https://openai.com/index/decisions-api)・10/23 | 残したい | 新APIの利用判断に直結。事例除外を強くしても落とさない正例にする |
| [Gemini 4 Argon: Built to solve your hardest problems](https://deepmind.google/blog/introducing-gemini-4-argon)・10/18 | 残したい | 新モデル発表。一般的な活用紹介との違いを保つ |
| [GitHub Copilot models deprecated on October 19, 2026](https://github.blog/changelog/2026-10-19-github-copilot-models-deprecated-on-october-19-2026)・10/20 | 残したい | 利用中モデルの切替に必要。料金・廃止情報の正例 |
| [Codex 0.164.0](https://github.com/openai/codex/releases/tag/rust-v0.164.0)・10/24 | 残したい | プリセット保存・inline設定など具体的な利用機能が抜粋から分かる |
| [Claude Code v2.1.305](https://github.com/anthropics/claude-code/releases/tag/v2.1.305)・10/21 | 残したい | sandbox設定や待機再確認のパラメータ変更。実環境への影響がある |
| [Terminal X matches senior investor judgment 88.6% with GPT-6.1](https://openai.com/index/terminal-x)・10/22 | 関心が薄い候補 | 特定企業・投資分野の活用成果が中心に見える。新モデルやAPI変更と同列に扱わず、再現可能な技術説明があるかを別途確認 |
| [Using thousands of AI agents to uncover new leads in biological data](https://openai.com/index/scaling-ai-research-for-complex-biological-data)・10/22 | 関心が薄い候補 | 生物学への応用。agentという語だけで開発者向けと判断しない。汎用的な実装・評価手順があれば採用の余地を残す |
| [Industry comparisons in the Copilot impact dashboard](https://github.blog/changelog/2026-10-22-industry-comparisons-in-the-copilot-impact-dashboard)・10/23 | 関心が薄い候補 | 効果測定・組織管理寄り。Copilot必須語を通過しても開発機能の更新とは限らない |
| [Claude Code v2.1.303](https://github.com/anthropics/claude-code/releases/tag/v2.1.303)・10/19 | 関心が薄い | 抜粋は「Bug fixes and reliability improvements」のみ。`improvements`を含む修正文が変更扱いになる例としてF11に渡す |
| [Anthropic Python SDK v2.3.0](https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.3.0)・10/24 | 一部だけ残したい | Enterprise API追加は利用者次第。抜粋のCI削除・サンプルのawait修正を破壊的変更として強調するのは読者の影響とずれる。`remove`だけで分類せず文脈を検証 |

不採用側にも確認候補がある。seenの `openai-models-google-cloud` と `low-resource-programming-languages` はlow_scoreで除外されているが、提供先拡大やコーディング支援の知見があるなら重要になり得る。保存されていない説明文・本文を推測して採用に変えず、F11で再評価する候補とする。`policy_society` の `EU` / `Europe` 等も、安全規制・提供地域の重要な変更を過度に減点しないか検証する。

## 追えている範囲と不足領域

| テーマ | 現在の入口 | 不足・注意点 |
| --- | --- | --- |
| AIモデル | OpenAI News / DeepMind、Copilot内のモデル変更 | 他社・オープンウェイトモデルの一次発表を直接追っていない。設定のQwen/DeepSeek/Llama等のキーワードは情報源の存在を保証しない |
| AIコーディング | Claude Code / Codex CLI / Copilot | Cursor、他IDE、Webサービス側の更新は部分的・未対象 |
| エージェント | OpenAIニュース、Claude Code・SDK、GitHub変更履歴 | 各社のAgents SDKや専用フレームワークを網羅しない。分野別の活用事例も混ざる |
| MCP | 仕様リリース、Anthropic SDKの関連変更 | MCP SDK・個別サーバー・コネクターの新機能は未網羅。Python SDK全体をMCP専用とは見なさない |
| API料金・制限 | OpenAIニュース、Copilotモデル廃止、Anthropic SDK | Google Gemini API、各社の価格表・レート上限の静かな変更や実際の提供状況は保証しない |

Braveは品質集計のみで、これらの不足を記事として埋める経路ではない。公開から7日以内・フィードに残る範囲が対象なので、低頻度実行や長期停止で取りこぼす可能性もある。

## 追加・入れ替え候補の調査

新規の情報源はまだ設定へ追加しない。上限10件も据え置く。取得確認は既存のパーサーで行い、記事・本文を保存していない。

| 候補と公式性 | 形式・到達性 | 技術密度・重複 | 利用条件の確認範囲 | 判断 |
| --- | --- | --- | --- | --- |
| [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) の [Releases Atom](https://github.com/googleapis/python-genai/releases.atom)。Google管理組織のSDKでREADMEもGemini Developer API等の利用を説明 | HTTP 200 / Atom、10エントリを解析。v2.33.0（10/23）は機械分類で新機能5・変更1・修正3、v2.32.0（10/21）は新機能4・変更1・修正3等 | Gemini APIの不足を補う。DeepMindのモデル発表とは役割が異なるが、モデル対応追加のニュースは重複し得る。全10件の精読評価は未実施 | [LICENSE](https://github.com/googleapis/python-genai/blob/main/LICENSE)はApache-2.0。再配布時のライセンス・通知等の条件を確認。ただしリンク先全体への適用は未確認のため、当面はタイトル・URL・日付を基本とする | **追加の第一候補**。F11で候補記事・ノイズを比較し、`release_notes`とプレリリース除外を検討 |
| [Anthropic TypeScript SDK](https://github.com/anthropics/anthropic-sdk-typescript) の [Releases Atom](https://github.com/anthropics/anthropic-sdk-typescript/releases.atom)。Anthropic公式SDK | HTTP 200 / Atom、10エントリを解析。`vertex-sdk-v1.1.0`、`sdk-v1.3.0`等、複数のタグ体系を確認 | TypeScript固有の型・runtime変更は有用だがClaude API更新はPython版と重複しやすい。タグごとの対象選別も必要 | [LICENSE](https://github.com/anthropics/anthropic-sdk-typescript/blob/main/LICENSE)はApache-2.0。同様に再配布時の通知等が条件。リリース文への適用範囲は採用前に確認し、全文転載は提案しない | **保留**。利用言語の需要と固有差分が確認できれば追加よりPython版との入れ替えを検討 |
| [Cursor公式Changelog](https://cursor.com/changelog) | `/changelog/rss.xml` を候補として確認したがプロキシCONNECTが403。公式RSS/Atomの提供有無・形式は未確認 | AIコーディングの不足を補う可能性。実データが取れないため密度・重複も未評価 | 利用条件・機械取得可否は未確認。HTMLの無断収集を前提にしない | **調査保留**。URLの存在を断定せず、公式の配信案内と条件を確認してから判断 |

GitHub配信には [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service) が関係する。[公式文書のソース](https://github.com/github/docs/blob/main/content/site-policy/github-terms/github-terms-of-service.md)のD.3/D.5（権利と公開リポジトリの閲覧・fork）とH（API利用）を確認した。公開による閲覧許可と、外部への任意の再配布許可は同一と扱わない。SDK両方のLICENSE第4項には再配布時のライセンス交付、変更表示、関連する権利表示・NOTICEの保持等の条件がある。公開フィードやOSSライセンスの存在だけで全文保存・翻訳の再配布が可能とは判断せず、リリース文・抜粋への適用範囲は採用前に確認する。

## 優先順位と次工程F11への入力

1. **最優先: 既存選定の評価セットを作る**。上の正例・関心の薄い例をF11の期待値にする。保存済みデータから評価対象を選び、事例の機械的な一律除外や閾値引き上げで新API・モデル・技術記事を失わないよう比較する。
2. **修正文・内部変更の誤分類を検証**。Claude Codeの「Bug fixes and reliability improvements」、SDKの「internal: remove …」「mcp: remove … examples」を負例候補にする。文字列分類器だけで利用者影響を断定しない。
3. **GitHub Changelogのノイズを分ける**。Copilot・AIという必須語だけでは足りない。廃止・新モデル・API変更を残し、impact dashboard等の管理・活用情報を低優先にする設定をdry-runで比較する。
4. **不足領域はGemini SDKから小さく評価**。他社モデルや多数のMCPサーバーを一括追加しない。追加時は新フィードのフィクスチャ、分類・集約・重複・プレリリース除外のテスト、実フィード取得確認を行う。
5. **取得成否の永続化はF04で検討**。今回の資料は監視ダッシュボードではない。フィード別の最終成功日・候補分母は、将来実行時の状態として記録する必要があり、古いログから捏造しない。

本PRでは設定・選定規則・保存記事を変更しない。選定を変更する段階で、修正前後の差分・取りこぼし・ノイズをF11で確認する。既存記事の一括削除や履歴の再構築は行わない。

## 影響と検証

- **Actions**: workflow・収集入口は変更なし。追加コマンドを自動収集へ組み込まず、API枠と秘密値の扱いも変わらない。
- **ログ・検索**: 読み取り専用のレポートを追加。ログ・seen・months・検索インデックスは変更せず、既存検索のデータ形式も維持する。
- **GitHub Pages**: トップ画面・JS・CSSは変更なし。READMEから評価資料へ辿れるようにする。独立したWebダッシュボードは追加しない。
- **テスト**: 期間境界、集約カードと追加URL、未帰属・旧情報源、曖昧な出所推定、0件、入力不変、逆転した期間の拒否を追加テストで検証する。既存の収集・選定・重複排除・検索テストも実行する。
- **残る確認**: この環境で制限されたニュース3フィード・Actions詳細ログ・Cursor候補の到達性。今回のForbiddenは配信元の品質評価や取得成功率には算入していない。
