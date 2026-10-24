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

## 再現できる比較例

以下は**検証用の仮説**として設定コピーを作る例。本番には反映しない。採用閾値を一律に上げる代わりに、業界・管理情報を減点し、提供先拡大・プログラミング言語の記事を加点、地域関連の減点を緩める。併せてGemini SDKの入力例も評価する。

```sh
python - <<'PY'
from pathlib import Path
import yaml
raw = yaml.safe_load(Path('config/sources.yml').read_text())
for feed in raw['feeds']:
    if feed['name'] == 'GitHub Changelog':
        feed['select'] = 'score'
for rule in raw['selection']['rules']:
    if rule['label'] == 'policy_society':
        rule['weight'] = -1
raw['selection']['rules'] += [
    {'label': 'industry_or_management', 'weight': -3,
     'terms': ['investor', 'biological data', 'impact dashboard']},
    {'label': 'developer_availability', 'weight': 2,
     'terms': ['Google Cloud', 'programming languages']},
]
raw['feeds'].append({
    'name': 'Gemini Python SDK Releases',
    'url': 'https://github.com/googleapis/python-genai/releases.atom',
    'category': 'api', 'classify': False, 'select': 'release_notes',
    'title_prefix': 'Gemini Python SDK',
})
Path('/tmp/ai-watch-candidate.yml').write_text(
    yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
PY
python scripts/collect.py --dry-run --reconsider-excluded \
  --compare-config /tmp/ai-watch-candidate.yml
```

### 比較結果（2026-10-24時点の設定・同梱データ）

| 指標 | 現行 | 検証案 |
| --- | ---: | ---: |
| 評価記事（フィード追加分を含む） | 15 | 17 |
| 採用（集約前） | 12 | 13 |
| 除外 | 3 | 4 |
| 集約後のカード | 10 | 11 |

記事単位の差分は9件。採否が同じでも方式変更による理由・スコアの差分を含む。

| 評価例 | 現行 → 検証案 | 判断材料 |
| --- | --- | --- |
| 新モデル発表 / Decisions API / Copilotモデル廃止 / Codex実用機能 | いずれも採用 → 採用 | F12の主要な正例をこの入力では維持 |
| Terminal Xの投資事例 | 採用（2）→ 除外（-1） | 業界事例を抑える仮説 |
| 生物データへのagents活用例 | 採用（4）→ 除外（1） | 技術的な実装・評価のある研究まで落とさないか追加の正例が必要 |
| Copilot impact dashboard | all方式で採用 → 除外（-1） | 必須語だけを通す方式との差が見える |
| OpenAI models on Google Cloud / low-resource programming languages | 除外（0）→ 採用（2） | 過剰除外の確認候補。後者は履歴で除外済みなので再評価フラグが必要 |
| API提供地域の変更 | 除外（1）→ 採用（3） | policy系減点緩和の効果。説明文は合成であり実記事の採否を断定しない |
| 曖昧な修正文 / SDKのinternal・examples削除 | 採用 → 採用、分類も不変 | `release_notes` の分類器は設定コピーでは変わらない。修正文・内部変更の誤分類は別途修正・テストが必要 |
| Gemini SDKの機能追加・修正のみ | 現行は未設定 → 機能追加を採用、修正のみを除外 | 単純な合成例は扱える。Gemini APIへの通信はしていない |

**今回の判断**: この検証案は採用しない。例に合わせた語の加減点だけでは一般化を保証できず、研究の技術的知見や地域変更の重要性を評価する追加例が要る。Gemini SDKも追加候補のままとし、F12の実Atom解析成功に加えて、実リリースの形式差・プレリリース・重複を含む評価が済んでから採否を決める。dry-runは安全な比較手段を提供し、本番の選定改善・情報源変更を自動実行しない。

## 期待値集計と品質チェック（F18）

F17の選定改善に向け、人が確定した期待値を通常の選定結果と照合する。選定ロジックは再実装せず、F11の判断記録を使う。リリース種別は通常選定と同じ `selection.release_counts()` を各記事の合成本文に適用し、集約前の記事単位で比較する。

```sh
# 不一致があっても処理成功は0。各記事と設定別・split別の集計を表示
python scripts/collect.py --dry-run --evaluate --reconsider-excluded
python scripts/collect.py --dry-run --evaluate --reconsider-excluded \
  --compare-config /tmp/ai-watch-candidate.yml

# CIと同じ固定例のチェック（未解消の既知課題すべてを失敗扱いにはしない）
python scripts/collect.py --dry-run --check-quality --reconsider-excluded
python scripts/collect.py --dry-run --check-quality --reconsider-excluded \
  --fixtures tests/fixtures/selection-validation.json
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
| 調整用 `selection-evaluation.json` | 10 | 6 | 4 | 未確定5、未設定フィード2 | 6 |
| 検証用 `selection-validation.json` | 11 | 9 | 2 | 0 | 9 |

両セットの品質チェックは現時点で成功する。不一致の4件/2件を隠した結果ではなく、今回の対象を固定例の退行検出に限定したため。調整用の不一致はimpact dashboard、曖昧な修正文、SDK内部・サンプル変更。検証用も別表現/HTMLの内部・サンプル削除がbreakingとして扱われる2件が不一致となる。

新モデル、新API、モデル廃止、Codexの実用機能は固定正例として保護する。検証用には、説明文だけに技術的根拠のある例、技術的に有益な活用事例、新モデル提供を否定する文、修正専用リリースを含めた。公開CLIフラグの削除と公開API引数削除の本当の破壊的変更も保護し、内部・サンプル変更を除外する今後の修正で巻き添えにしない。

上の比較案生成例に `--evaluate` を加えると、currentは一致6/不一致4/pending7、candidateは一致9/不一致3/pending5となる。記事単位ではdashboardの期待値が改善、悪化0、変化なし9、判断保留7。Gemini SDKの2例が未評価から一致に変わる分は、既存記事の改善と分ける。`min_score` を100にした試験用設定では新モデル等の固定正例が落ち、`--check-quality` は3、集計だけの `--evaluate` は0で終わる。

F17で規則・分類器を調整するときは調整用で比較し、検証用は固定したまま最後の回帰確認に使う。両方とも公開された小規模な合成例で、隠れたテストや統計的な代表標本ではない。この件数をニュース全体の精度・採用率とは呼ばず、検証例を見て規則を調整した場合はその事実を明記し、新しい未調整例を加える。

## 検証範囲

通常収集の回帰テストに加え、通信・書き込み経路が呼ばれないこと、入力ファイルのバイト列不変、再実行の同一出力、0件、除外再評価、上限超過、集約、既読・フィード間重複・必須語スキップ、設定変更・情報源追加・不正入力を検証する。期待値集計は未確定例・旧注記・既知の不一致・カテゴリ/分類の差分、candidateだけのチェック、固定例の退行時の終了コードも検証する。

```sh
python -m unittest discover -s tests -v
```

テストActionsは上の両セットの品質チェックを実行する。収集Actions、GitHub PagesのUI、Markdown保存形式、検索インデックス、本番の選定規則・情報源・Brave上限には変更がない。
