"""Offline safety/behavior tests. No test makes a network request."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import baseline as app


def item(title="クラウドの調査", number="0000000000000000001",
         href="https://www.p-portal.go.jp/pps-web-biz/UAA01/OAA0122?anken=0000000000000000001&cla=3",
         updated=None):
    link = f'<a href="{href}"><strong>{title}</strong></a>' if href else f"<strong>{title}</strong>"
    suffix = f"（{updated}更新）" if updated else ""
    number_li = f"<li>調達案件番号:{number}</li>" if number is not None else ""
    return (f"<li>{link}{suffix}<ul><li>令和8年（2026年）9月14日</li>"
            f"{number_li}<li>入札公告（WTO対象外）</li></ul></li>")


def document(items=None):
    if items is None:
        items = item()
    return ('<!doctype html><html><body>'
            '<h3 id="procurement-announcement">一般競争入札情報</h3>'
            f'<ul>{items}</ul><h3 id="proposal">企画競争情報</h3>'
            '<ul><li><a href="/procurement/another">収集しない別セクション</a></li></ul>'
            '</body></html>')


def response(body, status=200, content_type="text/html; charset=UTF-8"):
    result = requests.Response()
    result.status_code = status
    result.headers["Content-Type"] = content_type
    result._content = body.encode("utf-8")
    result._content_consumed = True
    return result


class FakeSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.replies:
            raise AssertionError("An unexpected extra request was made.")
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def robots(body="User-agent: *\nDisallow: /admin/\n"):
    return response(body, content_type="text/plain; charset=UTF-8")


class ParserTests(unittest.TestCase):
    def parse(self, html):
        records, errors, count = app.parse_tenders(html, "2026-10-03T12:00:00+09:00")
        app.assign_keys_and_hashes(records)
        return records, app.validate(records, errors, count)

    def test_exact_section_nested_metadata_and_update(self):
        rows, validation = self.parse(document(item(updated="2026年9月18日")))
        self.assertTrue(validation["valid"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["procurement_number"], "0000000000000000001")
        self.assertEqual(rows[0]["posted_date"], "2026-09-14")
        self.assertEqual(rows[0]["updated_date"], "2026-09-18")
        self.assertEqual(rows[0]["updated_date_raw"], "（2026年9月18日更新）")
        self.assertEqual(rows[0]["key_strategy"], "procurement_number")

    def test_missing_optional_values_and_url_fallback(self):
        rows, validation = self.parse(document(item(number=None)))
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["procurement_number_missing"], 1)
        self.assertIsNone(rows[0]["updated_date"])
        self.assertEqual(rows[0]["key_strategy"], "detail_url")

    def test_no_url_uses_composite_not_title(self):
        rows, validation = self.parse(document(item(number=None, href=None)))
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["detail_url_missing"], 1)
        self.assertEqual(rows[0]["key_strategy"], "category_title_posted_date")

    def test_duplicate_keys_reported_without_deletion(self):
        rows, validation = self.parse(document(item() + item()))
        self.assertEqual(len(rows), 2)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["stable_key_duplicate_groups"], 1)
        self.assertEqual(validation["stable_key_duplicate_records"], 2)

    def test_shared_url_does_not_become_a_url_key(self):
        rows, validation = self.parse(document(item(number=None) + item(title="別案件", number=None)))
        self.assertTrue(validation["valid"])
        self.assertTrue(all(row["key_strategy"] == "category_title_posted_date" for row in rows))

    def test_number_key_includes_category_and_notice_type(self):
        rows, _ = self.parse(document())
        original = rows[0]
        for field in ("source_agency", "procurement_category", "procurement_number", "notice_type"):
            changed = copy.deepcopy(original)
            changed[field] = str(changed[field]) + "変更"
            app.assign_keys_and_hashes([changed])
            self.assertNotEqual(original["stable_key"], changed["stable_key"])

    def test_hash_ignores_fetch_time_and_raw_date_format(self):
        rows, _ = self.parse(document())
        changed = copy.deepcopy(rows[0])
        changed["fetched_at"] = "2027-01-01T00:00:00+09:00"
        changed["posted_date_raw"] = "2026年9月14日"
        app.assign_keys_and_hashes([changed])
        self.assertEqual(rows[0]["content_hash"], changed["content_hash"])
        self.assertEqual(rows[0]["stable_key"], changed["stable_key"])

    def test_hash_changes_for_each_meaningful_field(self):
        rows, _ = self.parse(document())
        for field in app.MEANINGFUL_FIELDS:
            with self.subTest(field=field):
                changed = copy.deepcopy(rows[0])
                changed[field] = str(changed[field]) + "変更"
                app.assign_keys_and_hashes([changed])
                self.assertNotEqual(rows[0]["content_hash"], changed["content_hash"])

    def test_url_query_order_is_normalized_without_removing_identifiers(self):
        left = app.normalize_url("https://www.p-portal.go.jp/x?cla=3&anken=0001&chancnt=0")
        right = app.normalize_url("https://www.p-portal.go.jp/x?chancnt=0&anken=0001&cla=3")
        self.assertEqual(left, right)
        self.assertIn("anken=0001", left)
        self.assertIn("cla=3", left)

    def test_bad_date_and_unknown_metadata_are_not_guessed(self):
        for html in (
            document().replace("9月14日", "13月14日"),
            document().replace("入札公告（WTO対象外）", "未知の新しい構造"),
            document().replace("<strong>クラウドの調査</strong>", "<strong></strong>"),
        ):
            with self.subTest(html=html):
                _, validation = self.parse(html)
                self.assertFalse(validation["valid"])
                self.assertEqual(validation["unparseable_record_count"], 1)

    def test_structure_change_empty_section_and_non_html_fail(self):
        for html in (
            document().replace("procurement-announcement", "different"),
            document().replace("</h3><ul>", "</h3><p>構造変更</p><ul>", 1),
            "<html><body>Not the procurement page</body></html>",
            '{"records": []}',
        ):
            with self.subTest(html=html):
                with self.assertRaises(app.AcquisitionError):
                    self.parse(html)
        _, validation = self.parse(document(""))
        self.assertFalse(validation["valid"])


class AcquisitionTests(unittest.TestCase):
    def run_fake(self, replies):
        root = ROOT / "work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            project = Path(directory)
            session = FakeSession(replies)
            code, log = app.acquire_baseline(project, session=session)
            snapshots = list((project / "data" / "baselines").glob("*.json"))
            saved = json.loads(snapshots[0].read_text(encoding="utf-8")) if snapshots else None
            self.assertEqual(len(list((project / "logs").glob("*.json"))), 1)
            return code, log, session, saved

    def test_success_two_requests_baseline_and_no_external_fetch(self):
        code, log, session, snapshot = self.run_fake([robots(), response(document())])
        self.assertEqual(code, 0)
        self.assertEqual(log["http_status"], 200)
        self.assertEqual(snapshot["snapshot_type"], "BASELINE")
        self.assertEqual([call[0] for call in session.calls], [app.ROBOTS_URL, app.SOURCE_URL])
        for _, kwargs in session.calls:
            self.assertEqual(kwargs["timeout"], app.TIMEOUT)
            self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("change_type", snapshot["records"][0])

    def test_robots_disallow_and_invalid_robots_stop_before_page(self):
        for body in ("User-agent: *\nDisallow: /procurement\n", "no valid rules"):
            code, _, session, snapshot = self.run_fake([robots(body)])
            self.assertEqual(code, 1)
            self.assertEqual(len(session.calls), 1)
            self.assertIsNone(snapshot)

    def test_403_and_429_stop_without_retry(self):
        for status in (403, 429):
            code, log, session, snapshot = self.run_fake([robots(), response("", status=status)])
            self.assertEqual(code, 1)
            self.assertEqual(log["http_status"], status)
            self.assertEqual(len(session.calls), 2)
            self.assertIsNone(snapshot)

    def test_captcha_redirect_non_html_and_timeout_do_not_save(self):
        for answer in (
            response("<html><body>Verify you are human: CAPTCHA</body></html>"),
            response("", status=302),
            response('{"data": []}', content_type="application/json"),
            requests.Timeout("no response"),
            response(document("").replace("</body>", "Access denied</body>")),
        ):
            code, _, session, snapshot = self.run_fake([robots(), answer])
            self.assertEqual(code, 1)
            self.assertEqual(len(session.calls), 2)
            self.assertIsNone(snapshot)

    def test_partial_parse_and_duplicate_keys_do_not_save(self):
        for html in (document(item() + "<li>破損レコード</li>"), document(item() + item())):
            code, log, _, snapshot = self.run_fake([robots(), response(html)])
            self.assertEqual(code, 1)
            self.assertEqual(log["validation"]["result"], "FAIL")
            self.assertIsNone(snapshot)

    def test_size_limit_does_not_save(self):
        with patch.object(app, "MAX_BODY_BYTES", 100):
            code, _, _, snapshot = self.run_fake([robots(), response(document())])
        self.assertEqual(code, 1)
        self.assertIsNone(snapshot)

    def test_existing_baseline_stops_before_network(self):
        root = ROOT / "work"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            project = Path(directory)
            target = project / "data" / "baselines"
            target.mkdir(parents=True)
            (target / "baseline_previous.json").write_text("{}", encoding="utf-8")
            session = FakeSession([])
            code, log = app.acquire_baseline(project, session=session)
            self.assertEqual(code, 1)
            self.assertEqual(session.calls, [])
            self.assertIn("already exists", log["error"])

    def test_session_has_explicit_agent_and_no_retries(self):
        with app.create_session() as session:
            self.assertEqual(session.headers["User-Agent"], app.USER_AGENT)
            self.assertEqual(session.get_adapter("https://").max_retries.total, 0)


if __name__ == "__main__":
    unittest.main()
