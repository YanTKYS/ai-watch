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


def preview(config_path: Path, compare_path: Path | None, fixtures_path: Path,
            seen_path: Path | None = None, reconsider_excluded: bool = False) -> int:
    try:
        configs = [collect.load_config(p) for p in [config_path, *([compare_path] if compare_path else [])]]
        today, mapping, seen = load_fixture(fixtures_path)
        if seen_path is not None:
            seen = collect.load_seen(seen_path)
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
    return 0
