"""Read-only view models for the local procurement dashboard. No HTTP calls."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from baseline import PROJECT_ROOT, SOURCE_URL
from diff_engine import identity_for, inspect_snapshot, latest_good_snapshots

KEYWORDS = ("AI", "クラウド", "SaaS", "セキュリティ", "システム", "データ", "自治体")
ALLOWED_LINK_HOSTS = {"www.digital.go.jp", "www.p-portal.go.jp"}
DATA_ROOT = PROJECT_ROOT / "data"


def normalize_search(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def safe_detail_url(value: object) -> str | None:
    """Links are user-clicked; the application never fetches their targets."""
    if not isinstance(value, str) or value != value.strip() or any(ch in value for ch in "\r\n\t"):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_LINK_HOSTS
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or not parsed.path):
            return None
    except ValueError:
        return None
    return value


def load_latest_baseline(data_root: Path = DATA_ROOT) -> dict:
    """Read validated production baseline/snapshot folders and choose by fetched_at."""
    files = []
    for folder in (data_root / "baselines", data_root / "snapshots"):
        if folder.is_dir() and not folder.is_symlink():
            files.extend(sorted(folder.glob("*.json")))
    if not files:
        return {"snapshot": None, "path": None, "reason": "本番の正常snapshot候補がありません。", "rejected": []}
    good = []
    rejected = []
    for path in files:
        if path.is_symlink():
            rejected.append(f"{path.name}: シンボリックリンクは対象外")
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            rejected.append(f"{path.name}: JSONを読み取れません")
            continue
        status, _, problems = inspect_snapshot(snapshot, side="dashboard")
        if status is not None:
            rejected.append(f"{path.name}: {status}")
            continue
        if not isinstance(snapshot["validation"].get("warnings", []), list):
            rejected.append(f"{path.name}: validation.warningsの形式が不正")
            continue
        good.append((datetime.fromisoformat(snapshot["fetched_at"]), path, snapshot))
    if not good:
        return {
            "snapshot": None,
            "path": None,
            "reason": f"{len(files)}件の候補に検証済みsnapshotがありません。",
            "rejected": rejected,
        }
    _, path, snapshot = max(good, key=lambda item: (item[0], item[1].name))
    return {"snapshot": snapshot, "path": path, "reason": None, "rejected": rejected}


def fetched_at_label(snapshot: dict) -> str:
    value = snapshot.get("fetched_at")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "取得日時不明（タイムゾーン不明）"
    offset = parsed.utcoffset()
    if offset is None:
        return parsed.isoformat(timespec="seconds") + "（タイムゾーン不明）"
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    hours, remainder = divmod(abs(seconds), 3600)
    minutes = remainder // 60
    return f"{parsed.strftime('%Y-%m-%d %H:%M:%S')}（UTC{sign}{hours:02d}:{minutes:02d}）"


def snapshot_kpis(snapshot: dict) -> dict:
    records = snapshot["records"]
    warnings = snapshot["validation"].get("warnings", [])
    return {
        "listed": len(records),
        "with_number": sum(bool(row.get("procurement_number")) for row in records),
        "with_updated_date": sum(bool(row.get("updated_date")) for row in records),
        "validation_warn_items": len(warnings),
    }


def filter_records(
    records: list[dict], *, keyword: str = "",
    posted_from: date | None = None, posted_to: date | None = None,
    notice_type: str | None = None,
) -> list[dict]:
    needle = normalize_search(keyword.strip())
    selected = []
    for row in records:
        posted = row.get("posted_date")
        try:
            posted_day = date.fromisoformat(posted)
        except (TypeError, ValueError):
            continue
        if needle and needle not in normalize_search(row.get("title") or ""):
            continue
        if posted_from is not None and posted_day < posted_from:
            continue
        if posted_to is not None and posted_day > posted_to:
            continue
        if notice_type is not None and row.get("notice_type") != notice_type:
            continue
        selected.append(row)
    return selected


def keyword_counts(records: list[dict]) -> dict[str, int]:
    totals = {keyword: 0 for keyword in KEYWORDS}
    for row in records:
        title = normalize_search(row.get("title") or "")
        for keyword in KEYWORDS:
            if normalize_search(keyword) in title:
                totals[keyword] += 1
    return totals


def monthly_counts(records: list[dict]) -> dict[str, int]:
    counts = Counter()
    for row in records:
        try:
            posted = date.fromisoformat(row.get("posted_date"))
        except (TypeError, ValueError):
            continue
        counts[posted.strftime("%Y-%m")] += 1
    return dict(sorted(counts.items()))


def quality_summary(snapshot: dict) -> dict:
    records = snapshot["records"]
    identities = Counter(identity_for(row)[0] for row in records)
    warnings = snapshot["validation"].get("warnings", [])
    return {
        "procurement_number_missing": sum(not row.get("procurement_number") for row in records),
        "detail_url_missing": sum(not row.get("detail_url") for row in records),
        "updated_date_unpublished": sum(not row.get("updated_date") for row in records),
        "identity_collision_groups": sum(count > 1 for count in identities.values()),
        "validation_result": snapshot["validation"]["result"],
        "validation_warnings": warnings,
        "validation_warning_items": len(warnings),
    }


def _same_snapshot_reference(reference: object, path: Path, fetched_at: str, data_root: Path) -> bool:
    if not isinstance(reference, dict):
        return False
    if reference.get("fetched_at") != fetched_at:
        return False
    saved_path = reference.get("path")
    if not isinstance(saved_path, str):
        return False
    try:
        reference_path = Path(saved_path)
        if not reference_path.is_absolute():
            if len(reference_path.parts) == 1:
                return reference_path.name == path.name
            reference_path = data_root / reference_path
        return reference_path.resolve() == path.resolve()
    except (OSError, ValueError):
        return False


def diff_display_state(data_root: Path = DATA_ROOT) -> dict:
    """Read a saved PHASE 1B result only; never create or recompute a live diff."""
    good = latest_good_snapshots(data_root, limit=2)
    if len(good) < 2:
        return {
            "state": "NOT_COMPARABLE",
            "message": "比較可能な2件目の正常snapshotがまだありません",
            "result": None,
            "path": None,
        }
    previous, current = good
    snapshots = (
        json.loads(previous.read_text(encoding="utf-8")),
        json.loads(current.read_text(encoding="utf-8")),
    )
    folder = data_root / "diffs"
    candidates = []
    if folder.is_dir() and not folder.is_symlink():
        for path in folder.glob("*.json"):
            if path.is_symlink():
                continue
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                compared = datetime.fromisoformat(result["compared_at"])
            except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if (compared.utcoffset() is None or result.get("schema_version") != "1B.1"
                    or result.get("run_status") != "SUCCESS"
                    or not isinstance(result.get("summary"), dict)
                    or not isinstance(result.get("events"), list)
                    or not _same_snapshot_reference(result.get("previous_snapshot"), previous, snapshots[0]["fetched_at"], data_root)
                    or not _same_snapshot_reference(result.get("current_snapshot"), current, snapshots[1]["fetched_at"], data_root)):
                continue
            candidates.append((compared, path, result))
    if not candidates:
        return {
            "state": "NOT_CREATED",
            "message": "正常snapshotは2件ありますが、対応する差分結果はまだ作成されていません。",
            "result": None,
            "path": None,
        }
    _, path, result = max(candidates, key=lambda item: (item[0], item[1].name))
    return {"state": "READY", "message": None, "result": result, "path": path}


def source_links(snapshot: dict) -> dict:
    attribution = snapshot.get("attribution")
    if not isinstance(attribution, dict):
        attribution = {}
    def verified(value: object, fallback: str) -> str:
        return value if isinstance(value, str) and value.startswith("https://www.digital.go.jp/") else fallback
    return {
        "procurement": SOURCE_URL,
        "copyright": verified(attribution.get("copyright_policy_url"), "https://www.digital.go.jp/copyright-policy"),
        "pdl": verified(attribution.get("license_url"), "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"),
    }
