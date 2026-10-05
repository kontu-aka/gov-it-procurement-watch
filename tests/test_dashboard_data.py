"""Offline view-model tests for the read-only dashboard."""
from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline
import dashboard_data as dash
import diff_engine

BASELINE = ROOT / "tests" / "fixtures" / "phase1a_baseline_copy.json"


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(BASELINE.read_text(encoding="utf-8"))

    def data_area(self):
        root = ROOT / "work"
        root.mkdir(exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)

    def save_snapshot(self, data_root, name, snapshot, *, folder="baselines"):
        target = Path(data_root) / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        return path

    def test_latest_uses_fetched_at_not_filename(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            older = copy.deepcopy(self.original)
            newer = copy.deepcopy(self.original)
            newer["fetched_at"] = "2026-10-04T07:48:18+09:00"
            self.save_snapshot(root, "z_older.json", older)
            new_path = self.save_snapshot(root, "a_newer.json", newer)
            loaded = dash.load_latest_baseline(root)
            self.assertEqual(loaded["path"], new_path)
            self.assertEqual(loaded["snapshot"]["fetched_at"], newer["fetched_at"])

    def test_invalid_newer_and_test_fixtures_are_not_displayed(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            good_path = self.save_snapshot(root, "baseline_good.json", self.original)
            failed = copy.deepcopy(self.original)
            failed["fetched_at"] = "2026-10-06T07:48:18+09:00"
            failed["validation"]["valid"] = False
            self.save_snapshot(root, "baseline_failed.json", failed)
            tests = Path(temp) / "tests"
            for folder in ("fixtures", "output"):
                (tests / folder).mkdir(parents=True, exist_ok=True)
                (tests / folder / "fake.json").write_text(
                    json.dumps(self.original, ensure_ascii=False), encoding="utf-8"
                )
            loaded = dash.load_latest_baseline(root)
            self.assertEqual(loaded["path"], good_path)
            self.assertEqual(len(loaded["rejected"]), 1)

    def test_no_good_baseline_explains_and_never_substitutes_fake_data(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            no_files = dash.load_latest_baseline(root)
            self.assertIsNone(no_files["snapshot"])
            self.assertIsNotNone(no_files["reason"])
            empty = copy.deepcopy(self.original)
            empty["records"] = []
            self.save_snapshot(root, "empty.json", empty)
            broken_path = root / "baselines" / "newer.json"
            broken_path.write_text("{broken", encoding="utf-8")
            loaded = dash.load_latest_baseline(root)
            self.assertIsNone(loaded["snapshot"])
            self.assertEqual(len(loaded["rejected"]), 2)

    def test_real_baseline_counts_number_string_and_timezone(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            path = self.save_snapshot(root, "baseline.json", self.original)
            loaded = dash.load_latest_baseline(root)
            self.assertEqual(loaded["path"], path)
        rows = loaded["snapshot"]["records"]
        self.assertEqual(dash.snapshot_kpis(loaded["snapshot"]), {
            "listed": 15, "with_number": 15, "with_updated_date": 3,
            "validation_warn_items": 0,
        })
        self.assertEqual(dash.quality_summary(loaded["snapshot"]), {
            "procurement_number_missing": 0,
            "detail_url_missing": 0,
            "updated_date_unpublished": 12,
            "identity_collision_groups": 0,
            "validation_result": "PASS",
            "validation_warnings": [],
            "validation_warning_items": 0,
        })
        self.assertTrue(all(isinstance(row["procurement_number"], str) for row in rows))
        self.assertEqual(rows[0]["procurement_number"], "0000000000000621786")
        self.assertIn("UTC+09:00", dash.fetched_at_label(loaded["snapshot"]))

    def test_keyword_normalization_repeated_word_and_zero_counts(self):
        records = [
            {"title": "ＡＩとaiによるSaaSとＳａａＳの検証"},
            {"title": "クラウドの導入"},
            {"title": "自治体データとシステム"},
        ]
        counts = dash.keyword_counts(records)
        self.assertEqual(counts["AI"], 1)
        self.assertEqual(counts["SaaS"], 1)
        self.assertEqual(counts["クラウド"], 1)
        self.assertEqual(counts["セキュリティ"], 0)
        self.assertEqual(counts["データ"], 1)
        self.assertEqual(counts["自治体"], 1)
        self.assertEqual(set(counts), set(dash.KEYWORDS))

    def test_monthly_counts_do_not_infer_missing_or_invalid_dates(self):
        records = [
            {"posted_date": "2026-09-01"},
            {"posted_date": "2026-09-30"},
            {"posted_date": "2026-10-01"},
            {"posted_date": None},
            {"posted_date": "2026-13-01"},
        ]
        self.assertEqual(dash.monthly_counts(records), {
            "2026-09": 2, "2026-10": 1,
        })

    def test_filter_search_date_notice_and_zero_results(self):
        rows = self.original["records"]
        filtered = dash.filter_records(
            rows, keyword="クラウド",
            posted_from=date(2026, 9, 1),
            posted_to=date(2026, 9, 30),
            notice_type="入札公告（WTO対象）",
        )
        self.assertTrue(filtered)
        self.assertTrue(all(
            "クラウド" in row["title"]
            and row["notice_type"] == "入札公告（WTO対象）"
            and "2026-09-01" <= row["posted_date"] <= "2026-09-30"
            for row in filtered
        ))
        self.assertEqual(dash.filter_records(rows, keyword="存在しない案件語"), [])

    def test_single_good_snapshot_is_not_comparable(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            self.save_snapshot(root, "baseline.json", self.original)
            state = dash.diff_display_state(root)
        self.assertEqual(state["state"], "NOT_COMPARABLE")
        self.assertEqual(state["message"], "比較可能な2件目の正常snapshotがまだありません")
        self.assertIsNone(state["result"])

    def test_two_snapshots_without_matching_diff_is_not_created(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            self.save_snapshot(root, "base.json", self.original)
            newer = copy.deepcopy(self.original)
            newer["snapshot_type"] = "SNAPSHOT"
            newer["fetched_at"] = "2026-10-04T07:48:18+09:00"
            self.save_snapshot(root, "second.json", newer, folder="snapshots")
            result = dash.diff_display_state(root)
            self.assertEqual(result["state"], "NOT_CREATED")
            self.assertIsNone(result["result"])
            # A test result stored outside data/diffs must never become production output.
            test_output = Path(temp) / "tests" / "output"
            test_output.mkdir(parents=True)
            (test_output / "fixture.json").write_text('{"run_status":"SUCCESS"}', encoding="utf-8")
            self.assertEqual(dash.diff_display_state(root)["state"], "NOT_CREATED")

    def test_matching_phase1b_diff_can_be_displayed_without_recomputing(self):
        with self.data_area() as temp:
            root = Path(temp) / "data"
            previous_path = self.save_snapshot(root, "base.json", self.original)
            newer = copy.deepcopy(self.original)
            newer["snapshot_type"] = "SNAPSHOT"
            newer["fetched_at"] = "2026-10-04T07:48:18+09:00"
            current_path = self.save_snapshot(root, "second.json", newer, folder="snapshots")
            result = diff_engine.compare_snapshots(
                self.original, newer, previous_path=str(previous_path.resolve()),
                current_path=str(current_path.resolve()),
            )
            saved = diff_engine.save_diff_result(result, root / "diffs")
            state = dash.diff_display_state(root)
            self.assertEqual(state["state"], "READY")
            self.assertEqual(state["path"], saved)
            self.assertEqual(state["result"]["summary"]["unchanged"], 15)
            # Published demo diffs resolve relative to their data root, independent of checkout path.
            result["previous_snapshot"]["path"] = previous_path.relative_to(root).as_posix()
            result["current_snapshot"]["path"] = current_path.relative_to(root).as_posix()
            saved.write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(dash.diff_display_state(root)["state"], "READY")

    def test_warning_items_and_unpublished_updates_remain_separate(self):
        snapshot = copy.deepcopy(self.original)
        snapshot["validation"]["result"] = "PASS_WITH_WARN"
        snapshot["validation"]["warnings"] = ["番号欠損の確認が必要"]
        quality = dash.quality_summary(snapshot)
        self.assertEqual(quality["validation_warning_items"], 1)
        self.assertEqual(quality["updated_date_unpublished"], 12)
        self.assertEqual(dash.snapshot_kpis(snapshot)["validation_warn_items"], 1)

    def test_detail_link_accepts_only_known_https_hosts(self):
        good = self.original["records"][0]["detail_url"]
        self.assertEqual(dash.safe_detail_url(good), good)
        for value in (
            "", None, "javascript:alert(1)", "http://www.p-portal.go.jp/x",
            "https://malicious.example/x",
            "https://www.digital.go.jp.evil.example/x",
            "https://www.digital.go.jp/x\nbad",
        ):
            with self.subTest(value=value):
                self.assertIsNone(dash.safe_detail_url(value))

    def test_app_source_parses_without_streamlit_import(self):
        ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
