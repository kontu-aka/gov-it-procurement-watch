"""Presentation helpers. Statuses come only from saved comparison events."""

from __future__ import annotations

from html import escape


STATUS_STYLES = {
    "NEW": ("新規掲載", "new"),
    "UPDATED": ("内容更新", "updated"),
    "NOT_LISTED": ("今回の一覧から非掲載", "not-listed"),
    "UNCHANGED": ("変更なし", "unchanged"),
    "AMBIGUOUS_IDENTITY": ("照合保留", "review"),
    "DUPLICATE": ("重複・確認が必要", "review"),
    "MISSING": ("情報不足", "review"),
}


def status_badge(status: str | None) -> str:
    label, tone = STATUS_STYLES.get(status, ("判定なし", "neutral"))
    return f'<span class="status-badge {tone}">{escape(label)}</span>'


def saved_statuses(diff: dict) -> dict[str, str]:
    """Match current rows by exact saved stable_key; never infer a diff."""
    if diff["state"] != "READY":
        return {}
    statuses: dict[str, set[str]] = {}
    for event in diff["result"]["events"]:
        for row in event["current"] or []:
            if row.get("stable_key"):
                statuses.setdefault(row["stable_key"], set()).add(event["status"])
    return {key: next(iter(values)) for key, values in statuses.items() if len(values) == 1}


def record_card(row: dict, status: str | None, url: str | None) -> str:
    """Escape all saved text; callers pass the existing URL validator's result."""
    e = lambda value: escape(str(value or "未掲載"), quote=True)
    _, tone = STATUS_STYLES.get(status, ("判定なし", "neutral"))
    link = (f'<a class="detail-link" href="{e(url)}" target="_blank" '
            'rel="noopener noreferrer">詳細を開く ↗</a>') if url else '<span class="muted">詳細リンクなし</span>'
    updated = f'<span>更新日 {e(row["updated_date"])}</span>' if "updated_date" in row else ""
    return (
        f'<article class="record-card {tone}">'
        f'<div class="record-top">{status_badge(status)}'
        f'<span class="record-date">掲載日 {e(row["posted_date"])}</span></div>'
        f'<h3>{e(row["title"])}</h3>'
        '<div class="record-bottom"><div class="record-meta">'
        f'<span>案件番号 <strong>{e(row["procurement_number"])}</strong></span>'
        f'<span>{e(row["notice_type"])}</span>'
        f'{updated}</div>{link}</div></article>'
    )
