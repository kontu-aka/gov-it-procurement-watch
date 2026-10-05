"""Regression tests for protected repeat acquisition and live snapshot selection."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline
import dashboard_data as dash
from test_baseline import FakeSession, robots, response, document, item

BASE = ROOT / "tests/fixtures/phase1a_baseline_copy.json"


class Phase1DTests(unittest.TestCase):
    def area(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        return tempfile.TemporaryDirectory(dir=work)

    def baseline_in(self, root):
        path = root / "data/baselines/baseline_original.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(BASE.read_bytes())
        return path

    def test_repeat_saves_separately_and_preserves_baseline(self):
        with self.area() as temp:
            root = Path(temp)
            previous = self.baseline_in(root)
            original = previous.read_bytes()
            session = FakeSession([robots(), response(document())])
            code, log = baseline.acquire_snapshot(root, session=session)
            self.assertEqual(code, 0)
            self.assertEqual(previous.read_bytes(), original)
            self.assertEqual(len(list(previous.parent.glob("*.json"))), 1)
            current = Path(log["saved_file"])
            self.assertEqual(current.parent, root / "data/snapshots")
            self.assertEqual(json.loads(current.read_text(encoding="utf-8"))["snapshot_type"], "SNAPSHOT")
            self.assertEqual([call[0] for call in session.calls], [baseline.ROBOTS_URL, baseline.SOURCE_URL])

    def test_missing_previous_stops_before_network(self):
        with self.area() as temp:
            session = FakeSession([])
            code, log = baseline.acquire_snapshot(Path(temp), session=session)
            self.assertEqual(code, 1)
            self.assertEqual(session.calls, [])
            self.assertIn("validated previous", log["error"])

    def test_repeat_validation_failure_preserves_baseline_and_saves_no_snapshot(self):
        with self.area() as temp:
            root = Path(temp)
            previous = self.baseline_in(root)
            original = previous.read_bytes()
            session = FakeSession([robots(), response(document(item() + "<li>broken</li>"))])
            code, log = baseline.acquire_snapshot(root, session=session)
            self.assertEqual(code, 1)
            self.assertEqual(log["validation"]["result"], "FAIL")
            self.assertEqual(previous.read_bytes(), original)
            self.assertEqual(list((root / "data/snapshots").glob("*.json")), [])
            self.assertEqual(len(session.calls), 2)

    def test_latest_live_snapshot_selected_and_invalid_newer_excluded(self):
        with self.area() as temp:
            root = Path(temp)
            self.baseline_in(root)
            valid = json.loads(BASE.read_text(encoding="utf-8"))
            valid["snapshot_type"] = "SNAPSHOT"
            valid["fetched_at"] = "2026-10-04T07:48:18+09:00"
            folder = root / "data/snapshots"
            folder.mkdir()
            path = folder / "new_live.json"
            path.write_text(json.dumps(valid), encoding="utf-8")
            invalid = copy.deepcopy(valid)
            invalid["fetched_at"] = "2026-10-05T07:48:18+09:00"
            invalid["records"][0]["title"] = "tampered without hash update"
            (folder / "invalid.json").write_text(json.dumps(invalid), encoding="utf-8")
            loaded = dash.load_latest_baseline(root / "data")
            self.assertEqual(loaded["path"], path)
            self.assertEqual(len(loaded["rejected"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
