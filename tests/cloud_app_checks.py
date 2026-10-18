"""Explicit optional Streamlit checks for the public-sample deployment entrypoint."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import streamlit_app_checks as existing
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class CloudAppChecks(existing.StreamlitAppChecks):
    # Reuse the existing functional checks, with only the entrypoint changed.
    def setUp(self):
        sys.path.insert(0, str(ROOT / "src"))
        import dashboard_data as dash
        self.dash = dash
        self.demo_mode = True
        self.data_root = ROOT / "data/samples"
        self.loaded = dash.load_latest_baseline(self.data_root)
        self.snapshot = self.loaded["snapshot"]
        self.rows = self.snapshot["records"]
        self.no_http = patch("requests.sessions.Session.request",
                             side_effect=AssertionError("HTTP is forbidden in the viewer"))
        self.no_http.start()
        self.addCleanup(self.no_http.stop)
        self.app = AppTest.from_file(str(ROOT / "cloud_app.py"), default_timeout=20).run()
        self.assertEqual(len(self.app.exception), 0)

    def test_public_label_six_kpis_and_fixed_selection(self):
        self.assertTrue(self.app.checkbox[0].disabled)
        self.assertTrue(self.app.checkbox[0].value)
        self.assertEqual([m.value for m in self.app.metric[:6]], ["15", "0", "0", "0", "15", "0"])
        self.assertTrue(any("2026年10月3日・4日" in i.value and "現在の調達状況ではありません" in i.value
                            for i in self.app.info))
        self.assertTrue(any("非公式ツール" in i.value for i in self.app.caption))
        self.assertFalse(self.app.error)

    def test_false_session_state_cannot_select_private_data(self):
        # Defense in depth: UI state cannot override the cloud entrypoint's data root.
        self.app.session_state["demo_mode"] = False
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, "15")
        self.assertEqual(len(self.app.dataframe[0].value), 15)
        self.assertTrue(any("公開サンプル" in i.value for i in self.app.info))

    def test_no_private_reads_or_data_writes(self):
        enabled = [True]
        violations = []
        sample_root = (ROOT / "data/samples").resolve()
        data_root = (ROOT / "data").resolve()

        def audit(event, args):
            if not enabled[0] or event not in ("open", "os.listdir", "os.scandir"):
                return
            if not isinstance(args[0], (str, bytes, os.PathLike)):
                return
            path = Path(os.fsdecode(args[0])).resolve()
            if not path.is_relative_to(data_root):
                return
            if not path.is_relative_to(sample_root):
                violations.append("private data access")
                raise PermissionError("Public viewer must not access private data")
            if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                violations.append("sample data write")
                raise PermissionError("Public viewer must not write sample data")

        sys.addaudithook(audit)
        try:
            self.app.session_state["demo_mode"] = False
            self.app.text_input[0].set_value("クラウド").run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.metric[0].value, "15")
            self.assertFalse(violations)
        finally:
            enabled[0] = False

    def test_missing_or_invalid_samples_stop_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp)
            shutil.copy2(ROOT / "app.py", copied / "app.py")
            shutil.copy2(ROOT / "cloud_app.py", copied / "cloud_app.py")
            shutil.copytree(ROOT / "assets", copied / "assets")
            # Valid private snapshots are present; cloud must still stop.
            shutil.copytree(ROOT / "data/samples/baselines", copied / "data/baselines")
            with patch.object(self.dash, "DATA_ROOT", copied / "data"):
                # A control run proves the app can read this exact test data root.
                control = AppTest.from_file(str(copied / "app.py"), default_timeout=20)
                control.session_state["demo_mode"] = False
                control.run()
                self.assertFalse(control.exception)
                self.assertFalse(control.error)
                self.assertEqual(control.metric[0].value, "15")
                for invalid in (False, True):
                    with self.subTest(invalid_sample=invalid):
                        if invalid:
                            folder = copied / "data/samples/baselines"
                            folder.mkdir(parents=True)
                            (folder / "invalid.json").write_text("{}", encoding="utf-8")
                        app = AppTest.from_file(str(copied / "cloud_app.py"), default_timeout=20).run()
                        self.assertFalse(app.exception)
                        self.assertTrue(app.error)
                        self.assertEqual(len(app.metric), 0)
                        self.assertTrue(any("公開サンプル" in i.value for i in app.info))

    def test_local_default_has_no_silent_sample_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.dash, "DATA_ROOT", Path(tmp)):
                app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
                app.session_state["demo_mode"] = False
                app.run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertFalse(app.info)
                self.assertEqual(len(app.metric), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
