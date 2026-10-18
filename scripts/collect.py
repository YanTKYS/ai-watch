#!/usr/bin/env python3
"""生成AI関連の新着情報を日刊で収集し、月単位のMarkdownログへ追記する（news-watch の collect.py を流用）。

1. 公式フィード（RSS / Atom・GitHub Releases）: タイトル・URL・公開日を logs/ と data/seen.json に保存する。
2. Brave Search API（X検索・一般Web検索）: 利用規約上、検索結果は保存しない。取得品質の件数だけを
   data/brave-usage.json と Actionsログに残す（brave.py）。1日最大4リクエスト・1日1回。

- APIキーは環境変数 BRAVE_API_KEY からのみ取得する（出力・保存しない）。未設定ならBrave検索だけを飛ばす。
- ログを書き終えてからBrave検索を行うため、APIが失敗しても日刊ログ・閲覧機能には影響しない。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

import brave
import feeds
import selection
from common import JST, ConfigError, compile_terms, domain_of, matches_any

ROOT = Path(__file__).resolve().parent.parent
SAME_TITLE_WINDOW_DAYS = 7


@dataclass
class Category:
    id: str
    name: str
    terms: list[re.Pattern]


@dataclass
class Config:
    categories: list[Category]
    classify_order: list[str]
    feeds: list[feeds.Feed]
    max_age_days: int
    brave: brave.BraveConfig
    selection: selection.Selection = field(default_factory=selection.Selection)

    def category(self, cid: str) -> Category:
        return next(c for c in self.categories if c.id == cid)


@dataclass
class Item:
    url: str
    title: str
    category: str  # カテゴリ名（ログの見出し）
    feed: str
    published: str
    notes: str = ""  # リリースの項目数（機械的な集計）。リリースノートの文章は保存しない
    grouped_urls: list[str] = field(default_factory=list)  # 1件にまとめた他のリリースのURL（seen.json に記録）


@dataclass
class Stats:
    feeds: int = 0
    feed_requests: int = 0
    failed_feeds: list[str] = field(default_factory=list)
    entries: int = 0
    skipped_old_or_excluded: int = 0
    skipped_unmatched: int = 0
    duplicate_items: int = 0
    rejected: Counter = field(default_factory=Counter)  # 選定で採用しなかった理由 -> 件数
    new_items: int = 0
    same_title: int = 0


# ---- 設定 ---------------------------------------------------------------
def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"設定ファイルを読み込めません: {path} ({type(e).__name__})") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("categories"), list) or not raw["categories"]:
        raise ConfigError("設定ファイルの形式が不正です: 'categories' のリストが必要です")

    categories: list[Category] = []
    for c in raw["categories"]:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not isinstance(c.get("name"), str) \
                or not c["id"].strip() or not c["name"].strip():
            raise ConfigError("各カテゴリに文字列の 'id' と 'name' が必要です")
        if any(x.id == c["id"] or x.name == c["name"].strip() for x in categories):
            raise ConfigError(f"カテゴリの id / name が重複しています: {c['id']}")
        categories.append(Category(id=c["id"], name=" ".join(c["name"].split()),
                                   terms=compile_terms(c.get("keywords", []), f"categories.{c['id']}.keywords")))
    ids = {c.id for c in categories}

    order = raw.get("classify_order", [c.id for c in categories])
    if not isinstance(order, list) or len(set(order)) != len(order) or not set(order) <= ids:
        raise ConfigError("classify_order は categories の id のリスト（重複なし）にしてください")
    order += [c.id for c in categories if c.id not in order]

    max_age = raw.get("max_age_days", feeds.DEFAULT_MAX_AGE_DAYS)
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not 1 <= max_age <= 31:
        raise ConfigError(f"max_age_days は 1〜31 の整数にしてください: {max_age!r}")

    return Config(categories=categories, classify_order=order, feeds=feeds.load_feeds(raw.get("feeds"), ids),
                  max_age_days=max_age, brave=brave.load_brave(raw.get("brave"), raw.get("quality"), ids),
                  selection=selection.load_selection(raw.get("selection")))


def classify(config: Config, title: str) -> str | None:
    """タイトルが最初に該当したカテゴリの id（classify_order の順）。該当なしは None。"""
    for cid in config.classify_order:
        if matches_any(title, config.category(cid).terms):
            return cid
    return None


# ---- 永続化（news-watch から流用） ---------------------------------------------
def load_seen(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"seen.json を読み込めません: {path} ({type(e).__name__})") from e
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise ConfigError(f"seen.json の形式が不正です: {path}")
    return data


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def render_entry(item: Item, today: str) -> list[str]:
    return [
        f"#### {item.title}",
        "",
        f"- URL: {item.url}",
        f"- Source: {domain_of(item.url)}",
        f"- Feed: {item.feed}",
        *([f"- Notes: {item.notes}"] if item.notes else []),
        f"- Published: {item.published}",
        f"- Retrieved: {today}",
    ]


def _insert(lines: list[str], pos: int, new: list[str]) -> None:
    """posの直前の空行を除いた位置へ、空行区切りで new を挿入する。"""
    while pos > 0 and lines[pos - 1].strip() == "":
        pos -= 1
    lines[pos:pos] = ["", *new]


def add_entry(lines: list[str], today: str, category: str, block: list[str]) -> None:
    """月次ログ(行リスト)へ 日付 > カテゴリ の見出し配下に記事を追記する。"""
    date_h, cat_h = f"## {today}", f"### {category}"
    if date_h not in lines:
        _insert(lines, len(lines), [date_h, "", cat_h, "", *block])
        return
    start = lines.index(date_h) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    cat_at = next((i for i in range(start, end) if lines[i] == cat_h), None)
    if cat_at is None:
        _insert(lines, end, [cat_h, "", *block])
        return
    cat_end = next((i for i in range(cat_at + 1, end) if lines[i].startswith("### ")), end)
    _insert(lines, cat_end, block)


def write_log(logs_dir: Path, today: str, items: list[Item]) -> Path:
    year, month = today[:4], today[5:7]
    path = logs_dir / year / f"{year}-{month}.md"
    if path.exists():
        lines = path.read_text(encoding="utf-8").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
    else:
        lines = [f"# {year}年{int(month)}月"]
    for item in items:
        add_entry(lines, today, item.category, render_entry(item, today))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


_MONTH_FILE_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])\.md$")


def list_months(logs_dir: Path) -> list[str]:
    """logs/YYYY/YYYY-MM.md を走査し、閲覧UI用の月一覧（YYYY-MM・新しい順・重複なし）を返す。"""
    months = set()
    for path in logs_dir.glob("*/*.md"):
        m = _MONTH_FILE_RE.match(path.name)
        if m and path.parent.name == m.group(1):  # 年ディレクトリとファイル名の年が一致するもののみ
            months.add(f"{m.group(1)}-{m.group(2)}")
    return sorted(months, reverse=True)


def update_months(months_path: Path, logs_dir: Path) -> bool:
    """months.json を生成・更新する。内容が変わらなければ書き込まない。変更したら True。"""
    new = json.dumps(list_months(logs_dir), ensure_ascii=False, indent=2) + "\n"
    if months_path.exists() and months_path.read_text(encoding="utf-8") == new:
        return False
    months_path.parent.mkdir(parents=True, exist_ok=True)
    months_path.write_text(new, encoding="utf-8")
    return True


# ---- 公式フィード ------------------------------------------------------------
def _item(config: Config, feed: feeds.Feed, e: feeds.Entry) -> Item:
    cid = (classify(config, e.title) if feed.classify else None) or feed.category
    return Item(url=e.url, title=feeds.display_title(feed, e.title), category=config.category(cid).name,
                feed=feed.name, published=e.published)


def choose(config: Config, feed: feeds.Feed, entries: list[feeds.Entry]) -> tuple[list[Item], dict[str, str]]:
    """フィードの設定（select）に従って採用する記事を選ぶ。戻り値は (採用, 不採用URL -> 理由)。

    判定の内訳はActionsログに1記事1行で出す（公式フィードのタイトルのみ。本文は出さない）。
    """
    sel = config.selection
    adopted: list[tuple[int, feeds.Entry, str]] = []  # (点数, 記事, 備考)
    rejected: dict[str, str] = {}

    def reject(e: feeds.Entry, reason: str, detail: str) -> None:
        rejected[e.url] = reason
        print(f"  - rejected [{reason}] {detail}: {e.title}")

    for e in entries:
        if feed.select == "score":
            points, matched = selection.score(sel, e.title, e.summary, e.categories)
            detail = f"score={points} ({selection.describe(matched)})"
            if points >= sel.min_score:
                adopted.append((points, e, detail))
            else:
                reject(e, selection.rejection_reason(matched), detail)
        elif feed.select == "release_notes":
            counts = selection.release_counts(e.content)
            verdict = selection.release_verdict(counts)
            detail = f"{verdict} ({selection.format_counts(counts)}, その他 {counts['other']})"
            if verdict == "minor":
                reject(e, "fixes_only", detail)  # 修正・雑務のみのリリース
            else:
                adopted.append((1, e, detail))
        else:
            adopted.append((0, e, "select=all"))

    adopted.sort(key=lambda x: (x[0], x[1].published), reverse=True)
    if feed.select != "release_notes":  # リリースは下で1件にまとめるため上限の対象外
        for points, e, detail in adopted[sel.max_new_per_feed:]:
            reject(e, "over_limit", detail)  # 1回の収集で1フィードから採用する件数の上限
        adopted = adopted[:sel.max_new_per_feed]
    for _, e, detail in adopted:
        print(f"  + adopted {detail}: {e.title}")
    if feed.select != "release_notes" or not adopted:
        return [_item(config, feed, e) for _, e, _ in adopted], rejected

    # 同じ収集で採用したリリースは1件にまとめる（最新のリリースにリンクし、項目数を合算して添える）
    releases = sorted((e for _, e, _ in adopted), key=lambda e: e.published, reverse=True)
    item = _item(config, feed, releases[0])
    if len(releases) > 1:
        item.title = f"{item.title}（{releases[-1].title} 以降の {len(releases)} リリース）"
    totals = Counter()
    unknown = 0
    for e in releases:
        counts = selection.release_counts(e.content)
        if selection.release_verdict(counts) == "unknown":
            unknown += 1
        totals.update(counts)
    if unknown < len(releases):
        item.notes = selection.format_counts(totals)
        if unknown:
            item.notes += f"（{unknown} リリースは項目を判定できず）"
    item.grouped_urls = [e.url for e in releases[1:]]
    return [item], rejected


def collect_feeds(config: Config, seen: dict[str, dict], today: str) -> tuple[list[Item], dict[str, str], Stats]:
    """戻り値は (採用した記事, 不採用URL -> 理由, 統計)。不採用URLは seen.json に記録して復活させない。"""
    stats = Stats(feeds=len(config.feeds))
    new_items: dict[str, Item] = {}
    rejected: dict[str, str] = {}
    for feed in config.feeds:
        stats.feed_requests += 1
        info, body = feeds.FetchInfo(), b""
        try:
            body = feeds.fetch(feed.url, info)
            body = feeds.decode_body(body, info)  # 展開に失敗した場合、診断には受信データの先頭形式を出す
            entries = feeds.parse_feed(body)
        except Exception as e:  # 1件の失敗で全体を止めない。本文全体は出力せず、切り分け用の診断情報だけを出す。
            stats.failed_feeds.append(feed.name)
            print(f"::warning::feed failed: feed='{feed.name}' error={feeds.describe_error(e)}")
            print(f"  diagnostics: {feeds.diagnose(info, body, e)}")
            continue
        print(f"feed ok: feed='{feed.name}' status={info.status} content_type={json.dumps(info.content_type)} "
              f"content_encoding={json.dumps(info.content_encoding)} bytes={info.size} "
              f"decoded_bytes={info.decoded_size} entries={len(entries)}")
        stats.entries += len(entries)
        selected = feeds.select_entries(feed, entries, today, config.max_age_days)
        stats.skipped_old_or_excluded += len(entries) - len(selected)
        candidates = []
        for e in selected:
            if feed.require_terms and not matches_any(e.title, feed.require_terms):
                stats.skipped_unmatched += 1  # 生成AIと関係の薄い記事（GitHub Changelog など）
                continue
            if e.url in seen or e.url in new_items or e.url in rejected:
                stats.duplicate_items += 1
                continue
            candidates.append(e)
        if not candidates:
            continue
        cats = Counter(c for e in candidates for c in e.categories)
        print(f"selection: feed='{feed.name}' select={feed.select} candidates={len(candidates)}"
              + (f" categories={dict(cats.most_common(10))}" if cats else ""))
        chosen, feed_rejected = choose(config, feed, candidates)
        for item in chosen:
            new_items[item.url] = item
        rejected.update(feed_rejected)
        stats.rejected.update(feed_rejected.values())
    order = {c.name: i for i, c in enumerate(config.categories)}  # ログ内のカテゴリを設定の順に並べる
    items = sorted(new_items.values(), key=lambda i: order[i.category])
    stats.new_items = len(items)
    return items, rejected, stats


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.casefold())


def recent_titles(logs_dir: Path, today: str) -> set[str]:
    """直近 SAME_TITLE_WINDOW_DAYS 日の記録済みタイトル（正規化後）。同一話題の観測用。"""
    oldest = (date.fromisoformat(today) - timedelta(days=SAME_TITLE_WINDOW_DAYS)).isoformat()
    titles = set()
    for ym in {today[:7], oldest[:7]}:
        path = logs_dir / ym[:4] / f"{ym}.md"
        if not path.exists():
            continue
        day = ""
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.startswith("## "):
                day = line[3:].strip()
            elif line.startswith("#### ") and oldest <= day <= today:
                titles.add(normalize_title(line[5:]))
    return titles


def count_same_titles(items: list[Item], logs_dir: Path, today: str) -> int:
    """URLが異なるが正規化後のタイトルが同じ記事の数（観測のみ。保存には影響させない）。"""
    try:
        known = recent_titles(logs_dir, today)
    except (OSError, UnicodeDecodeError, ValueError):
        return 0
    count = 0
    for item in items:
        key = normalize_title(item.title)
        count += key in known
        known.add(key)
    return count


# ---- メイン処理 ----------------------------------------------------------
def print_stats(s: Stats) -> None:
    print(f"feeds: {s.feeds}")
    print(f"feed requests: {s.feed_requests}")
    print(f"failed feeds: {len(s.failed_feeds)}" + (f" ({', '.join(s.failed_feeds)})" if s.failed_feeds else ""))
    print(f"feed entries: {s.entries}")
    print(f"skipped (old / excluded): {s.skipped_old_or_excluded}")
    print(f"skipped (require_keywords): {s.skipped_unmatched}")
    print(f"duplicate items: {s.duplicate_items}")
    print(f"rejected by selection: {sum(s.rejected.values())}"
          + (f" ({', '.join(f'{k}={v}' for k, v in s.rejected.most_common())})" if s.rejected else ""))
    print(f"same-title items (observation only): {s.same_title}")
    print(f"new items: {s.new_items}")


def run(
    config_path: Path = ROOT / "config" / "sources.yml",
    seen_path: Path = ROOT / "data" / "seen.json",
    logs_dir: Path = ROOT / "logs",
    months_path: Path = ROOT / "data" / "months.json",
    usage_path: Path = ROOT / "data" / "brave-usage.json",
    today: str | None = None,
    env: dict | None = None,
    skip_brave: bool = False,
    sleep=time.sleep,
) -> int:
    env = os.environ if env is None else env
    today = today or datetime.now(JST).date().isoformat()
    try:
        config = load_config(config_path)
        seen = load_seen(seen_path)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # 1. 公式フィード（保存する）
    items, rejected, stats = collect_feeds(config, seen, today)
    stats.same_title = count_same_titles(items, logs_dir, today)
    if items:
        write_log(logs_dir, today, items)  # ログ→seenの順（途中失敗時に記事を取りこぼさない）
    if items or rejected:
        for item in items:
            seen[item.url] = {"first_seen": today}
            for url in item.grouped_urls:
                seen[url] = {"first_seen": today, "grouped_into": item.url}
        for url, reason in rejected.items():  # 不採用の記事も記録し、次回以降に復活させない
            seen[url] = {"first_seen": today, "excluded": reason}
        save_json(seen_path, seen)
    update_months(months_path, logs_dir)
    print_stats(stats)

    # 2. Brave検索（保存しない。品質の件数のみ記録）
    probe = None
    if skip_brave:
        print("Brave status: skipped (--skip-brave)")
    else:
        try:
            usage = brave.load_usage(usage_path)
        except (OSError, ValueError) as e:
            print(f"::warning::brave-usage.json is unreadable; Brave search is skipped: error={type(e).__name__}")
            usage = None
        api_key = (env.get("BRAVE_API_KEY") or "").strip()
        terms = {c.id: c.terms for c in config.categories}
        probe = brave.run_probe(config.brave, api_key, usage, today, terms, set(seen),
                                persist=lambda u: brave.save_usage(usage_path, u, today), sleep=sleep)
        if probe.status == "no_api_key":
            print("::warning::BRAVE_API_KEY is not configured; Brave search is skipped.")
        print("\n".join(brave.format_result(probe)))
        if usage:
            print("\n".join(brave.summarize(usage, today)))

    attempted = stats.feed_requests + (probe.requests if probe else 0)
    failed = len(stats.failed_feeds) + (probe.failed if probe else 0)
    if attempted and failed == attempted:
        print("ERROR: すべての取得が失敗しました。", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai-watch 日刊収集")
    parser.add_argument("--skip-brave", action="store_true", help="Brave検索を行わない（公式フィードのみ）")
    args = parser.parse_args(argv)
    return run(skip_brave=args.skip_brave)


if __name__ == "__main__":
    sys.exit(main())
