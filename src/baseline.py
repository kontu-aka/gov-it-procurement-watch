"""One-shot, fail-closed acquisition of the Digital Agency tender baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

SOURCE_URL = "https://www.digital.go.jp/procurement"
ROBOTS_URL = "https://www.digital.go.jp/robots.txt"
AGENCY = "デジタル庁"
CATEGORY = "一般競争入札情報"
USER_AGENT = "GovITProcurementWatch/0.1 (PHASE1A; local-baseline; daily-or-less)"
TIMEOUT = (15, 30)
MAX_BODY_BYTES = 2_000_000
PROJECT_ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
MEANINGFUL_FIELDS = (
    "source_agency", "procurement_category", "title", "posted_date",
    "updated_date", "procurement_number", "notice_type", "detail_url",
)
BLOCK_MARKERS = re.compile(
    r"captcha|cf-chl-|challenge-platform|access\s+denied|too\s+many\s+requests"
    r"|verify\s+you\s+are\s+human|unusual\s+traffic|just\s+a\s+moment"
    r"|アクセス(?:が|を)?制限|アクセスが集中",
    re.IGNORECASE,
)


class AcquisitionError(RuntimeError):
    """An acquisition must not be accepted as a normal baseline."""


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def normalize_url(value: str | None) -> str | None:
    """Sort query parameters, preserving all identifier/stage parameters."""
    if not value:
        return None
    parts = urlsplit(value)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path, query, parts.fragment))


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_date(raw: str | None) -> str | None:
    """Parse explicit Gregorian dates; do not infer a missing year/date."""
    if not raw:
        return None
    match = re.search(r"(?<!\d)(\d{4})年[）)]?\s*(\d{1,2})月\s*(\d{1,2})日", raw)
    if not match:
        match = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", raw)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError:
        return None


def parse_record(item: Tag, fetched_at: str) -> dict:
    anchors = item.find_all("a", recursive=False)
    if len(anchors) > 1:
        raise AcquisitionError("Unexpected multiple direct title links.")
    anchor = anchors[0] if anchors else None
    title_node = anchor if anchor is not None else item.find("strong", recursive=False)
    if title_node is None:
        raise AcquisitionError("Title element missing.")
    title = normalize_text(" ".join(
        str(text) for text in title_node.find_all(string=True)
        if text.find_parent("svg") is None
    ))
    if not title:
        raise AcquisitionError("Title missing.")
    detail_url = None
    href = anchor.get("href") if anchor is not None else None
    if href:
        detail_url = urljoin(SOURCE_URL, href.strip())
        parts = urlsplit(detail_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise AcquisitionError("Unsupported detail URL.")

    metadata_lists = item.find_all("ul", recursive=False)
    if len(metadata_lists) != 1:
        raise AcquisitionError("Expected exactly one metadata list.")
    metadata = [
        normalize_text(node.get_text(" ", strip=True))
        for node in metadata_lists[0].find_all("li", recursive=False)
    ]
    if not metadata or not metadata[0]:
        raise AcquisitionError("Posted date metadata missing.")
    posted_raw = metadata[0]
    posted = parse_date(posted_raw)
    if posted is None:
        raise AcquisitionError("Posted date could not be parsed.")

    number = None
    notice_type = None
    for line in metadata[1:]:
        if not line:
            raise AcquisitionError("Empty metadata item.")
        if line.startswith("調達案件番号"):
            match = re.fullmatch(r"調達案件番号\s*[:：]\s*(\d+)", line)
            if not match or number is not None:
                raise AcquisitionError("Invalid or repeated procurement number.")
            number = match.group(1)
        elif line.startswith("入札公告"):
            if notice_type is not None:
                raise AcquisitionError("Repeated notice type.")
            notice_type = line
        else:
            raise AcquisitionError("Unrecognized tender metadata; manual review required.")

    outside_text = normalize_text(" ".join(
        str(text) for text in item.find_all(string=True, recursive=False)
    ))
    updated_raw = None
    updated = None
    if outside_text:
        match = re.fullmatch(r"[（(]([^（）()]*更新[^（）()]*)[）)]", outside_text)
        if not match:
            raise AcquisitionError("Unexpected text outside title/metadata.")
        updated_raw = outside_text
        updated = parse_date(updated_raw)
        if updated is None:
            raise AcquisitionError("Updated date could not be parsed.")

    unexpected = [
        child.name for child in item.find_all(recursive=False)
        if child is not anchor and child is not title_node
        and child is not metadata_lists[0]
    ]
    if unexpected:
        raise AcquisitionError("Unexpected element inside tender record.")
    return {
        "source_agency": AGENCY,
        "procurement_category": CATEGORY,
        "title": title,
        "posted_date_raw": posted_raw,
        "posted_date": posted,
        "updated_date_raw": updated_raw,
        "updated_date": updated,
        "procurement_number": number,
        "notice_type": notice_type,
        "detail_url": detail_url,
        "source_page_url": SOURCE_URL,
        "fetched_at": fetched_at,
        "stable_key": None,
        "key_strategy": None,
        "content_hash": None,
    }


def parse_tenders(html: str, fetched_at: str) -> tuple[list[dict], list[dict], int]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("html") is None or soup.find("body") is None:
        raise AcquisitionError("A complete HTML document was not received.")
    headings = soup.find_all(id="procurement-announcement")
    if len(headings) != 1:
        raise AcquisitionError("Tender section identifier missing or repeated.")
    heading = headings[0]
    if heading.name != "h3" or normalize_text(heading.get_text(" ", strip=True)) != CATEGORY:
        raise AcquisitionError("Tender section heading differs from expected structure.")
    listing = heading.find_next_sibling()
    if listing is None or listing.name != "ul":
        raise AcquisitionError("Tender section list missing; no structure inference attempted.")
    if any(child.name != "li" for child in listing.find_all(recursive=False)):
        raise AcquisitionError("Unexpected element in tender list.")
    candidates = listing.find_all("li", recursive=False)
    records, errors = [], []
    for index, candidate in enumerate(candidates, start=1):
        try:
            records.append(parse_record(candidate, fetched_at))
        except AcquisitionError as exc:
            errors.append({"record_index": index, "error": str(exc)})
    return records, errors, len(candidates)


def is_case_url(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    if (parts.netloc.lower() == "www.digital.go.jp"
            and parts.path.rstrip("/") == "/procurement"):
        return False
    if parts.path.rstrip("/") in ("", "/pps-web-biz/UAA01/OAA0101"):
        return False
    return True


def assign_keys_and_hashes(records: list[dict]) -> None:
    urls = Counter(normalize_url(row["detail_url"]) for row in records if row["detail_url"])
    for row in records:
        if row["procurement_number"]:
            strategy = "procurement_number"
            key_fields = [row["source_agency"], row["procurement_category"],
                          row["procurement_number"], row["notice_type"]]
        elif is_case_url(row["detail_url"]) and urls[normalize_url(row["detail_url"])] == 1:
            strategy = "detail_url"
            key_fields = [normalize_url(row["detail_url"])]
        else:
            strategy = "category_title_posted_date"
            key_fields = [row["procurement_category"], row["title"], row["posted_date"]]
        row["key_strategy"] = strategy
        row["stable_key"] = strategy + ":" + digest(key_fields)
        content = {field: row[field] for field in MEANINGFUL_FIELDS}
        content["detail_url"] = normalize_url(content["detail_url"])
        row["content_hash"] = digest(content)


def validate(records: list[dict], parse_errors: list[dict], candidate_count: int) -> dict:
    counts = Counter(row["stable_key"] for row in records)
    duplicates = [
        {"stable_key": key, "count": count}
        for key, count in sorted(counts.items()) if key and count > 1
    ]
    errors = []
    warnings = []
    if not records:
        errors.append("No tender records parsed.")
    if parse_errors or len(records) != candidate_count:
        errors.append("Some candidate records could not be parsed.")
    if any(not row["title"] for row in records):
        errors.append("Title missing.")
    if any(not row["posted_date"] for row in records):
        errors.append("Posted date missing.")
    if any(not row["stable_key"] for row in records):
        errors.append("Stable key missing.")
    if duplicates:
        errors.append("Duplicate stable keys detected; records were not deduplicated.")
    missing_numbers = sum(row["procurement_number"] is None for row in records)
    missing_urls = sum(row["detail_url"] is None for row in records)
    if missing_numbers:
        warnings.append(f"Procurement number not published: {missing_numbers}.")
    if missing_urls:
        warnings.append(f"Detail URL not published: {missing_urls}.")
    strategies = dict(Counter(row["key_strategy"] for row in records))
    if strategies.get("category_title_posted_date"):
        warnings.append("Composite fallback keys require review after title/date corrections.")
    return {
        "valid": not errors,
        "result": "PASS_WITH_WARN" if not errors and warnings else ("PASS" if not errors else "FAIL"),
        "candidate_count": candidate_count,
        "parsed_count": len(records),
        "procurement_number_present": len(records) - missing_numbers,
        "procurement_number_missing": missing_numbers,
        "detail_url_present": len(records) - missing_urls,
        "detail_url_missing": missing_urls,
        "updated_date_present": sum(row["updated_date"] is not None for row in records),
        "updated_date_missing": sum(row["updated_date"] is None for row in records),
        "stable_key_duplicate_groups": len(duplicates),
        "stable_key_duplicate_records": sum(item["count"] for item in duplicates),
        "stable_key_duplicate_excess": sum(item["count"] - 1 for item in duplicates),
        "stable_key_duplicates": duplicates,
        "unparseable_record_count": len(parse_errors),
        "parse_errors": parse_errors,
        "key_strategies": strategies,
        "errors": errors,
        "warnings": warnings,
    }


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=0))
    return session


def fetch_text(session: requests.Session, url: str, log: dict, *, robots: bool) -> str:
    if url not in (ROBOTS_URL, SOURCE_URL):
        raise AcquisitionError("Network destination is outside the acquisition scope.")
    log["requested_urls"].append(url)
    with session.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True) as response:
        log["robots_http_status" if robots else "http_status"] = response.status_code
        if response.status_code in (403, 429):
            raise AcquisitionError(f"HTTP {response.status_code}: stopped without retry.")
        if response.status_code != 200:
            raise AcquisitionError(f"HTTP {response.status_code}: success required; redirects disabled.")
        content_type = response.headers.get("Content-Type", "").lower()
        if not robots and not (
            content_type.split(";", 1)[0].strip() in ("text/html", "application/xhtml+xml")
        ):
            raise AcquisitionError("Response Content-Type is not HTML.")
        if robots and content_type.split(";", 1)[0].strip() != "text/plain":
            raise AcquisitionError("robots.txt Content-Type is not plain text.")
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise AcquisitionError("Response exceeds the configured size limit.")
            chunks.append(chunk)
        encoding_match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type)
        encoding = encoding_match.group(1) if encoding_match else "utf-8"
        try:
            body = b"".join(chunks).decode(encoding, errors="strict")
        except (UnicodeError, LookupError) as exc:
            raise AcquisitionError("Response text encoding could not be decoded.") from exc
        if not body.strip():
            raise AcquisitionError("Empty response body.")
        if BLOCK_MARKERS.search(body):
            raise AcquisitionError("CAPTCHA/access restriction marker detected; no bypass or retry.")
        return body


def check_robots(text: str) -> None:
    if "<html" in text.lower() or not re.search(r"(?im)^\s*user-agent\s*:", text):
        raise AcquisitionError("robots.txt does not contain recognizable rules.")
    parser = RobotFileParser()
    parser.set_url(ROBOTS_URL)
    parser.parse(text.splitlines())
    if not parser.can_fetch(USER_AGENT.split("/", 1)[0], SOURCE_URL):
        raise AcquisitionError("robots.txt disallows the target URL.")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise AcquisitionError("Output file already exists; refusing overwrite.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def acquire_baseline(project_dir: Path = PROJECT_ROOT, session=None) -> tuple[int, dict]:
    return _acquire(project_dir, session=session, snapshot_mode=False)


def acquire_snapshot(project_dir: Path = PROJECT_ROOT, session=None) -> tuple[int, dict]:
    """Reuse the approved one-shot pipeline, saving separately from the baseline."""
    return _acquire(project_dir, session=session, snapshot_mode=True)


def _acquire(project_dir: Path, *, session, snapshot_mode: bool) -> tuple[int, dict]:
    started = datetime.now(JST)
    stamp = started.strftime("%Y%m%dT%H%M%S%f%z")
    log_path = project_dir / "logs" / f"acquisition_{stamp}.json"
    baseline_dir = project_dir / "data" / "baselines"
    snapshot_type = "SNAPSHOT" if snapshot_mode else "BASELINE"
    output_dir = project_dir / "data" / ("snapshots" if snapshot_mode else "baselines")
    log = {
        "run_type": snapshot_type,
        "attempted_at": started.isoformat(),
        "fetched_at": None,
        "source_page_url": SOURCE_URL,
        "robots_url": ROBOTS_URL,
        "user_agent": USER_AGENT,
        "robots_http_status": None,
        "http_status": None,
        "requested_urls": [],
        "parsed_count": 0,
        "validation": {"valid": False, "result": "NOT_RUN"},
        "saved_file": None,
        "log_file": str(log_path),
        "error": None,
        "result": "FAIL",
    }
    own_session = session is None
    try:
        if sys.version_info[:2] != (3, 12):
            raise AcquisitionError("Python 3.12.x is required.")
        if not snapshot_mode and next(baseline_dir.glob("baseline_*.json"), None) is not None:
            raise AcquisitionError("A baseline already exists; stopped before any network request.")
        if snapshot_mode:
            from diff_engine import latest_good_snapshots
            if not latest_good_snapshots(project_dir / "data", limit=1):
                raise AcquisitionError("A validated previous snapshot is required; stopped before any network request.")
        session = session or create_session()
        robots_text = fetch_text(session, ROBOTS_URL, log, robots=True)
        check_robots(robots_text)
        html = fetch_text(session, SOURCE_URL, log, robots=False)
        fetched_at = datetime.now(JST).isoformat()
        log["fetched_at"] = fetched_at
        records, parse_errors, candidate_count = parse_tenders(html, fetched_at)
        assign_keys_and_hashes(records)
        validation = validate(records, parse_errors, candidate_count)
        log["parsed_count"] = len(records)
        log["validation"] = validation
        if not validation["valid"]:
            raise AcquisitionError("Validation failed; no snapshot saved.")
        path = output_dir / f"{snapshot_type.lower()}_{stamp}.json"
        snapshot = {
            "schema_version": "1A.1",
            "snapshot_type": snapshot_type,
            "source_agency": AGENCY,
            "procurement_category": CATEGORY,
            "source_page_url": SOURCE_URL,
            "fetched_at": fetched_at,
            "attribution": {
                "source": "デジタル庁「調達情報」",
                "license": "PDL1.0",
                "license_url": "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
                "copyright_policy_url": "https://www.digital.go.jp/copyright-policy",
                "processed_by": "Gov IT Procurement Watch",
                "processing": "公開一覧から一般競争入札情報を抽出・日付正規化・キーとハッシュを生成",
                "official_service": False,
            },
            "validation": validation,
            "records": records,
        }
        atomic_json(path, snapshot)
        log["saved_file"] = str(path)
        log["result"] = validation["result"]
        log["preview"] = records[:3]
        code = 0
    except (AcquisitionError, requests.RequestException, OSError, ValueError) as exc:
        log["error"] = (str(exc) if isinstance(exc, AcquisitionError) else
                        f"{type(exc).__name__}: acquisition stopped; no automatic retry.")
        code = 1
    finally:
        if own_session and session is not None:
            session.close()
    try:
        atomic_json(log_path, log)
    except (OSError, AcquisitionError) as exc:
        log["logging_error"] = type(exc).__name__
        code = 1
    return code, log


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="One-shot acquisition using the approved fixed URLs.")
    parser.add_argument("--snapshot", action="store_true",
                        help="Save the next live snapshot separately; requires validated previous data.")
    args = parser.parse_args()
    code, log = acquire_snapshot() if args.snapshot else acquire_baseline()
    print(json.dumps(log, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
