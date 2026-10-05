"""Explicit AppTest checks; optional Streamlit runtime, never acquisition."""
import sys
import unittest
from datetime import date
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from phase1c_network_guard import install
install(ROOT / "tests" / "output" / "apptest_connections.jsonl")

import streamlit as st
from streamlit.testing.v1 import AppTest


class StreamlitAppChecks(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "src"))
        import dashboard_data as dash
        self.dash = dash
        self.demo_mode = os.environ.get("GOV_IT_APPTEST_DEMO") == "1" or dash.load_latest_baseline(ROOT / "data")["snapshot"] is None
        self.data_root = ROOT / "data/samples" if self.demo_mode else ROOT / "data"
        self.loaded = dash.load_latest_baseline(self.data_root)
        self.snapshot = self.loaded["snapshot"]
        self.rows = self.snapshot["records"]
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
        self.app.session_state["demo_mode"] = self.demo_mode
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def check_rerun(self):
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)

    def test_initial_data_metadata_and_leading_zeros(self):
        metrics = {item.label: item.value for item in self.app.metric}
        self.assertEqual([metrics[name] for name in
                          ("現在掲載件数", "案件番号あり", "更新日記載あり", "データ品質WARN")],
                         [str(value) for value in self.dash.snapshot_kpis(self.snapshot).values()])
        table = self.app.dataframe[0].value
        self.assertEqual(len(table), len(self.rows))
        self.assertEqual(table.iloc[0]["案件番号"], self.rows[0]["procurement_number"])
        self.assertTrue(table["詳細リンク"].str.startswith("https://").all())
        captions = "\n".join(item.value for item in self.app.caption)
        self.assertIn(self.dash.fetched_at_label(self.snapshot), captions)
        self.assertIn(self.loaded["path"].name, captions)
        self.assertNotIn("fixtures", captions)
        self.assertTrue(any("デジタル庁公式サービスではありません" in item.value
                            for item in self.app.markdown))

    def test_keyword_search_and_rerun(self):
        self.app.text_input[0].set_value("クラウド").run()
        self.assertEqual(len(self.app.exception), 0)
        table = self.app.dataframe[0].value
        expected = len(self.dash.filter_records(self.rows, keyword="クラウド"))
        self.assertEqual(len(table), expected)
        self.assertTrue(table["案件名"].str.contains("クラウド").all())
        self.check_rerun()
        self.assertEqual(len(self.app.dataframe[0].value), expected)
        self.assertEqual(self.app.metric[0].value, str(len(self.rows)))

    def test_date_range_and_rerun(self):
        self.app.date_input[0].set_value((date(2026, 8, 1), date(2026, 8, 31))).run()
        self.assertEqual(len(self.app.exception), 0)
        table = self.app.dataframe[0].value
        expected = len(self.dash.filter_records(self.rows, posted_from=date(2026, 8, 1), posted_to=date(2026, 8, 31)))
        self.assertEqual(len(table), expected)
        self.assertTrue(table["掲載日"].str.startswith("2026-08").all())
        self.check_rerun()
        self.assertEqual(len(self.app.dataframe[0].value), expected)

    def test_notice_filter_and_rerun(self):
        self.app.selectbox[0].select("入札公告（WTO対象）").run()
        self.assertEqual(len(self.app.exception), 0)
        table = self.app.dataframe[0].value
        self.assertGreater(len(table), 0)
        self.assertLess(len(table), len(self.rows))
        self.assertTrue((table["公告種別"] == "入札公告（WTO対象）").all())
        self.check_rerun()
        self.assertTrue((self.app.dataframe[0].value["公告種別"] == "入札公告（WTO対象）").all())

    def test_zero_results_and_recovery(self):
        self.app.text_input[0].set_value("該当なし検証語ZZZZ").run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIn("条件に該当する案件はありません。", [item.value for item in self.app.info])
        self.check_rerun()
        self.app.text_input[0].set_value("").run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.dataframe[0].value), len(self.rows))

    def test_diff_quality_aggregates_and_telemetry_disabled(self):
        self.assertFalse(st.get_option("browser.gatherUsageStats"))
        state = self.dash.diff_display_state(self.data_root)
        labels = {item.label: item.value for item in self.app.metric}
        if state["state"] == "READY":
            summary = state["result"]["summary"]
            for label, key in (("NEW", "new"), ("UPDATED", "updated"), ("一覧から非掲載", "not_listed")):
                self.assertEqual(labels[label], str(summary[key]))
            self.assertNotIn("比較可能な2件目の正常snapshotがまだありません",
                             [item.value for item in self.app.info])
            self.assertTrue(any("比較済み" in item.value for item in self.app.caption))
            if all(event["status"] == "UNCHANGED" for event in state["result"]["events"]):
                self.assertIn("NO CHANGE：比較済み・差分0件", [item.value for item in self.app.info])
        else:
            self.assertIn(state["message"], [item.value for item in self.app.info])
            self.assertNotIn("NEW", labels)
        quality = self.dash.quality_summary(self.snapshot)
        self.assertEqual(labels["更新日未掲載"], str(quality["updated_date_unpublished"]))
        self.assertEqual(labels["identity衝突候補"], str(quality["identity_collision_groups"]))
        self.assertTrue(any(f"validation status：{quality['validation_result']}" in item.value
                            for item in self.app.markdown))
        keywords = self.app.dataframe[1].value
        self.assertEqual(dict(zip(keywords["キーワード"], keywords["該当案件数"])),
                         self.dash.keyword_counts(self.rows))
        months = self.app.dataframe[2].value
        self.assertEqual(dict(zip(months["掲載月"], months["案件数"])),
                         self.dash.monthly_counts(self.rows))




class SyntheticDiffAppChecks(unittest.TestCase):
    """Synthetic fixture data only; these are not observed live changes."""
    def test_nonzero_diff_expanders_and_updated_fields_render(self):
        import json
        import tempfile
        from unittest.mock import patch
        import dashboard_data as dash
        import diff_engine as engine
        from synthetic_snapshots import nonzero_pair

        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        previous, current = nonzero_pair()
        with tempfile.TemporaryDirectory(dir=work) as temp:
            data = Path(temp) / "data"
            old, new = data / "baselines/synthetic_previous.json", data / "snapshots/synthetic_current.json"
            for path, snapshot in ((old, previous), (new, current)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = engine.compare_snapshots(previous, current, previous_path=str(old), current_path=str(new))
            self.assertEqual(result["run_status"], "SUCCESS")
            expected = {"NEW", "UPDATED", "NOT_LISTED", "AMBIGUOUS_IDENTITY"}
            self.assertTrue(expected <= {event["status"] for event in result["events"]})
            engine.save_diff_result(result, data / "diffs")
            with patch.object(dash, "DATA_ROOT", data):
                app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
                app.session_state["demo_mode"] = False
                app.run()
                self.assertEqual(len(app.exception), 0)
                metrics = {item.label: item.value for item in app.metric}
                for label in ("NEW", "UPDATED", "一覧から非掲載"):
                    self.assertEqual(metrics[label], "1")
                labels = [item.label for item in app.expander]
                for status in expected:
                    self.assertTrue(any(label.startswith(status + "｜合成テスト：") for label in labels), status)
                self.assertTrue(any("title" in str(item.value) for item in app.json))
                self.assertNotIn("NO CHANGE：比較済み・差分0件", [item.value for item in app.info])
                app.run()
                self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
