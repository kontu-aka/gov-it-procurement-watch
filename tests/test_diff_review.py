"""Offline chronology, portable references and diff CLI regression tests."""
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import dashboard_data as dash
import diff_engine as engine
from synthetic_snapshots import nonzero_pair, unchanged_pair


def area():
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=work)


class SnapshotChronologyTests(unittest.TestCase):
    def assert_closed(self, previous, current, expected_status):
        result = engine.compare_snapshots(previous, current)
        self.assertEqual(result["run_status"], expected_status)
        self.assertEqual(result["events"], [])
        for key in ("new", "updated", "not_listed"):
            self.assertEqual(result["summary"][key], 0)
        with area() as temp:
            output = Path(temp) / "diffs"
            with self.assertRaises(ValueError):
                engine.save_diff_result(result, output)
            self.assertFalse(output.exists())

    def test_ordered_saved_generations_no_change(self):
        # Existing public saved data, read only; no acquisition.
        samples = ROOT / "data/samples"
        previous = json.loads(next((samples / "baselines").glob("*.json")).read_text(encoding="utf-8"))
        current = json.loads(next((samples / "snapshots").glob("*.json")).read_text(encoding="utf-8"))
        result = engine.compare_snapshots(previous, current)
        self.assertEqual(result["run_status"], "SUCCESS")
        self.assertEqual(result["summary"]["unchanged"], 15)
        self.assertTrue(all(e["status"] == "UNCHANGED" for e in result["events"]))

    def test_reverse_order_is_rejected_without_reversed_events(self):
        previous, current = nonzero_pair()
        self.assert_closed(current, previous, "VALIDATION_ERROR")

    def test_same_snapshot_is_rejected(self):
        previous, _ = unchanged_pair()
        for current in (previous, copy.deepcopy(previous)):
            with self.subTest(same_object=current is previous):
                self.assert_closed(previous, current, "VALIDATION_ERROR")

    def test_missing_invalid_or_naive_dates_fail_closed(self):
        for side in (0, 1):
            for value in (None, "unparseable", "2026-10-04T07:48:18"):
                with self.subTest(side=side, value=value):
                    pair = list(nonzero_pair())
                    if value is None:
                        pair[side].pop("fetched_at")
                    else:
                        pair[side]["fetched_at"] = value
                    self.assert_closed(*pair, "STRUCTURE_ERROR")

    def test_same_instant_with_different_offsets_is_rejected(self):
        previous, current = unchanged_pair()
        current["fetched_at"] = datetime.fromisoformat(previous["fetched_at"]).astimezone(timezone.utc).isoformat()
        self.assert_closed(previous, current, "VALIDATION_ERROR")

    def test_timezone_offsets_are_compared_as_instants(self):
        previous, current = unchanged_pair()
        previous["fetched_at"] = "2026-10-03T23:00:00+09:00"
        current["fetched_at"] = "2026-10-03T15:00:00+00:00"
        result = engine.compare_snapshots(previous, current)
        self.assertEqual(result["run_status"], "SUCCESS")
        self.assertEqual(result["summary"]["unchanged"], 15)


class PortableReferenceTests(unittest.TestCase):
    def test_absolute_and_relative_paths_persist_only_filenames(self):
        previous, current = unchanged_pair()
        paths = (str(ROOT / "data/baselines/previous.json"),
                 "baselines/previous.json", str(PureWindowsPath(ROOT.anchor) / "review" / "previous.json"))
        for path in paths:
            with self.subTest(path_kind=type(path).__name__):
                result = engine.compare_snapshots(previous, current, previous_path=path,
                                                  current_path=str(ROOT / "data/snapshots/current.json"))
                self.assertEqual(result["previous_snapshot"]["path"], "previous.json")
                self.assertEqual(result["current_snapshot"]["path"], "current.json")

    def test_save_sanitizes_legacy_paths_without_mutating_input(self):
        previous, current = unchanged_pair()
        result = engine.compare_snapshots(previous, current)
        old_path = str(ROOT / "data/baselines/previous.json")
        result["previous_snapshot"]["path"] = old_path
        result["current_snapshot"]["path"] = str(ROOT / "data/snapshots/current.json")
        with area() as temp:
            saved = json.loads(engine.save_diff_result(result, Path(temp) / "diffs").read_text(encoding="utf-8"))
        self.assertEqual(saved["previous_snapshot"]["path"], "previous.json")
        self.assertEqual(saved["current_snapshot"]["path"], "current.json")
        self.assertEqual(result["previous_snapshot"]["path"], old_path)

    def test_saved_diff_is_ready_after_dataset_relocation(self):
        previous, current = unchanged_pair()
        with area() as temp:
            original, moved = Path(temp) / "original", Path(temp) / "moved"
            old, new = original / "baselines/previous.json", original / "snapshots/current.json"
            for path, snapshot in ((old, previous), (new, current)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = engine.compare_snapshots(previous, current, previous_path=str(old), current_path=str(new))
            engine.save_diff_result(result, original / "diffs")
            shutil.copytree(original, moved)
            self.assertEqual(dash.diff_display_state(moved)["state"], "READY")


class DiffCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(self.enterContext(area()))
        self.previous_path = self.temp / "baselines/previous.json"
        self.current_path = self.temp / "snapshots/current.json"
        self.output = self.temp / "diffs"
        self.write_pair(*nonzero_pair())

    def write_pair(self, previous, current):
        for path, snapshot in ((self.previous_path, previous), (self.current_path, current)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(snapshot), encoding="utf-8")

    def call_cli(self, previous=None, current=None):
        argv = ["diff_engine.py", str(previous or self.previous_path), str(current or self.current_path),
                "--output-dir", str(self.output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = engine.main()
            except SystemExit as exc:
                code = exc.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_success_saves_nonzero_synthetic_diff_with_portable_references(self):
        code, stdout, stderr = self.call_cli()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["run_status"], "SUCCESS")
        files = list(self.output.glob("*.json"))
        self.assertEqual(len(files), 1)
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(saved["previous_snapshot"]["path"], "previous.json")
        self.assertEqual(saved["current_snapshot"]["path"], "current.json")
        self.assertTrue({"NEW", "UPDATED", "NOT_LISTED", "AMBIGUOUS_IDENTITY"} <= {e["status"] for e in saved["events"]})

    def test_reverse_and_same_file_return_failure_without_output(self):
        for previous, current in ((self.current_path, self.previous_path), (self.previous_path, self.previous_path)):
            with self.subTest(same_file=previous == current):
                code, stdout, _ = self.call_cli(previous, current)
                self.assertEqual(code, 1)
                result = json.loads(stdout)
                self.assertEqual(result["run_status"], "VALIDATION_ERROR")
                self.assertEqual(result["summary"]["new"], 0)
                self.assertEqual(result["summary"]["not_listed"], 0)
                self.assertFalse(self.output.exists())

    def test_missing_input_is_argparse_error_without_output(self):
        code, _, stderr = self.call_cli(previous=self.temp / "missing.json")
        self.assertEqual(code, 2)
        self.assertIn("Could not read snapshot JSON", stderr)
        self.assertFalse(self.output.exists())

    def test_malformed_json_is_argparse_error_without_output(self):
        self.current_path.write_text("{broken", encoding="utf-8")
        code, _, stderr = self.call_cli()
        self.assertEqual(code, 2)
        self.assertIn("Could not read snapshot JSON", stderr)
        self.assertFalse(self.output.exists())

    def test_invalid_record_returns_validation_error_without_output(self):
        previous, current = nonzero_pair()
        current["records"][0]["title"] += "hash not updated"
        self.write_pair(previous, current)
        code, stdout, _ = self.call_cli()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["run_status"], "VALIDATION_ERROR")
        self.assertFalse(self.output.exists())
