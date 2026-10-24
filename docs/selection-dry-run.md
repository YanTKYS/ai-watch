# 選定ルールのdry-run（F11）

`collect.py --dry-run` は、通常収集と同じ `collect_feeds()` / `choose()` に合成入力を渡し、採否・カテゴリ・スコア・理由・リリース集約先を表示する。入力履歴を含めて読み取り専用で、ログ・data・設定・検索インデックスを変更しない。Brave検索や他のAI APIは呼ばず、APIキーが設定されていても利用しない。新しい依存関係・サービスは不要。

## 基本操作

リポジトリ直下から実行する。仮想環境を使う場合は `python` を `.venv/bin/python` に読み替える。

```sh
# 同梱の合成データと、その中の採否履歴で評価（通信しない）
python scripts/collect.py --dry-run

# フィクスチャ内で除外済みの例も、同じ規則で再評価
python scripts/collect.py --dry-run --reconsider-excluded

# 完全な設定ファイル同士を、同じ入力・同じ履歴・同じ日付で比較
python scripts/collect.py --dry-run --reconsider-excluded \
  --config config/sources.yml --compare-config /tmp/ai-watch-candidate.yml

# 独自の合成データ・ローカル履歴を使う（履歴は更新しない）
python scripts/collect.py --dry-run --fixtures /tmp/evaluation.json \
  --seen data/seen.json --reconsider-excluded
```

`--dry-run` なしでは従来どおり実際の収集を行う。`--config` は通常収集にも使えるが、`--fixtures` / `--seen` / `--compare-config` はdry-run専用で、dry-runなしではエラーにする。dry-runの `--skip-brave` は省略してよい。ライブ取得モードは今回追加していない。

## 出力の読み方

最初にモード・評価日・再評価フラグを表示し、設定ごとの件数を示す。その後は記事ごとのJSON Linesで、`current` / `candidate` を並べる。両方で変更がない記事も表示し、正例の取りこぼしを確認できる。

- `status`: `adopted`（採用）、`rejected`（選定で除外）、`skipped`（選定前にスキップ）。採用記事数と集約後の `cards` は別の数値。
- `score`: `score`方式の点数。リリース方式・all方式・事前スキップは `null`。内部のソート値を品質スコアとは扱わない。
- `reason` / `detail`: 採用方式、notable/unknown、除外理由、該当スコア規則と加減点、リリース種別件数など。
- `grouped_into`: 他の採用リリースへ集約される場合のURL。集約内の各記事も個別に比較する。
- `changed`: 採否だけでなく、カテゴリ・スコア・理由・集約先などが変わった場合もtrue。片方だけにあるフィードの記事は他方が `null`。
- `seen:excluded`: 履歴で除外済み。`--reconsider-excluded` で再評価する。採用済み・集約済みは再評価せず、`seen/duplicate` としてスキップする。
- `require_keywords` は必須語なし、`age/title/max_items` は公開日・タイトル除外規則・フィード上限による事前スキップ。選定時の採用上限超過は別の `over_limit`。

記事のキーは `(フィードURL, 記事URL)`。カテゴリは通常の保存時に使うカテゴリ（集約記事は代表リリースのカテゴリ）で、スキップ・除外記事では採用した場合のカテゴリを示す。URL・タイトルは表示するが、説明文・リリースノート本文や環境変数は出力しない。JSON部分は改行・制御文字をエスケープする。通常dry-runの終了コード0は処理成功を表し、変更案が望ましいことまでは保証しない。入力不備は2で終了する。追加の品質チェックと終了コード3は後述。

## 合成フィクスチャの形式

既定は [selection-evaluation.json](../tests/fixtures/selection-evaluation.json)。F12の代表例を基に、URL・日付・説明文・リリース本文を合成している。実フィードのアーカイブやActions実行時スコアの再現ではない。ニュース見出しに似た例もあるが、リリースのバージョンは架空で、文章は最小限の評価用データ。

```json
{
  "today": "2026-10-24",
  "feeds": {
    "https://openai.com/news/rss.xml": [
      {
        "title": "Introducing Example GPT-9",
        "url": "https://evaluation.example.org/model",
        "published": "2026-10-24",
        "summary": "A synthetic API announcement.",
        "content": "",
        "categories": []
      }
    ]
  },
  "seen": {}
}
```

上は形式を示す最小例。実際には両設定にあるすべてのフィードURLを指定し、0件は `[]` と明示する。未指定フィードはエラーにして、追加フィードの入力漏れを「記事なし」と誤認しない。片方で未設定のフィード入力は許可する。各記事は `feeds.Entry` と同じフィールドで、title/url/publishedが必須。URLは通常収集と同じ最小正規化を行い、同じフィード内の重複URLは入力ミスとして拒否する。RSS/Atomやgzip自体の解析は既存フィクスチャ・回帰テストの担当とし、このJSONは解析後の記事を入力する。

`today` は固定の評価日。実行日に左右されず、公開から7日以内・未来日の除外も通常と同じ条件で評価する。`seen` 省略時は空履歴。既定では本番の `data/seen.json` を読まないため、評価例がすべて既読で消えることを避ける。実履歴で評価したい場合だけ `--seen` を明示する。`expectations` は品質評価用のメタデータで、通常dry-runの選定・出力・終了コードには影響しない。旧keep/review/check文字列も通常dry-runでは従来どおり無視する。

## 再現できる比較例（F17第2段階）

同じ現在の分類器・固定日付・フィクスチャで、変更前の設定と今回のニュース設定を比較する。過去の記事や履歴は書き換えない。

```sh
# 第2段階の変更前の設定を一時ファイルへ取り出す（Git履歴が必要）
git show 839e171:config/sources.yml > /tmp/ai-watch-before-news.yml
python scripts/collect.py --dry-run --evaluate --reconsider-excluded \
  --config /tmp/ai-watch-before-news.yml --compare-config config/sources.yml
python scripts/collect.py --dry-run --check-quality --reconsider-excluded \
  --config /tmp/ai-watch-before-news.yml --compare-config config/sources.yml \
  --fixtures tests/fixtures/selection-validation.json
python scripts/collect.py --dry-run --check-quality --reconsider-excluded \
  --config /tmp/ai-watch-before-news.yml --compare-config config/sources.yml \
  --fixtures tests/fixtures/selection-news-validation.json
```

採用した変更はGitHub Changelogのscore化と2規則だけ。`adoption_reporting` は組織のimpact/adoption/usageのダッシュボード・分析・ROI等を限定的に減点し、タイトルにAPI/SDK/CLI（複数形を含む）がある場合は適用しない。`developer_operations` はポリシーAPI・データ所在・地域エンドポイント・明示的なAPIアクセス拡大を加点し、政治・地域関連の減点だけで利用条件の技術更新が落ちることを防ぐ。閾値2・各規則の既存重み・1フィード最大5件は変えない。

score化だけの候補では、新ニュース境界例が一致8/不一致5のままで、policy APIやデータ所在が政治/地域語で落ちたため採用しなかった。投資家・生物分野等の語を追加して一括減点する案、Google Cloudやprogramming languagesを含むだけで加点する案、policy系の減点を一律に緩める案も採用しない。

| 評価セット | 変更前 → 変更後の一致/不一致 | 改善 / 悪化 / 未変化 / 保留 |
| --- | --- | --- |
| 既存調整用（確定10、保留7） | 9/1 → 10/0 | 1 / 0 / 9 / 7 |
| 既存検証用（確定11） | 11/0 → 11/0 | 0 / 0 / 11 / 0 |
| 追加ニュース境界例（確定13） | 8/5 → 13/0 | 5 / 0 / 8 / 0 |

既存調整用の採用・除外・集約後カード数は両設定とも9・6・9。ただし内訳は変わり、dashboardを除外し、未確定の地域アクセス例が採用側に動く。件数が同じことを無変更・品質同等の証拠にはしない。

追加ニュース例は規則比較前に採否・根拠を記述し、本文・期待値を変更せず比較した。管理レポート2件が採用枠を占めて重要記事2件が上限超過になる例も含み、変更後は管理記事を除外して重要5件を採用する。上限を増やして解消したわけではない。追加例は今回のリスクに合わせて作った公開の合成例で、未知データへの一般化の証拠ではない。

## 期待値集計と品質チェック（F18）

F17の選定改善に向け、人が確定した期待値を通常の選定結果と照合する。選定ロジックは再実装せず、F11の判断記録を使う。リリース種別は通常選定と同じ `selection.release_counts()` を各記事の合成本文に適用し、集約前の記事単位で比較する。

```sh
# 不一致があっても処理成功は0。各記事と設定別・split別の集計を表示
python scripts/collect.py --dry-run --evaluate --reconsider-excluded
python scripts/collect.py --dry-run --evaluate --reconsider-excluded \
  --config /tmp/ai-watch-before-news.yml --compare-config config/sources.yml

# CIと同じ固定例のチェック（未解消の既知課題すべてを失敗扱いにはしない）
python scripts/collect.py --dry-run --check-quality --reconsider-excluded
python scripts/collect.py --dry-run --check-quality --reconsider-excluded \
  --fixtures tests/fixtures/selection-validation.json
python scripts/collect.py --dry-run --check-quality --reconsider-excluded \
  --fixtures tests/fixtures/selection-news-validation.json
```

`--evaluate` / `--check-quality` はdry-run専用。後者は集計も行うので両方の指定は不要。比較時にチェックする対象は**candidate**、単体時は**current**。修復前のcurrentに固定例の不一致があっても、candidateで直っていればチェックは成功する。両設定の不一致は出力に残る。

| 終了コード | 意味 |
| --- | --- |
| 0 | 通常dry-run/集計の処理成功、または品質チェック対象の固定例が一致 |
| 2 | 入力・設定不備。品質チェックで固定例が1件もない場合も含む |
| 3 | `--check-quality` の対象設定に、`required: true` の期待値不一致がある |

### 期待値の記述

フィクスチャの `expectations` は記事URLをキーとする。根拠・フィード・用途を明示し、採否が未確定なら `expected: null` とする。URLは正規化後の入力記事と一致させる。

```json
{
  "expectations": {
    "https://evaluation.example.org/new-model": {
      "feed_url": "https://openai.com/news/rss.xml",
      "split": "tuning",
      "expected": {"status": "adopted", "category": "AIモデル"},
      "reason": "新モデルの提供開始は重要な技術更新。",
      "required": true
    }
  }
}
```

- `expected.status` は `adopted` / `rejected`。`category` は既存の表示名による任意の照合項目。
- リリースでは `release_counts: {"breaking": 1, "chore": 0}` 等を追加できる。feature/change/breaking/fix/chore/otherの指定した種別だけを照合する。値は0以上の整数。通常記事・事前スキップ・all方式では分類結果はnullであり、分類の期待値があれば不一致になる。
- `reason` は判断の根拠、`split` は `tuning`（調整用）か `validation`（検証用）。文字列の旧keep/review/checkや期待値未指定の記事は**すべて要確認**にし、keepを採用正解、reviewを除外正解へ暗黙に読み替えない。
- `required: true` は固定した重要正例や、明確な定型的修正などCIで保護する確定例。未確定例には指定できない。既知の不一致は `required: false` として可視化し、正しい挙動へ修正した後で固定例への追加を判断する。不一致を消すために期待値を現行動作へ寄せない。
- 未設定フィードの任意例は未評価（pending）とし、確定例の分母から外す。ただしrequired例の情報源を外したり、既読・期間・上限等でスキップした場合はチェックをすり抜けさせず不一致にする。存在しない記事参照、未知フィールド、分類種別の誤記などは入力エラー。

### 出力と変更前後の評価

従来のdry-run出力の後に、`QUALITY current/candidate all/tuning/validation` の件数を追加する。`confirmed = match + mismatch` が評価の分母、`pending` は分母外で、期待値未確定の `undecided` と任意の未設定フィードの `not_configured` を分けて表示する。requiredの不一致は `required_failed` に出る。

続くJSON Linesは `"quality": true` で識別し、期待値・実際の採否/カテゴリ/分類・根拠・不一致項目を表示する。`change` は不一致項目が減ればimproved、増えればregressed、改善と悪化が同居すればmixed、同じ項目集合ならunchanged。片方がpendingならpendingとし、未評価からの対象追加を品質改善と同一視しない。採否・分類・カテゴリのどこが変わったかは `differences` で確認する。

### 現在の基準結果と次工程

| 評価セット | 確定 | 一致 | 不一致 | 要確認/未評価 | CI固定例 |
| --- | ---: | ---: | ---: | --- | ---: |
| 調整用 `selection-evaluation.json` | 10 | 10 | 0 | 未確定5、未設定フィード2 | 10 |
| 検証用 `selection-validation.json` | 11 | 11 | 0 | 0 | 9 |
| ニュース境界例 `selection-news-validation.json` | 13 | 13 | 0 | 0 | 13 |

3セットの固定品質チェックは成功する。F18導入時の調整用不一致4件のうち、F17第1段階でリリース分類3件、第2段階でdashboardの1件を改善した。検証用11例は第1段階後の結果を維持する。調整用のdashboardは期待値を変えずrequiredへ昇格。未確定5件と未設定フィード2件は依然として分母外であり、全記事の正しさを確認したことにはならない。

新モデル、新API、モデル廃止、Codexの実用機能は固定正例として保護する。検証用には、説明文だけに技術的根拠のある例、技術的に有益な活用事例、新モデル提供を否定する文、修正専用リリースを含めた。公開CLIフラグの削除と公開API引数削除の本当の破壊的変更も保護し、内部・サンプル変更を除外する今後の修正で巻き添えにしない。

`min_score` を100にした試験用設定では新モデル等の固定正例が落ち、`--check-quality` は3、集計だけの `--evaluate` は0で終わる。固定例を消す・期待値を現行へ寄せることで成功させず、不一致の原因を確認する。

### F17第1段階の変更前後と適用範囲

| セット | 変更前（F18時点） | 変更後 | 記事単位の改善 / 悪化 / 未変化 / 保留 |
| --- | --- | --- | --- |
| 調整用 | 一致6・不一致4・pending7 | 一致9・不一致1・pending7 | 3 / 0 / 7 / 7 |
| 検証用 | 一致9・不一致2・pending0 | 一致11・不一致0・pending0 | 2 / 0 / 9 / 0 |

変更はリリース項目の分類だけ。明示されたinternal/CI/docs/examples等の作業スコープ・対象、雑務の見出しを考慮し、`remove`一般を除外しない。Conventionalの `!` や明示的なBREAKING CHANGEを尊重し、雑務見出しでも公開CLIフラグ/API引数の削除は残す。既知の定型修正文だけをfixとし、未知の記述は従来どおりother/unknownで採用する。見出しだけの定型修正文は1項目と扱い、具体的な項目が続く場合は二重計上しない。強調・inline codeのMarkdown記号は分類時だけ外し、抜粋テキストを書き換えない。

調整用の定型修正文・CI削除・examples修正の3例は、期待する採否・件数を変えず `required` へ昇格した。定型修正文は実際の [Claude Code v2.1.303](https://github.com/anthropics/claude-code/releases/tag/v2.1.303)、作業文脈は [Anthropic SDK v2.3.0](https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.3.0) でも確認し、公開フラグ削除は [Claude Code v2.1.300](https://github.com/anthropics/claude-code/releases/tag/v2.1.300) と対照した。短い抜粋と別表現の単体テスト、通常収集→集約→検索インデックスまでの統合テストで再発を保護する。検証用JSONは本文・期待値・requiredを含めて未変更で、分類器の修正後に回帰確認した。

第1段階の変更は今後の通常収集とdry-runで共通に使われる。既存のMarkdown正本・seen・インデックスの一括修正や再収集は行わない。既存の不採用履歴は自動で再評価されない。作業スコープ・言い回しに基づく機械分類なので、すべての利用者影響を理解できるとは主張しない。第1段階ではニューススコアを変更せず、第2段階の変更は次節のとおり。情報源・未知のリリース内容の採用方針は維持する。

### F17第2段階の判断保留・運用への影響

Terminal X、生物学のagents活用、OpenAI models on Google Cloud、low-resource programming languages、地域アクセス変更の5例はexpected:nullを維持した。今回も公式ニュース3フィードの取得がプロキシCONNECT 403で、実タイトル・説明文を追加確認できなかった。投資・研究の一括除外や、特定クラウド名だけでの加点は行わない。地域アクセス例は加点で採用に動いたが、正解が確定したとは集計しない。

追加例では、具体的な推論APIのクラウド提供、APIエンドポイントが追加される地域アクセス、Copilot data residency、モデル廃止・料金・制限、技術的な活用事例と再現可能な研究評価を保護する。単にクラウド名・言語名・地域があるだけの元の未確定例と区別する。APIの語による報告記事の減点除外も機械的な手掛かりで、すべてのAPI記事が有用だと保証するものではない。

今後の収集では、Changelogの新たな不採用はadoption_reporting等の理由とfirst_seenをseenへ残すため、再実行で自動復活しない。過去のseen・記事はそのままで、除外再評価は必要な場合だけ明示的に行う。上限超過は従来どおり履歴へ除外保存せず、次回の候補に残す。通常収集の統合テストで、重要5記事の保存、管理記事の除外履歴、既存履歴の保持、7件中5件→次回残り2件の採用を確認する。

今後も調整用で比較し、既存検証用は固定したまま最後の回帰確認に使う。公開された小規模合成例は統計的な代表標本ではなく、件数をニュース全体の精度・採用率とは呼ばない。検証例を見て調整した場合はその事実を明記し、新しい未調整例を加える。

## 検証範囲

通常収集の回帰テストに加え、通信・書き込み経路が呼ばれないこと、入力ファイルのバイト列不変、再実行の同一出力、0件、除外再評価、上限超過、集約、既読・フィード間重複・必須語スキップ、設定変更・情報源追加・不正入力を検証する。期待値集計は未確定例・旧注記・既知の不一致・カテゴリ/分類の差分、candidateだけのチェック、固定例の退行時の終了コードも検証する。

```sh
python -m unittest discover -s tests -v
```

テストActionsは3セットの品質チェックを実行する。本番のニュース選定条件は今回変更するが、収集Actions、GitHub PagesのUI、Markdown保存形式、保存済み検索インデックス、リリース分類、情報源・Brave上限には変更がない。
