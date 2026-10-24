#!/usr/bin/env python3
"""設定・保存済みログ・seenから情報源一覧をMarkdownで標準出力する。通信・書き込みは行わない。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import collect
import search_index
from common import ConfigError

ROOT = Path(__file__).resolve().parent.parent


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def inferred_feed(url: str, config: collect.Config) -> str | None:
    """除外URLの出所を推定。GitHubはリポジトリ、ニュースは一意のホストのみ。

    seenにはFeedがないため確定値ではない。曖昧な場合は未帰属とし、URLは出力しない。
    """
    try:
        target = urlsplit(url)
        matches = []
        for feed in config.feeds:
            source = urlsplit(feed.url)
            if target.hostname != source.hostname:
                continue
            if source.hostname == "github.com":
                if not source.path.endswith("/releases.atom"):
                    continue
                prefix = source.path.removesuffix(".atom") + "/tag/"
                if not target.path.startswith(prefix):
                    continue
            matches.append(feed.name)
        return matches[0] if len(matches) == 1 else None
    except ValueError:
        return None


def report(config: collect.Config, logs_dir: Path, seen_path: Path, since: str, until: str) -> str:
    articles = [a for a in search_index.build_index(logs_dir) if since <= a["retrieved"] <= until]
    seen = collect.load_seen(seen_path)
    counts = Counter(a["feed"] for a in articles)
    # 集約先が対象期間の記事であるURLだけを数える。先頭リリースはカード数に含む。
    by_url = {a["url"]: a["feed"] for a in articles}
    grouped = Counter(by_url[v["grouped_into"]] for v in seen.values() if v.get("grouped_into") in by_url)
    rejected = Counter()
    reasons = Counter()
    for url, record in seen.items():
        if "excluded" in record and since <= record.get("first_seen", "") <= until:
            rejected[inferred_feed(url, config)] += 1
            reasons[record["excluded"]] += 1
    rows = [
        "# 情報源一覧（生成物）", "",
        f"対象: {since}〜{until}（記事は取得日、除外URLはfirst_seen基準）。", "",
        "`scripts/source_report.py` により現行設定・Markdownログ・seenから生成。手編集しない。",
        "公式性・有用性・到達性の評価は [source-quality.md](source-quality.md) を参照。", "",
        "| 情報源 / 設定URL | 既定カテゴリ / タイトルによる再分類 | 選定 / タイトル必須語 / プレリリース等除外 | 保存記事 | 集約内の追加URL | 除外URL（推定） | 最新取得記事日 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for feed in config.feeds:
        dates = [a["retrieved"] for a in articles if a["feed"] == feed.name]
        row = [f"{feed.name} ({feed.url})", f"{config.category(feed.category).name} / {'あり' if feed.classify else 'なし'}",
               f"{feed.select} / {'あり' if feed.require_terms else 'なし'} / {'あり' if feed.exclude_title_patterns else 'なし'}",
               counts[feed.name], grouped[feed.name], rejected[feed.name], max(dates, default="—")]
        rows.append("| " + " | ".join(cell(v) for v in row) + " |")
    known = {f.name for f in config.feeds}
    rows += ["", f"保存記事合計: {len(articles)}件。うち現行設定にないFeed: {sum(n for f, n in counts.items() if f not in known)}件。",
             f"除外URL合計: {sum(reasons.values())}件（未帰属: {rejected[None]}件）。", "",
             "| 保存された除外理由 | URL数 |", "| --- | ---: |"]
    rows += [f"| {cell(reason)} | {n} |" for reason, n in sorted(reasons.items())]
    rows += ["", "## 数値の読み方", "",
             "- 保存記事はURL重複排除後のカード数。集約内の追加URLはseenのgrouped_intoで対応付ける。合計はリリースの全変更項目数ではない。",
             "- 除外はseenに残るURLの状態で、採否試行回数ではない。first_seenは最終除外日ではなく、再評価で状態が変わり得る。",
             "- 除外のFeedは保存されていない。GitHubは設定内のリポジトリのreleases/tag/、その他は設定内で一意の同一ホストから推定。複数候補は未帰属。設定変更で推定は変わる。",
             "- 年齢・必須語・プレリリース・重複による事前除外、over_limitはこの除外数に含まれない。分母がないため採用率は算出しない。",
             "- 最新取得記事日は最終フィード取得成功日ではない。0記事は取得失敗を意味しない。取得成否はActionsのfeed ok/failedログで別途確認する。", ""]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=date.fromisoformat)
    parser.add_argument("--until", required=True, type=date.fromisoformat)
    parser.add_argument("--config", type=Path, default=ROOT / "config/sources.yml")
    parser.add_argument("--logs", type=Path, default=ROOT / "logs")
    parser.add_argument("--seen", type=Path, default=ROOT / "data/seen.json")
    args = parser.parse_args(argv)
    if args.since > args.until:
        parser.error("--since must not be after --until")
    try:
        text = report(collect.load_config(args.config), args.logs, args.seen, args.since.isoformat(), args.until.isoformat())
    except (ConfigError, OSError, ValueError) as e:
        parser.exit(1, f"source report failed: {e}\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
