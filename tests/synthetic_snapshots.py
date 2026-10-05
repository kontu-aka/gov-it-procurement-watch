"""Fixture-derived synthetic generations for tests only; never live observations."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline


def unchanged_pair():
    previous = json.loads((ROOT / "tests/fixtures/phase1a_baseline_copy.json").read_text(encoding="utf-8"))
    current = copy.deepcopy(previous)
    current["snapshot_type"] = "SNAPSHOT"
    current["fetched_at"] = "2026-10-04T07:48:18+09:00"
    for row in current["records"]:
        row["fetched_at"] = current["fetched_at"]
    return previous, current


def nonzero_pair():
    """Deliberately synthetic NEW/UPDATED/NOT_LISTED/AMBIGUOUS_IDENTITY."""
    previous, current = unchanged_pair()
    for snapshot in (previous, current):
        for row in snapshot["records"]:
            row["title"] = "合成テスト：" + row["title"]
            baseline.assign_keys_and_hashes([row])
    current["records"][1]["title"] += "（合成の訂正）"
    baseline.assign_keys_and_hashes([current["records"][1]])
    added = copy.deepcopy(current["records"][0])
    added.update(title="合成テスト：新規レコード", procurement_number="0000000000000999999",
                 detail_url="https://www.digital.go.jp/procurement/synthetic-new")
    collision = copy.deepcopy(current["records"][3])
    collision.update(title="合成テスト：同一番号の対応不能レコード", notice_type="合成の追加公告",
                     detail_url="https://www.digital.go.jp/procurement/synthetic-collision")
    baseline.assign_keys_and_hashes([added, collision])
    current["records"].pop(2)
    current["records"].extend([added, collision])
    for snapshot in (previous, current):
        snapshot["validation"]["candidate_count"] = len(snapshot["records"])
        snapshot["validation"]["parsed_count"] = len(snapshot["records"])
    return previous, current
