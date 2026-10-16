"""Presentation regressions using saved event identities, never live acquisition."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dashboard_data import safe_detail_url
from dashboard_ui import record_card, saved_statuses, status_badge
from diff_engine import compare_snapshots
from synthetic_snapshots import nonzero_pair


class DashboardPresentationTests(unittest.TestCase):
    def test_synthetic_saved_events_keep_their_exact_status_per_current_record(self):
        previous, current = nonzero_pair()
        result = compare_snapshots(previous, current)
        statuses = saved_statuses({"state": "READY", "result": result})
        for event in result["events"]:
            for row in event["current"]:
                self.assertEqual(statuses[row["stable_key"]], event["status"])
        absent = next(event for event in result["events"] if event["status"] == "NOT_LISTED")
        self.assertNotIn(absent["previous"][0]["stable_key"], statuses)
        self.assertTrue({"NEW", "UPDATED", "UNCHANGED", "AMBIGUOUS_IDENTITY"} <= set(statuses.values()))

    def test_missing_or_conflicting_comparison_does_not_claim_unchanged(self):
        for state in ("NOT_CREATED", "NOT_COMPARABLE"):
            self.assertEqual(saved_statuses({"state": state}), {})
        events = [{"status": status, "current": [{"stable_key": "same"}]}
                  for status in ("NEW", "UPDATED")]
        self.assertEqual(saved_statuses({"state": "READY", "result": {"events": events}}), {})
        self.assertIn("判定なし", status_badge(None))
        self.assertNotIn("変更なし", status_badge(None))

    def test_card_escapes_saved_text_and_preserves_number_and_link(self):
        _, current = nonzero_pair()
        row = dict(current["records"][0], title='<script>alert("x")</script> & 調達')
        url = safe_detail_url(row["detail_url"])
        html = record_card(row, "NEW", url)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn(row["procurement_number"], html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('class="status-badge new">新規掲載', html)
        self.assertNotIn("href=", record_card(row, "NEW", safe_detail_url("javascript:alert(1)")))

    def test_diff_projection_does_not_claim_an_unrecorded_update_date(self):
        previous, current = nonzero_pair()
        result = compare_snapshots(previous, current)
        event = next(event for event in result["events"] if event["status"] == "NOT_LISTED")
        row = event["previous"][0]
        self.assertNotIn("updated_date", row)
        html = record_card(row, "NOT_LISTED", safe_detail_url(row["detail_url"]))
        self.assertIn("今回の一覧から非掲載", html)
        self.assertNotIn("更新日", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
