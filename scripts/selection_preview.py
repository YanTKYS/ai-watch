"""collectの共通選定処理を合成入力で評価する。書き込み・ネットワーク用の経路を持たない。"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import date
from pathlib import Path

import collect
import feeds
import selection
from common import ConfigError, normalize_url


def load_fixture(path: Path) -> tuple[str, dict, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("feeds"), dict):
        raise ConfigError("fixturesにはtodayとfeedsマッピングが必要です")
    today = date.fromisoformat(raw["today"]).isoformat()
    mapping = {}
    for url, entries in raw["feeds"].items():
        if not normalize_url(url) or not isinstance(entries, list):
            raise ConfigError("fixturesのfeedsはURLから記事配列へのマッピングにしてください")
        mapping[url] = []
        urls = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - set(feeds.Entry.__dataclass_fields__):
                raise ConfigError("fixturesの記事フィールドが不正です")
            e = feeds.Entry(**entry)
            if not all(isinstance(v, str) for v in (e.title, e.url, e.published, e.summary, e.content)):
                raise ConfigError("fixturesの記事フィールドは文字列にしてください")
            if not isinstance(e.categories, list) or not all(isinstance(c, str) for c in e.categories):
                raise ConfigError("fixturesのcategoriesは文字列配列にしてください")
            e.url = normalize_url(e.url)
            if not e.url or not e.title.strip() or date.fromisoformat(e.published).isoformat() != e.published:
                raise ConfigError("fixturesのURL・タイトル・公開日が不正です")
            if e.url in urls:
                raise ConfigError("fixturesの同じフィード内に重複URLがあります")
            urls.add(e.url)
            mapping[url].append(e)
    seen = raw.get("seen", {})
    if not isinstance(seen, dict) or not all(isinstance(v, dict) for v in seen.values()):
        raise ConfigError("fixturesのseenはURLから履歴へのマッピングにしてください")
    return today, mapping, seen


def load_expectations(path: Path, mapping: dict) -> dict:
    """旧keep/review/checkは全て要確認。明示した根拠・期待値だけを機械判定する。"""
    raw = json.loads(path.read_text(encoding="utf-8")).get("expectations", {})
    if not isinstance(raw, dict):
        raise ConfigError("expectationsはURLから期待値へのマッピングにしてください")
    result = {}
    for url, meta in raw.items():
        if isinstance(meta, str):
            # 旧注記を除外正解や固定の重要例へ暗黙に変換しない。
            found = False
            for feed_url, entries in mapping.items():
                if any(e.url == url for e in entries):
                    found = True
                    result[feed_url, url] = {"split": "unassigned", "expected": None,
                                             "reason": f"旧注記: {meta}（期待値未確定）", "required": False}
            if not found:
                raise ConfigError("旧注記に対応する記事がありません")
            continue
        if (not isinstance(meta, dict) or "expected" not in meta
                or set(meta) - {"feed_url", "split", "expected", "reason", "required"}):
            raise ConfigError("期待値のメタデータが不正です")
        feed_url = meta.get("feed_url")
        if not isinstance(feed_url, str) or feed_url not in mapping or not any(e.url == url for e in mapping[feed_url]):
            raise ConfigError("期待値に対応するフィード・記事がありません")
        expected = meta.get("expected")
        if meta.get("split") not in ("tuning", "validation") or not isinstance(meta.get("reason"), str) or not meta["reason"].strip():
            raise ConfigError("期待値にはsplit(tuning/validation)と根拠reasonが必要です")
        if type(meta.get("required", False)) is not bool:
            raise ConfigError("requiredは真偽値にしてください")
        if expected is not None:
            if not isinstance(expected, dict) or set(expected) - {"status", "category", "release_counts"}:
                raise ConfigError("expectedのフィールドが不正です")
            if expected.get("status") not in ("adopted", "rejected"):
                raise ConfigError("expected.statusはadopted/rejectedにしてください")
            if "category" in expected and (not isinstance(expected["category"], str) or not expected["category"].strip()):
                raise ConfigError("expected.categoryは空でない文字列にしてください")
            if "release_counts" in expected:
                counts = expected["release_counts"]
                if (not isinstance(counts, dict) or not counts or set(counts) - set(selection.KINDS)
                        or any(type(n) is not int or n < 0 for n in counts.values())):
                    raise ConfigError("release_countsは既知種別から非負整数へのマッピングにしてください")
        elif meta.get("required"):
            raise ConfigError("要確認の例をrequiredにできません")
        result[feed_url, url] = {**meta, "required": meta.get("required", False)}
    return result


def assess(config: collect.Config, decisions: dict, mapping: dict, expectations: dict) -> dict:
    """選定式を再実装せず、通常と同じ分類関数・判断記録を期待値と照合する。"""
    modes = {f.url: f.select for f in config.feeds}
    rows = {}
    for feed_url, entries in mapping.items():
        for entry in entries:
            key = feed_url, entry.url
            meta = expectations.get(key, {"split": "unassigned", "expected": None,
                                          "reason": "期待値未指定", "required": False})
            decision = decisions.get(key)
            actual = None
            if decision is not None:
                actual = {"status": decision.status, "category": decision.category, "release_counts": None}
                if modes.get(feed_url) == "release_notes" and decision.status != "skipped":
                    actual["release_counts"] = selection.release_counts(entry.content)
            expected = meta["expected"]
            differences = {}
            if expected is None or (actual is None and not meta["required"]):
                outcome = "pending"
            else:
                for field, value in expected.items():
                    pairs = value.items() if field == "release_counts" else [(None, value)]
                    for kind, wanted in pairs:
                        got = actual.get(field) if actual is not None else None
                        if kind is not None:
                            got = got.get(kind) if isinstance(got, dict) else None
                        if got != wanted:
                            name = f"{field}.{kind}" if kind else field
                            differences[name] = {"expected": wanted, "actual": got}
                outcome = "mismatch" if differences else "match"
            rows[key] = {"title": entry.title, "split": meta["split"], "reason": meta["reason"],
                         "required": meta["required"], "expected": expected, "actual": actual,
                         "result": outcome, "differences": differences,
                         "pending_reason": ("期待値未確定" if expected is None else "設定にフィードがない") if outcome == "pending" else ""}
    return rows


def print_assessment(assessments: list[dict]) -> None:
    for label, rows in zip(("current", "candidate"), assessments):
        for split in ("all", *sorted({row["split"] for row in rows.values()})):
            subset = [row for row in rows.values() if split == "all" or row["split"] == split]
            counts = {result: sum(row["result"] == result for row in subset) for result in ("match", "mismatch", "pending")}
            required_failed = sum(row["required"] and row["result"] != "match" for row in subset)
            undecided = sum(row["expected"] is None for row in subset)
            not_configured = sum(row["result"] == "pending" and row["expected"] is not None for row in subset)
            print(f"QUALITY {label} {split}: confirmed={counts['match'] + counts['mismatch']} "
                  f"match={counts['match']} mismatch={counts['mismatch']} pending={counts['pending']} "
                  f"required_failed={required_failed} undecided={undecided} not_configured={not_configured}")
    for key, before in sorted(assessments[0].items()):
        row = {"quality": True, "feed_url": key[0], "url": key[1], "current": before}
        if len(assessments) == 2:
            after = assessments[1][key]
            row["candidate"] = after
            if "pending" in (before["result"], after["result"]):
                change = "pending"
            else:
                old, new = set(before["differences"]), set(after["differences"])
                change = "mixed" if new - old and old - new else "regressed" if new - old else "improved" if old - new else "unchanged"
            row["change"] = change
        print(json.dumps(row, ensure_ascii=False))


def preview(config_path: Path, compare_path: Path | None, fixtures_path: Path,
            seen_path: Path | None = None, reconsider_excluded: bool = False, *,
            evaluate: bool = False, check_quality: bool = False) -> int:
    try:
        configs = [collect.load_config(p) for p in [config_path, *([compare_path] if compare_path else [])]]
        today, mapping, seen = load_fixture(fixtures_path)
        if seen_path is not None:
            seen = collect.load_seen(seen_path)
        expectations = load_expectations(fixtures_path, mapping) if evaluate or check_quality else None
        if check_quality and not any(meta["required"] for meta in expectations.values()):
            raise ConfigError("--check-qualityにはrequiredの確定例が最低1件必要です")
        # 片方だけに追加された情報源も含め、必要な入力を全て検証してから選定する。
        for config in configs:
            for feed in config.feeds:
                if feed.url not in mapping:
                    raise ConfigError(f"fixturesにフィードがありません: {feed.url}（0件なら[]を明示）")
        evaluations = []
        for config in configs:
            decisions = {}
            with redirect_stdout(io.StringIO()):
                items, _, stats = collect.collect_feeds(
                    config, seen, today, reconsider_excluded, entry_source=mapping.__getitem__, decisions=decisions)
            if stats.failed_feeds:
                raise ConfigError("fixturesの選定処理に失敗しました: " + ", ".join(stats.failed_feeds))
            evaluations.append((decisions, len(items)))
        assessments = [assess(config, result[0], mapping, expectations) for config, result in zip(configs, evaluations)] if expectations is not None else []
    except (ConfigError, OSError, ValueError, TypeError, KeyError) as e:
        print(f"ERROR: dry-run: {e}", file=sys.stderr)
        return 2

    print(f"DRY-RUN offline: today={today}; reconsider_excluded={reconsider_excluded}; Brave/API=disabled; writes=0")
    print("score=nullはscore方式以外・事前スキップ。age/title/max_itemsは公開日・タイトル除外・フィード上限の事前スキップ。")
    labels = ["current", "candidate"]
    for label, (decisions, cards) in zip(labels, evaluations):
        print(f"{label}: articles={len(decisions)} adopted={sum(d.status == 'adopted' for d in decisions.values())} "
              f"rejected={sum(d.status == 'rejected' for d in decisions.values())} "
              f"skipped={sum(d.status == 'skipped' for d in decisions.values())} cards={cards}")
    left = evaluations[0][0]
    right = evaluations[-1][0]
    changed = 0
    # JSON Linesで改行・制御文字もエスケープし、本文・説明文・APIキーは出力しない。
    for key in sorted(left.keys() | right.keys()):
        before = asdict(left[key]) if key in left else None
        after = asdict(right[key]) if key in right else None
        different = before != after
        changed += different
        print(json.dumps({"feed_url": key[0], "url": key[1], "changed": different,
                          "current": before, **({"candidate": after} if compare_path else {})}, ensure_ascii=False))
    if compare_path:
        print(f"changed articles: {changed}（未設定フィードの記事はnull、同じURLでもフィード別に比較）")
    if assessments:
        print_assessment(assessments)
        if check_quality:
            failed = sum(row["required"] and row["result"] != "match" for row in assessments[-1].values())
            print(f"QUALITY CHECK {'candidate' if compare_path else 'current'}: {'FAIL' if failed else 'PASS'}; required_failed={failed}")
            return 3 if failed else 0
    return 0
