"""Offline comparison of validated procurement snapshots. No network calls."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from baseline import (
    JST, MEANINGFUL_FIELDS, PROJECT_ROOT, SOURCE_URL, atomic_json,
    digest, is_case_url, normalize_text, normalize_url,
)

RUN_ERRORS = {"FETCH_ERROR", "STRUCTURE_ERROR", "VALIDATION_ERROR"}
RECORD_STATUSES = (
    "UNCHANGED", "NEW", "UPDATED", "NOT_LISTED",
    "DUPLICATE", "MISSING", "AMBIGUOUS_IDENTITY",
)
GOOD_RESULTS = {"PASS", "PASS_WITH_WARN"}
REQUIRED_RECORD_FIELDS = {
    "source_agency", "procurement_category", "title", "posted_date_raw",
    "posted_date", "updated_date_raw", "updated_date", "procurement_number",
    "notice_type", "detail_url", "source_page_url", "fetched_at",
    "stable_key", "key_strategy", "content_hash",
}


def identity_for(row: dict) -> tuple[str, str]:
    """Generate the cross-snapshot identity independently of stable_key."""
    agency = normalize_text(row.get("source_agency"))
    category = normalize_text(row.get("procurement_category"))
    title = normalize_text(row.get("title"))
    posted = row.get("posted_date")
    number = row.get("procurement_number")
    if not all((agency, category, title, posted)):
        raise ValueError("Identity requires agency, category, title and posted date.")
    if number is not None:
        if not isinstance(number, str) or not number.isdigit():
            raise ValueError("Procurement number must be a digit string.")
        return "procurement_number:" + digest([agency, number]), "procurement_number"
    url = row.get("detail_url")
    if isinstance(url, str) and is_case_url(url):
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.netloc:
            return "detail_url:" + digest([normalize_url(url)]), "detail_url"
    return "category_title_posted_date:" + digest([category, title, posted]), "category_title_posted_date"


def content_hash_for(row: dict) -> str:
    content = {field: row.get(field) for field in MEANINGFUL_FIELDS}
    content["detail_url"] = normalize_url(content["detail_url"])
    return digest(content)


def is_substantive_duplicate(left: dict, right: dict) -> bool:
    """True only for semantically identical rows on the same source listing."""
    fields = (*MEANINGFUL_FIELDS, "source_page_url")
    for field in fields:
        a, b = left.get(field), right.get(field)
        if field == "detail_url":
            a, b = normalize_url(a), normalize_url(b)
        elif field in ("title", "notice_type", "source_agency", "procurement_category"):
            a, b = normalize_text(a), normalize_text(b)
        if a != b:
            return False
    return True


def _required_missing(row: dict) -> list[str]:
    missing = []
    for field in ("source_agency", "procurement_category", "title", "posted_date"):
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def inspect_snapshot(snapshot: object, *, side: str) -> tuple[str | None, list[dict], list[str]]:
    """Check the stored PASS flag and independently check records before comparison."""
    if not isinstance(snapshot, dict):
        return "STRUCTURE_ERROR", [], [f"{side}: snapshot is not an object."]
    if snapshot.get("snapshot_type") not in ("BASELINE", "SNAPSHOT"):
        return "STRUCTURE_ERROR", [], [f"{side}: unrecognized snapshot type."]
    if snapshot.get("source_page_url") != SOURCE_URL:
        return "STRUCTURE_ERROR", [], [f"{side}: unexpected source page."]
    try:
        fetched_at = datetime.fromisoformat(snapshot["fetched_at"])
        if fetched_at.tzinfo is None:
            raise ValueError("Fetch timestamp lacks a timezone.")
    except (KeyError, TypeError, ValueError):
        return "STRUCTURE_ERROR", [], [f"{side}: invalid fetch timestamp."]
    rows = snapshot.get("records")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return "STRUCTURE_ERROR", [], [f"{side}: records must be an array of objects."]
    problems = []
    missing_events = []
    if not rows:
        problems.append(f"{side}: no records.")
    validation = snapshot.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True or validation.get("result") not in GOOD_RESULTS:
        problems.append(f"{side}: stored validation is not PASS.")
    for index, row in enumerate(rows, start=1):
        missing = _required_missing(row)
        if missing:
            missing_events.append({
                "status": "MISSING", "side": side, "record_index": index,
                "stable_key": row.get("stable_key"), "missing_fields": missing,
            })
            continue
        if not REQUIRED_RECORD_FIELDS <= row.keys():
            problems.append(f"{side}: record schema incomplete at record {index}.")
            continue
        if not all(isinstance(row[field], str) for field in
                   ("source_agency", "procurement_category", "title",
                    "posted_date_raw", "posted_date", "fetched_at", "stable_key")):
            problems.append(f"{side}: required field type invalid at record {index}.")
            continue
        if any(row[field] is not None and not isinstance(row[field], str) for field in
               ("updated_date_raw", "updated_date", "procurement_number",
                "notice_type", "detail_url")):
            problems.append(f"{side}: optional field type invalid at record {index}.")
            continue
        try:
            date.fromisoformat(row["posted_date"])
            if row["updated_date"] is not None:
                date.fromisoformat(row["updated_date"])
            identity_for(row)
        except (TypeError, ValueError):
            problems.append(f"{side}: invalid date or identity at record {index}.")
            continue
        if row.get("source_page_url") != SOURCE_URL:
            problems.append(f"{side}: unexpected record source at record {index}.")
        if not row["stable_key"]:
            problems.append(f"{side}: stable_key missing at record {index}.")
        if row["detail_url"] is not None:
            parts = urlsplit(row["detail_url"])
            if parts.scheme not in ("http", "https") or not parts.netloc:
                problems.append(f"{side}: detail URL invalid at record {index}.")
                continue
        recorded_hash = row.get("content_hash")
        if not isinstance(recorded_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded_hash):
            problems.append(f"{side}: content_hash invalid at record {index}.")
        elif content_hash_for(row) != recorded_hash:
            problems.append(f"{side}: content_hash mismatch at record {index}.")
    if missing_events or problems:
        return "VALIDATION_ERROR", missing_events, problems
    return None, [], []


def _ref(item: tuple[int, dict, str, str]) -> dict:
    index, row, identity_key, strategy = item
    return {
        "record_index": index,
        "stable_key": row["stable_key"],
        "identity_key": identity_key,
        "identity_strategy": strategy,
        "title": row["title"],
        "procurement_number": row["procurement_number"],
        "notice_type": row["notice_type"],
        "posted_date": row["posted_date"],
        "detail_url": row["detail_url"],
        "content_hash": row["content_hash"],
    }


def _event(status: str, key: str | None, previous: list, current: list,
           *, reason: str | None = None, changed_fields: dict | None = None) -> dict:
    strategies = sorted({item[3] for item in [*previous, *current]})
    return {
        "status": status,
        "identity_key": key,
        "identity_strategy": strategies[0] if len(strategies) == 1 else None,
        "identity_strategies": strategies,
        "previous": [_ref(item) for item in previous],
        "current": [_ref(item) for item in current],
        "changed_fields": changed_fields or {},
        "reason": reason,
    }


def _duplicate_clusters(group: list) -> list[list]:
    clusters = []
    used = set()
    for pos, item in enumerate(group):
        if pos in used:
            continue
        cluster = [item]
        for other_pos in range(pos + 1, len(group)):
            if other_pos not in used and is_substantive_duplicate(item[1], group[other_pos][1]):
                cluster.append(group[other_pos])
                used.add(other_pos)
        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters


def _unique_signal_pairs(previous: list, current: list) -> set[tuple[int, int]]:
    """Accept multi-record matches only when independent unique signals agree."""
    getters = (
        lambda row: normalize_url(row.get("detail_url")) if row.get("detail_url") else None,
        lambda row: normalize_text(row.get("notice_type")),
        lambda row: (normalize_text(row.get("title")), row.get("posted_date")),
    )
    edges = set()
    for getter in getters:
        prev_values = defaultdict(list)
        curr_values = defaultdict(list)
        for item in previous:
            value = getter(item[1])
            if value and (not isinstance(value, tuple) or all(value)):
                prev_values[value].append(item[0])
        for item in current:
            value = getter(item[1])
            if value and (not isinstance(value, tuple) or all(value)):
                curr_values[value].append(item[0])
        for value in prev_values.keys() & curr_values.keys():
            if len(prev_values[value]) == len(curr_values[value]) == 1:
                edges.add((prev_values[value][0], curr_values[value][0]))
    return edges


def _corroborated_pair(previous, current) -> bool:
    """A reused number alone is insufficient evidence of the same case."""
    old, new = previous[1], current[1]
    old_url, new_url = old.get("detail_url"), new.get("detail_url")
    if old_url and new_url and is_case_url(old_url) and is_case_url(new_url):
        if normalize_url(old_url) == normalize_url(new_url):
            return True
    return (
        old.get("procurement_category") == new.get("procurement_category")
        and normalize_text(old.get("title")) == normalize_text(new.get("title"))
        and old.get("posted_date") == new.get("posted_date")
    )


def _resolved_pairs(previous: list, current: list) -> list[tuple] | None:
    if len(previous) == len(current) == 1:
        old, new = previous[0], current[0]
        if old[3] == "procurement_number" and not _corroborated_pair(old, new):
            return None
        return [(old, new)]
    if len(previous) != len(current) or not previous:
        return None
    edges = _unique_signal_pairs(previous, current)
    by_prev = defaultdict(set)
    by_curr = defaultdict(set)
    for prev_index, curr_index in edges:
        by_prev[prev_index].add(curr_index)
        by_curr[curr_index].add(prev_index)
    if len(by_prev) != len(previous) or len(by_curr) != len(current):
        return None
    if any(len(values) != 1 for values in [*by_prev.values(), *by_curr.values()]):
        return None
    curr_index = {item[0]: item for item in current}
    pairs = [(item, curr_index[next(iter(by_prev[item[0]]))]) for item in previous]
    return pairs if all(_corroborated_pair(old, new) for old, new in pairs) else None


def _changed_fields(previous: dict, current: dict) -> dict:
    return {
        field: {"before": previous.get(field), "after": current.get(field)}
        for field in MEANINGFUL_FIELDS
        if previous.get(field) != current.get(field)
    }


def _matched_event(previous, current) -> dict:
    old, new = previous[1], current[1]
    if old["content_hash"] == new["content_hash"]:
        return _event("UNCHANGED", previous[2], [previous], [current])
    return _event(
        "UPDATED", previous[2], [previous], [current],
        changed_fields=_changed_fields(old, new),
    )


def _cross_key_signal(left: dict, right: dict) -> bool:
    """Quarantine apparent same cases whose chosen identity strategy changed."""
    left_url, right_url = left.get("detail_url"), right.get("detail_url")
    if left_url and right_url and is_case_url(left_url) and is_case_url(right_url):
        if normalize_url(left_url) == normalize_url(right_url):
            return True
    return (
        left.get("source_agency") == right.get("source_agency")
        and left.get("procurement_category") == right.get("procurement_category")
        and normalize_text(left.get("title")) == normalize_text(right.get("title"))
        and left.get("posted_date") == right.get("posted_date")
    )


def _quarantine_cross_key(previous: list, current: list) -> tuple[list[dict], list, list]:
    """Connected components prevent a cross-key resemblance from becoming NEW+NOT_LISTED."""
    adjacency = defaultdict(set)
    for old in previous:
        for new in current:
            if _cross_key_signal(old[1], new[1]):
                a, b = ("p", old[0]), ("c", new[0])
                adjacency[a].add(b)
                adjacency[b].add(a)
    if not adjacency:
        return [], previous, current
    old_by_index = {item[0]: item for item in previous}
    new_by_index = {item[0]: item for item in current}
    visited = set()
    events = []
    for start in sorted(adjacency):
        if start in visited:
            continue
        stack, component = [start], set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(adjacency[node] - component)
        visited.update(component)
        olds = [old_by_index[index] for side, index in sorted(component) if side == "p"]
        news = [new_by_index[index] for side, index in sorted(component) if side == "c"]
        events.append(_event(
            "AMBIGUOUS_IDENTITY", None, olds, news,
            reason="Similar records have different identity keys; manual review required.",
        ))
    previous = [item for item in previous if ("p", item[0]) not in visited]
    current = [item for item in current if ("c", item[0]) not in visited]
    return events, previous, current


def _summary(previous: object, current: object, events: list[dict]) -> dict:
    counts = Counter(event["status"] for event in events)
    return {
        "total_previous": len(previous["records"]) if isinstance(previous, dict) and isinstance(previous.get("records"), list) else None,
        "total_current": len(current["records"]) if isinstance(current, dict) and isinstance(current.get("records"), list) else None,
        **{status.lower(): counts[status] for status in RECORD_STATUSES},
    }


def _snapshot_filename(path: str | None) -> str | None:
    """Persist only a filename; accept either platform's path separators."""
    return PurePosixPath(str(path).replace("\\", "/")).name if path is not None else None


def _snapshot_ref(snapshot: object, path: str | None) -> dict:
    return {
        "path": _snapshot_filename(path),
        "fetched_at": snapshot.get("fetched_at") if isinstance(snapshot, dict) else None,
        "snapshot_type": snapshot.get("snapshot_type") if isinstance(snapshot, dict) else None,
    }


def compare_snapshots(
    previous: object,
    current: object | None,
    *,
    previous_path: str | None = None,
    current_path: str | None = None,
    current_run_status: str = "SUCCESS",
) -> dict:
    """Compare only validated snapshots; errors never produce NOT_LISTED."""
    if current_run_status not in RUN_ERRORS | {"SUCCESS"}:
        raise ValueError("Unknown run status.")
    compared_at = datetime.now(JST).isoformat()
    events = []
    errors = []
    previous_error, previous_missing, previous_problems = inspect_snapshot(previous, side="previous")
    if previous_error:
        status = previous_error
        events = previous_missing
        errors = previous_problems
    elif current_run_status in RUN_ERRORS:
        status = current_run_status
        errors = [f"Current run reported {current_run_status}; comparison was skipped."]
    else:
        current_error, current_missing, current_problems = inspect_snapshot(current, side="current")
        if current_error:
            status = current_error
            events = current_missing
            errors = current_problems
        elif datetime.fromisoformat(previous["fetched_at"]) >= datetime.fromisoformat(current["fetched_at"]):
            status = "VALIDATION_ERROR"
            errors = ["Previous snapshot must be strictly earlier than current snapshot; comparison was skipped."]
        else:
            status = "SUCCESS"
            old_by_key = defaultdict(list)
            new_by_key = defaultdict(list)
            for index, row in enumerate(previous["records"], start=1):
                key, strategy = identity_for(row)
                old_by_key[key].append((index, row, key, strategy))
            for index, row in enumerate(current["records"], start=1):
                key, strategy = identity_for(row)
                new_by_key[key].append((index, row, key, strategy))
            unmatched_old, unmatched_new = [], []
            for key in sorted(old_by_key.keys() | new_by_key.keys()):
                olds, news = old_by_key[key], new_by_key[key]
                old_duplicates = _duplicate_clusters(olds)
                new_duplicates = _duplicate_clusters(news)
                if old_duplicates or new_duplicates:
                    events.append(_event(
                        "DUPLICATE", key, olds, news,
                        reason="Substantively identical rows repeat within a snapshot; identity group quarantined.",
                    ))
                elif olds and news:
                    pairs = _resolved_pairs(olds, news)
                    if pairs is None:
                        events.append(_event(
                            "AMBIGUOUS_IDENTITY", key, olds, news,
                            reason="Colliding identity candidates lack a consistent one-to-one match.",
                        ))
                    else:
                        events.extend(_matched_event(old, new) for old, new in pairs)
                elif len(olds) > 1 or len(news) > 1:
                    events.append(_event(
                        "AMBIGUOUS_IDENTITY", key, olds, news,
                        reason="Multiple distinct rows share an identity candidate.",
                    ))
                else:
                    unmatched_old.extend(olds)
                    unmatched_new.extend(news)
            cross_events, unmatched_old, unmatched_new = _quarantine_cross_key(
                unmatched_old, unmatched_new
            )
            events.extend(cross_events)
            events.extend(_event("NOT_LISTED", item[2], [item], []) for item in unmatched_old)
            events.extend(_event("NEW", item[2], [], [item]) for item in unmatched_new)
    result = {
        "schema_version": "1B.1",
        "compared_at": compared_at,
        "run_status": status,
        "previous_snapshot": _snapshot_ref(previous, previous_path),
        "current_snapshot": _snapshot_ref(current, current_path),
        "summary": _summary(previous, current, events),
        "events": events,
        "errors": errors,
    }
    return result


def latest_good_snapshots(data_dir: Path, *, limit: int = 2) -> list[Path]:
    """Select by validated snapshot timestamp, never by the latest run log."""
    candidates = []
    for folder in (data_dir / "baselines", data_dir / "snapshots"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            health, _, _ = inspect_snapshot(snapshot, side="candidate")
            if health is None:
                candidates.append((datetime.fromisoformat(snapshot["fetched_at"]), path))
    candidates.sort(key=lambda item: (item[0], str(item[1])))
    return [path for _, path in candidates[-limit:]]


def save_diff_result(result: dict, output_dir: Path = PROJECT_ROOT / "data" / "diffs") -> Path:
    if result["run_status"] != "SUCCESS":
        raise ValueError("Only successful comparisons can be saved as production diffs.")
    stamp = datetime.fromisoformat(result["compared_at"]).strftime("%Y%m%dT%H%M%S%f%z")
    destination = output_dir / f"diff_{stamp}.json"
    portable_result = dict(result)
    for side in ("previous_snapshot", "current_snapshot"):
        reference = dict(result[side])
        reference["path"] = _snapshot_filename(reference.get("path"))
        portable_result[side] = reference
    atomic_json(destination, portable_result)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline comparison of two validated local snapshots.")
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "diffs")
    args = parser.parse_args()
    try:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
        current = json.loads(args.current.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        parser.error(f"Could not read snapshot JSON: {type(exc).__name__}")
    result = compare_snapshots(
        previous, current,
        previous_path=str(args.previous.resolve()),
        current_path=str(args.current.resolve()),
    )
    if result["run_status"] != "SUCCESS":
        print(json.dumps({
            "run_status": result["run_status"],
            "summary": result["summary"],
            "errors": result["errors"],
        }, ensure_ascii=False, indent=2))
        return 1
    path = save_diff_result(result, args.output_dir)
    print(json.dumps({
        "run_status": result["run_status"],
        "summary": result["summary"],
        "saved_file": str(path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
