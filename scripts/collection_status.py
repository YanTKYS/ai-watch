"""公開用の収集・インデックス生成状態。本文・診断・秘密値は受け取らず、既知の項目だけ保存する。"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

from common import JST

ROOT = Path(__file__).resolve().parent.parent


def timestamp() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def valid_time(value) -> str | None:
    if isinstance(value, str):
        try:
            if datetime.fromisoformat(value).utcoffset() is not None:
                return value
        except ValueError:
            pass
    return None


def run_key() -> str | None:
    # 公開されているActionsの実行番号だけを関連付けに使用する。
    value = f"{os.environ.get('GITHUB_RUN_ID', '')}:{os.environ.get('GITHUB_RUN_ATTEMPT', '')}"
    return value if re.fullmatch(r"\d+:\d+", value) else None


def load(path: Path) -> dict:
    empty = {"schema_version": 1, "collection": None, "index": None}
    if not path.exists():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
            return empty
        for section, keys in {
            "collection": ("attempted_at", "completed_at", "last_all_success_at", "result", "new_articles", "feeds", "run_key"),
            "index": ("checked_at", "last_success_at", "result", "for_collection"),
        }.items():
            if isinstance(raw.get(section), dict):
                empty[section] = {k: raw[section].get(k) for k in keys}
        c = empty["collection"]
        if c is not None:
            valid = (c["result"] in ("success", "partial", "failed", "running", "error", "unknown")
                     and all(c[k] is None or valid_time(c[k]) for k in ("attempted_at", "completed_at", "last_all_success_at"))
                     and (c["new_articles"] is None or type(c["new_articles"]) is int and c["new_articles"] >= 0)
                     and isinstance(c["feeds"], list))
            if valid:
                clean_feeds = []
                for f in c["feeds"]:
                    if (not isinstance(f, dict) or not isinstance(f.get("name"), str)
                            or f.get("status") not in ("success", "failed")
                            or not all(f.get(k) is None or type(f[k]) is int and f[k] >= 0 for k in ("candidates", "adopted"))):
                        valid = False
                        break
                    clean_feeds.append({k: f.get(k) for k in ("name", "status", "candidates", "adopted")})
                c["feeds"] = clean_feeds
            if valid and c["result"] in ("success", "partial", "failed"):
                failures = sum(f["status"] == "failed" for f in c["feeds"])
                valid = bool(c["feeds"] and valid_time(c["attempted_at"]) and valid_time(c["completed_at"])
                             and type(c["new_articles"]) is int
                             and (failures == 0 if c["result"] == "success" else failures == len(c["feeds"])
                                  if c["result"] == "failed" else 0 < failures < len(c["feeds"])))
            if not valid:
                empty["collection"] = None
            elif not isinstance(c["run_key"], str) or not re.fullmatch(r"\d+:\d+", c["run_key"]):
                c["run_key"] = None
        i = empty["index"]
        if i is not None and (i["result"] not in ("success", "failed", "skipped") or not valid_time(i["checked_at"])
                              or any(i[k] is not None and not valid_time(i[k]) for k in ("last_success_at", "for_collection"))):
            empty["index"] = None
        return empty
    except (ValueError, UnicodeError):
        # 旧/破損状態から成功日時を推定しない。読み取りI/O障害は隠さない。
        return empty


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def begin(path: Path, attempted_at: str) -> None:
    state = load(path)
    previous = state["collection"] or {}
    state["collection"] = {"attempted_at": attempted_at, "completed_at": None,
                           "last_all_success_at": valid_time(previous.get("last_all_success_at")),
                           "result": "running", "new_articles": None, "feeds": [], "run_key": run_key()}
    save(path, state)


def finish(path: Path, attempted_at: str | None, result: str, feeds: list[dict], new_articles: int | None) -> None:
    state = load(path)
    previous = state["collection"] or {}
    completed_at = timestamp()
    state["collection"] = {
        "attempted_at": attempted_at, "completed_at": completed_at,
        "last_all_success_at": completed_at if result == "success" else valid_time(previous.get("last_all_success_at")),
        "result": result, "new_articles": new_articles,
        "feeds": [{key: f[key] for key in ("name", "status", "candidates", "adopted")} for f in feeds],
        "run_key": run_key(),
    }
    save(path, state)


def finalize(path: Path, collect_result: str, index_result: str) -> None:
    state = load(path)
    collection = state["collection"] or {}
    # import失敗・CLI実行前の障害・途中終了でも、前回の正常を今回の結果としない。
    if (not collection or collection.get("result") == "running"
            or (run_key() is not None and collection.get("run_key") != run_key())):
        attempted_at = collection.get("attempted_at") if collection.get("run_key") == run_key() else None
        finish(path, attempted_at, "error" if collect_result == "failure" else "unknown", [], None)
        state = load(path)
    now = timestamp()
    old_index = state["index"] or {}
    state["index"] = {"checked_at": now, "result": {"success": "success", "failure": "failed"}.get(index_result, "skipped"),
                      "last_success_at": now if index_result == "success" else valid_time(old_index.get("last_success_at")),
                      "for_collection": state["collection"]["attempted_at"]}
    save(path, state)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=ROOT / "data/collection-status.json")
    parser.add_argument("--collect-result", required=True, choices=("success", "failure", "skipped", "cancelled"))
    parser.add_argument("--index-result", required=True, choices=("success", "failure", "skipped", "cancelled"))
    args = parser.parse_args(argv)
    finalize(args.path, args.collect_result, args.index_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
