"""フィード記事の選定（v0.1.3）。「読むと AI・AIコーディングツールについて新しい技術的知見が得られるか」を、
設定（config/sources.yml の selection）に従って機械的に判定する。外部APIは使わない。

- ニュース系（select: score）: タイトル・説明文に設定の規則を当てて点数を付け、min_score 以上を採用する。
  単語1つで一律に除外せず、技術的な信号（新モデル・提供開始・API・料金変更など）と、
  導入事例・政策・教育などの信号を合算して判断する。
- リリース系（select: release_notes）: リリースノートの各項目を「新機能・変更・破壊的変更・修正・雑務」に分類し、
  修正・雑務だけのリリースを除外する。判定できないリリースは見落とさないよう採用する。
  1回の収集で採用した同じフィードのリリースは1件にまとめ、項目数（機械的な集計）と、
  公式リリースノートの記載から機械的に選んだ数項目（原文のまま・バージョン付き）、各リリースへのリンクを添える。
  推測による要約は作らない。項目を判定できない場合は抜粋せず、リンクだけを残す。
- 不採用の記事は理由とともに seen.json に記録し、次回以降の収集で復活させない（collect.py）。
"""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field

from common import ConfigError, compile_terms, matches_any

MODES = ("all", "score", "release_notes")
FIELDS = ("title", "summary", "any", "categories")
DEFAULT_MIN_SCORE = 2
DEFAULT_MAX_NEW_PER_FEED = 5


@dataclass
class Rule:
    label: str
    weight: int
    field: str  # title | summary | any | categories（フィードが記事に付けたカテゴリ）
    patterns: list[re.Pattern]

    def matches(self, title: str, summary: str, categories: list[str]) -> bool:
        text = {"title": title, "summary": summary, "any": f"{title}\n{summary}",
                "categories": "\n".join(categories)}[self.field]
        return matches_any(text, self.patterns)


@dataclass
class Selection:
    min_score: int = DEFAULT_MIN_SCORE
    max_new_per_feed: int = DEFAULT_MAX_NEW_PER_FEED
    rules: list[Rule] = field(default_factory=list)


def load_selection(raw: object) -> Selection:
    if raw is None:
        return Selection()
    if not isinstance(raw, dict):
        raise ConfigError("'selection' はマッピングにしてください")
    min_score = raw.get("min_score", DEFAULT_MIN_SCORE)
    max_new = raw.get("max_new_per_feed", DEFAULT_MAX_NEW_PER_FEED)
    for key, value, low in (("min_score", min_score, -100), ("max_new_per_feed", max_new, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= 100:
            raise ConfigError(f"selection.{key} が不正です: {value!r}")
    rules = []
    for r in raw.get("rules", []) or []:
        if not isinstance(r, dict) or not isinstance(r.get("label"), str) or not r["label"].strip():
            raise ConfigError("selection.rules の各要素に文字列の 'label' が必要です")
        label = r["label"].strip()
        weight = r.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight == 0:
            raise ConfigError(f"selection.rules '{label}' の weight は0以外の整数にしてください")
        where = r.get("in", "title")
        if where not in FIELDS:
            raise ConfigError(f"selection.rules '{label}' の in は {' / '.join(FIELDS)} のいずれかにしてください")
        patterns = compile_terms(r.get("terms"), f"selection.rules '{label}' の terms")
        regexes = r.get("patterns", []) or []
        if not isinstance(regexes, list) or not all(isinstance(p, str) and p for p in regexes):
            raise ConfigError(f"selection.rules '{label}' の patterns は文字列のリストにしてください")
        try:
            patterns += [re.compile(p, re.IGNORECASE) for p in regexes]
        except re.error as e:
            raise ConfigError(f"selection.rules '{label}' の patterns が正規表現として不正です: {e}") from e
        if not patterns:
            raise ConfigError(f"selection.rules '{label}' に terms か patterns が必要です")
        rules.append(Rule(label=label, weight=weight, field=where, patterns=patterns))
    return Selection(min_score=min_score, max_new_per_feed=max_new, rules=rules)


def score(sel: Selection, title: str, summary: str = "", categories: list[str] = ()) -> tuple[int, list[Rule]]:
    """(点数, 該当した規則)。各規則は1記事につき1回だけ数える。"""
    matched = [rule for rule in sel.rules if rule.matches(title, summary, list(categories))]
    return sum(rule.weight for rule in matched), matched


def rejection_reason(matched: list[Rule]) -> str:
    """不採用の理由。減点の規則に該当していれば最も重いもののラベル、なければ low_score（技術的な信号が足りない）。"""
    negatives = [rule for rule in matched if rule.weight < 0]
    return min(negatives, key=lambda r: r.weight).label if negatives else "low_score"


def describe(matched: list[Rule]) -> str:
    return ",".join(f"{r.label}{r.weight:+d}" for r in matched) or "-"


# ---- リリースノート ----------------------------------------------------------
KINDS = ("feature", "change", "breaking", "fix", "chore", "other")
KIND_LABELS = {"feature": "新機能", "change": "変更・改善", "breaking": "破壊的変更・廃止", "fix": "修正"}
_SECTION_RULES = [  # 見出しの語 → 項目の種類（上から順に判定）
    ("breaking", re.compile(r"breaking|deprecat|remov", re.I)),
    ("fix", re.compile(r"\bfix|bug", re.I)),
    ("chore", re.compile(r"chore|doc|internal|test|\bci\b|build|depend|refactor|merged|contributor|style", re.I)),
    ("feature", re.compile(r"feature|highlight|\bnew\b|added|addition", re.I)),
    ("change", re.compile(r"change|improv|update|perf|enhance", re.I)),
]
_PREFIX_RULES = [  # 項目の先頭の語 → 種類
    ("breaking", re.compile(r"^(breaking|removed?|deprecat\w*|drop(ped)?)\b", re.I)),
    ("feature", re.compile(r"^(added|add|adds|new|introduc\w*|supports?|now supports|enabled?|launch\w*)\b", re.I)),
    ("change", re.compile(r"^(changed|change[sd]?|improved|improves?|updated?|updates|faster|reduced|increased|"
                          r"made|renamed|moved|optimi[sz]\w*|perf|reverted)\b", re.I)),
    ("fix", re.compile(r"^(fixed|fix|fixes|resolved?|corrected)\b", re.I)),
]
_CONVENTIONAL = re.compile(r"^(feat|fix|perf|refactor|chore|docs?|test|ci|build|style|revert)(\([^)]*\))?(!)?:\s*", re.I)
_CONVENTIONAL_KIND = {"feat": "feature", "fix": "fix", "perf": "change", "revert": "change"}
_LEAD = re.compile(r"^(?:\[[^\]]{1,40}\]\s*|[A-Za-z][\w .-]{0,30}:\s+)+")  # "[VSCode] " "Windows: " "api: " など
_BLOCK = re.compile(r"</?(p|li|ul|ol|div|br|tr|pre|blockquote)\b[^>]*>", re.I)
_HEADING = re.compile(r"<h[1-6][^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def note_lines(content: str) -> list[tuple[bool, str]]:
    """リリースノート（HTMLまたはテキスト）を (見出しか, 1行のテキスト) に分ける。"""
    text = _HEADING.sub("\n\x00", content)
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    lines = []
    for raw in text.split("\n"):
        heading = raw.startswith("\x00") or raw.lstrip().startswith("#")
        line = raw.replace("\x00", "").strip().lstrip("#").strip().lstrip("•*-–· ").strip()
        if line:
            lines.append((heading, " ".join(line.split())))
    return lines


def classify_item(line: str, section: str | None) -> str:
    m = _CONVENTIONAL.match(line)
    if m:
        if m.group(3):  # feat!: など
            return "breaking"
        return _CONVENTIONAL_KIND.get(m.group(1).lower(), "chore")
    for body in (line, _LEAD.sub("", line)):  # "Improved artifacts: ..." と "[VSCode] Fixed ..." の両方を扱う
        for kind, rx in _PREFIX_RULES:
            if rx.match(body):
                return kind
    return section or "other"


def classified_items(content: str) -> list[tuple[str, str]]:
    """リリースノートの各項目を (種類, 1行のテキスト) にする（記載順）。"""
    items = []
    section: str | None = None
    for heading, line in note_lines(content):
        if heading:
            section = next((kind for kind, rx in _SECTION_RULES if rx.search(line)), None)
            continue
        if len(line) < 4 or line.lower().startswith(("full changelog", "what's changed", "new contributors")):
            continue
        items.append((classify_item(line, section), line))
    return items


def release_counts(content: str) -> dict[str, int]:
    counts = dict.fromkeys(KINDS, 0)
    for kind, _ in classified_items(content):
        counts[kind] += 1
    return counts


HIGHLIGHT_KINDS = ("breaking", "feature", "change")  # 抜粋する種類と優先順（修正・雑務は抜粋しない）
MAX_HIGHLIGHTS = 3
MAX_HIGHLIGHT_CHARS = 200
_SCOPED = re.compile(r"^(?:\[[^\]]{1,40}\]|[A-Za-z][\w .-]{0,30}:)\s")  # "[VSCode] ..." "Windows: ..." など特定環境向け


def pick_highlights(releases: list[tuple[str, str]], limit: int = MAX_HIGHLIGHTS) -> list[str]:
    """リリースノートから重要度の高い項目を機械的に選ぶ。releases は新しい順の (バージョン, リリースノート)。

    優先順: 破壊的変更・廃止 > 新機能 > 変更・改善。同じ種類では、特定環境向け（[VSCode] など）でない項目を優先し、
    複数リリースのときは各リリースの記載順の先頭から順に（新しいリリースから）選ぶ。
    文章は公式の記載のまま（長い場合のみ末尾を省略）で、推測で書き換えない。
    """
    candidates = []
    for r, (version, content) in enumerate(releases):
        seen_in_release = Counter()
        for kind, line in classified_items(content):
            if kind not in HIGHLIGHT_KINDS:
                continue
            scoped = bool(_SCOPED.match(line))
            key = (HIGHLIGHT_KINDS.index(kind), scoped, seen_in_release[(kind, scoped)], r)
            seen_in_release[(kind, scoped)] += 1
            candidates.append((key, kind, version, line))
    out = []
    for _, kind, version, line in sorted(candidates)[:limit]:
        if len(line) > MAX_HIGHLIGHT_CHARS:
            line = line[:MAX_HIGHLIGHT_CHARS - 1].rsplit(" ", 1)[0] + "…"
        out.append(f"{KIND_LABELS[kind]}（{version}）: {line}")
    return out


def release_verdict(counts: dict[str, int]) -> str:
    """notable（新機能・変更・破壊的変更あり） / minor（修正・雑務のみ） / unknown（判定できない）。"""
    if counts["feature"] or counts["change"] or counts["breaking"]:
        return "notable"
    if counts["other"] or not (counts["fix"] or counts["chore"]):
        return "unknown"  # 見落とさないよう採用する
    return "minor"


def format_counts(counts: dict[str, int]) -> str:
    return " / ".join(f"{label} {counts[kind]}" for kind, label in KIND_LABELS.items())
