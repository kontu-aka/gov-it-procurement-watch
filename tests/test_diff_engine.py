"""PHASE 1B offline scenarios based on an exact copy of the saved PHASE 1A baseline."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline
import diff_engine as engine

EXPECTED_FIXTURE_SHA256 = "e6b21073a160611256fa4f8b94ff7fe1e0a803e5607467a560ba89bb8a697e95"
FIXTURE = ROOT / "tests" / "fixtures" / "phase1a_baseline_copy.json"
RESULTS = ROOT / "tests" / "output" / "scenario_results.json"
NEW_FETCHED_AT = "2026-10-04T07:48:18+09:00"


class OfflineDiffTests(unittest.TestCase):
    outcomes: list[dict] = []

    @classmethod
    def setUpClass(cls):
        fixture_bytes = FIXTURE.read_bytes()
        if hashlib.sha256(fixture_bytes).hexdigest() != EXPECTED_FIXTURE_SHA256:
            raise AssertionError("Test fixture must match the verified PHASE 1A baseline digest.")
        cls.template = json.loads(fixture_bytes.decode("utf-8"))
        assert cls.template["validation"]["result"] == "PASS"
        assert len(cls.template["records"]) == 15

    @classmethod
    def tearDownClass(cls):
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(
            json.dumps(
                {
                    "fixture": FIXTURE.relative_to(ROOT).as_posix(),
                    "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                    "web_access_count": 0,
                    "scenarios": sorted(cls.outcomes, key=lambda case: case["id"]),
                },
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def pair(self):
        previous = copy.deepcopy(self.template)
        current = copy.deepcopy(self.template)
        current["snapshot_type"] = "SNAPSHOT"
        current["fetched_at"] = NEW_FETCHED_AT
        for row in current["records"]:
            row["fetched_at"] = NEW_FETCHED_AT
        return previous, current

    def finalize(self, snapshot):
        snapshot["validation"]["parsed_count"] = len(snapshot["records"])
        snapshot["validation"]["candidate_count"] = len(snapshot["records"])

    def recompute(self, row):
        baseline.assign_keys_and_hashes([row])

    def compare(self, previous, current, **kwargs):
        with patch("socket.socket.connect", side_effect=AssertionError("Web access forbidden")), \
             patch("requests.sessions.Session.request", side_effect=AssertionError("Web access forbidden")):
            return engine.compare_snapshots(
                previous, current,
                previous_path="tests/fixtures/previous.json",
                current_path="tests/fixtures/current.json" if current is not None else None,
                **kwargs,
            )

    def check(self, scenario_id, result, expected):
        actual = {"run_status": result["run_status"], **result["summary"]}
        passed = all(actual.get(key) == value for key, value in expected.items())
        self.outcomes.append({
            "id": scenario_id,
            "expected": expected,
            "actual": {key: actual.get(key) for key in expected},
            "passed": passed,
        })
        self.assertTrue(passed, f"{scenario_id}: expected {expected}, got {actual}")
        return result

    def test_01_all_unchanged(self):
        previous, current = self.pair()
        result = self.check("01_all_unchanged", self.compare(previous, current),
                            {"run_status": "SUCCESS", "total_previous": 15,
                             "total_current": 15, "unchanged": 15, "new": 0,
                             "updated": 0, "not_listed": 0})
        self.assertTrue(all(event["status"] == "UNCHANGED" for event in result["events"]))

    def test_02_one_new(self):
        previous, current = self.pair()
        added = copy.deepcopy(current["records"][0])
        added["title"] = "テスト用の新規案件"
        added["procurement_number"] = "0000000000000999999"
        added["detail_url"] = "https://www.digital.go.jp/procurement/fixture-only"
        self.recompute(added)
        current["records"].append(added)
        self.finalize(current)
        result = self.check("02_one_new", self.compare(previous, current),
                            {"run_status": "SUCCESS", "unchanged": 15,
                             "new": 1, "updated": 0, "not_listed": 0})
        self.assertEqual(next(event for event in result["events"] if event["status"] == "NEW")["current"][0]["procurement_number"], "0000000000000999999")

    def test_03_changed_title_and_fields(self):
        previous, current = self.pair()
        row = current["records"][0]
        old_title = row["title"]
        row["title"] = old_title + "（訂正）"
        self.recompute(row)
        result = self.check("03_changed_title", self.compare(previous, current),
                            {"run_status": "SUCCESS", "unchanged": 14,
                             "updated": 1, "new": 0, "not_listed": 0})
        updated = next(event for event in result["events"] if event["status"] == "UPDATED")
        self.assertEqual(updated["changed_fields"]["title"], {
            "before": old_title, "after": row["title"],
        })
        self.assertNotIn("fetched_at", updated["changed_fields"])
        self.assertEqual(updated["previous"][0]["identity_key"], updated["current"][0]["identity_key"])
        self.assertEqual(updated["previous"][0]["stable_key"], updated["current"][0]["stable_key"])

    def test_04_one_not_listed(self):
        previous, current = self.pair()
        current["records"].pop(0)
        self.finalize(current)
        result = self.check("04_one_not_listed", self.compare(previous, current),
                            {"run_status": "SUCCESS", "total_current": 14,
                             "unchanged": 14, "not_listed": 1, "new": 0})
        self.assertEqual(next(event for event in result["events"] if event["status"] == "NOT_LISTED")["current"], [])

    def test_05_url_fallback(self):
        previous, current = self.pair()
        for snapshot in (previous, current):
            row = snapshot["records"][0]
            row["procurement_number"] = None
            self.recompute(row)
        result = self.check("05_url_fallback", self.compare(previous, current),
                            {"run_status": "SUCCESS", "unchanged": 15,
                             "missing": 0, "ambiguous_identity": 0})
        event = result["events"][0]
        self.assertEqual(event["identity_strategy"], "detail_url")
        self.assertIsNone(current["records"][0]["procurement_number"])

    def test_06_composite_fallback(self):
        previous, current = self.pair()
        for snapshot in (previous, current):
            row = snapshot["records"][0]
            row["procurement_number"] = None
            row["detail_url"] = None
            self.recompute(row)
        result = self.check("06_composite_fallback", self.compare(previous, current),
                            {"run_status": "SUCCESS", "unchanged": 15,
                             "missing": 0, "ambiguous_identity": 0})
        self.assertEqual(result["events"][0]["identity_strategy"], "category_title_posted_date")

    def test_07_shared_number_distinct_notices_match_one_to_one(self):
        previous, current = self.pair()
        second = copy.deepcopy(previous["records"][0])
        second["title"] = "同一番号の別公告（テスト）"
        second["notice_type"] = "入札公告（追加公告）"
        second["detail_url"] = second["detail_url"].replace("chancnt=0", "chancnt=1")
        second["posted_date"] = "2026-09-15"
        second["posted_date_raw"] = "令和8年（2026年）9月15日"
        self.recompute(second)
        previous["records"].append(copy.deepcopy(second))
        current["records"].append(copy.deepcopy(second))
        self.finalize(previous)
        self.finalize(current)
        result = self.check("07_shared_number_distinct_notices", self.compare(previous, current),
                            {"run_status": "SUCCESS", "total_previous": 16,
                             "total_current": 16, "unchanged": 16,
                             "duplicate": 0, "ambiguous_identity": 0})

    def test_08_identity_collision_is_ambiguous(self):
        previous, current = self.pair()
        second = copy.deepcopy(current["records"][0])
        second["title"] = "同一番号で対応不能な別公告（テスト）"
        second["notice_type"] = "入札公告（追加公告）"
        second["detail_url"] = second["detail_url"].replace("chancnt=0", "chancnt=2")
        self.recompute(second)
        current["records"].append(second)
        self.finalize(current)
        result = self.check("08_collision_ambiguous", self.compare(previous, current),
                            {"run_status": "SUCCESS", "ambiguous_identity": 1,
                             "duplicate": 0, "new": 0, "updated": 0,
                             "not_listed": 0, "unchanged": 14})

    def test_09_missing_required_title(self):
        previous, current = self.pair()
        current["records"][0]["title"] = ""
        result = self.check("09_missing_title", self.compare(previous, current),
                            {"run_status": "VALIDATION_ERROR", "missing": 1,
                             "not_listed": 0, "new": 0, "updated": 0})
        self.assertEqual(result["events"][0]["missing_fields"], ["title"])

    def test_10_fetch_error_never_not_listed(self):
        previous, _ = self.pair()
        result = self.check("10_fetch_error", self.compare(
            previous, None, current_run_status="FETCH_ERROR"),
            {"run_status": "FETCH_ERROR", "not_listed": 0,
             "total_current": None, "unchanged": 0})
        self.assertEqual(result["events"], [])

    def test_11_structure_error_never_not_listed(self):
        previous, _ = self.pair()
        result = self.check("11_structure_error", self.compare(
            previous, None, current_run_status="STRUCTURE_ERROR"),
            {"run_status": "STRUCTURE_ERROR", "not_listed": 0,
             "total_current": None, "unchanged": 0})
        self.assertEqual(result["events"], [])

    def test_12_hash_difference_updated(self):
        previous, current = self.pair()
        row = current["records"][0]
        row["updated_date"] = "2026-09-19"
        row["updated_date_raw"] = "（2026年9月19日更新）"
        self.recompute(row)
        result = self.check("12_content_hash_difference", self.compare(previous, current),
                            {"run_status": "SUCCESS", "updated": 1,
                             "unchanged": 14, "not_listed": 0})
        update = next(event for event in result["events"] if event["status"] == "UPDATED")
        self.assertEqual(update["changed_fields"]["updated_date"], {
            "before": None, "after": "2026-09-19",
        })

    def test_13_validation_error_never_not_listed(self):
        previous, _ = self.pair()
        self.check("13_validation_error", self.compare(
            previous, None, current_run_status="VALIDATION_ERROR"),
            {"run_status": "VALIDATION_ERROR", "not_listed": 0,
             "total_current": None})

    def test_14_substantive_duplicate_not_number_only(self):
        previous, current = self.pair()
        self.assertTrue(engine.is_substantive_duplicate(current["records"][0], copy.deepcopy(current["records"][0])))
        different = copy.deepcopy(current["records"][0])
        different["notice_type"] = "入札公告（追加公告）"
        self.assertFalse(engine.is_substantive_duplicate(current["records"][0], different))
        current["records"].append(copy.deepcopy(current["records"][0]))
        self.finalize(current)
        self.check("14_substantive_duplicate", self.compare(previous, current),
                   {"run_status": "SUCCESS", "duplicate": 1,
                    "unchanged": 14, "new": 0, "not_listed": 0})

    def test_15_cross_key_change_is_not_new_or_not_listed(self):
        previous, current = self.pair()
        row = current["records"][0]
        row["procurement_number"] = None
        self.recompute(row)
        self.check("15_cross_key_quarantine", self.compare(previous, current),
                   {"run_status": "SUCCESS", "ambiguous_identity": 1,
                    "new": 0, "not_listed": 0, "unchanged": 14})

    def test_16_latest_good_ignores_failed_runs(self):
        root = ROOT / "work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            data = Path(temp) / "data"
            good_dir = data / "baselines"
            invalid_dir = data / "snapshots"
            logs = Path(temp) / "logs"
            good_dir.mkdir(parents=True)
            invalid_dir.mkdir(parents=True)
            logs.mkdir()
            good = good_dir / "baseline.json"
            good.write_text(json.dumps(self.template, ensure_ascii=False), encoding="utf-8")
            invalid = copy.deepcopy(self.template)
            invalid["fetched_at"] = "2026-10-05T07:48:18+09:00"
            invalid["validation"]["valid"] = False
            (invalid_dir / "failed.json").write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            (logs / "latest_failed_run.json").write_text('{"result":"FETCH_ERROR"}', encoding="utf-8")
            selected = engine.latest_good_snapshots(data)
            self.assertEqual(selected, [good])
            self.check("16_latest_good", self.compare(*self.pair()),
                       {"run_status": "SUCCESS", "unchanged": 15, "not_listed": 0})

    def test_17_conflicting_unique_signals_stay_ambiguous(self):
        previous, current = self.pair()
        second = copy.deepcopy(previous["records"][0])
        second["title"] = "同一番号の別公告（テスト）"
        second["notice_type"] = "入札公告（追加公告）"
        second["detail_url"] = second["detail_url"].replace("chancnt=0", "chancnt=1")
        self.recompute(second)
        previous["records"].append(copy.deepcopy(second))
        current["records"].append(copy.deepcopy(second))
        # Swap URLs while notice types remain unchanged: two signals disagree.
        first_url = current["records"][0]["detail_url"]
        current["records"][0]["detail_url"] = current["records"][-1]["detail_url"]
        current["records"][-1]["detail_url"] = first_url
        self.recompute(current["records"][0])
        self.recompute(current["records"][-1])
        self.finalize(previous)
        self.finalize(current)
        self.check("17_conflicting_signals", self.compare(previous, current),
                   {"run_status": "SUCCESS", "ambiguous_identity": 1,
                    "duplicate": 0, "updated": 0, "new": 0, "not_listed": 0,
                    "unchanged": 14})

    def test_18_malformed_current_is_structure_error(self):
        previous, current = self.pair()
        current["records"] = "malformed"
        self.check("18_malformed_structure", self.compare(previous, current),
                   {"run_status": "STRUCTURE_ERROR", "not_listed": 0,
                    "new": 0, "total_current": None})

    def test_19_corrupt_field_type_is_validation_error(self):
        previous, current = self.pair()
        current["records"][0]["detail_url"] = 123
        self.check("19_corrupt_field_type", self.compare(previous, current),
                   {"run_status": "VALIDATION_ERROR", "not_listed": 0,
                    "new": 0, "updated": 0})

    def test_20_hash_tampering_is_validation_error(self):
        previous, current = self.pair()
        current["records"][0]["content_hash"] = "0" * 64
        self.check("20_hash_tampering", self.compare(previous, current),
                   {"run_status": "VALIDATION_ERROR", "not_listed": 0,
                    "new": 0, "updated": 0})

    def test_22_number_only_without_corroboration_is_ambiguous(self):
        previous, current = self.pair()
        row = current["records"][0]
        row["title"] = "番号が再利用された可能性のある別案件（テスト）"
        row["detail_url"] = "https://www.digital.go.jp/procurement/different-fixture-case"
        self.recompute(row)
        self.check("22_number_only_ambiguous", self.compare(previous, current),
                   {"run_status": "SUCCESS", "ambiguous_identity": 1,
                    "updated": 0, "new": 0, "not_listed": 0,
                    "unchanged": 14})

    def test_23_missing_posted_date(self):
        previous, current = self.pair()
        current["records"][0]["posted_date"] = None
        result = self.check("23_missing_posted_date", self.compare(previous, current),
                            {"run_status": "VALIDATION_ERROR", "missing": 1,
                             "not_listed": 0, "new": 0})
        self.assertEqual(result["events"][0]["missing_fields"], ["posted_date"])

    def test_21_diff_file_shape_in_test_output_only(self):
        previous, current = self.pair()
        row = current["records"][0]
        row["title"] += "（訂正）"
        self.recompute(row)
        result = self.compare(previous, current)
        root = ROOT / "work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            path = engine.save_diff_result(result, Path(temp) / "tests-output")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["run_status"], "SUCCESS")
            self.assertEqual(saved["previous_snapshot"]["path"], "previous.json")
            self.assertEqual(saved["current_snapshot"]["path"], "current.json")
            self.assertIn("compared_at", saved)
            self.assertEqual(saved["summary"]["updated"], 1)
            self.assertEqual(next(event for event in saved["events"] if event["status"] == "UPDATED")["changed_fields"]["title"]["after"], row["title"])
            with self.assertRaises(ValueError):
                engine.save_diff_result(
                    self.compare(previous, None, current_run_status="FETCH_ERROR"),
                    Path(temp) / "tests-output",
                )
        self.check("21_diff_file_shape", result,
                   {"run_status": "SUCCESS", "updated": 1, "unchanged": 14})


if __name__ == "__main__":
    unittest.main()
