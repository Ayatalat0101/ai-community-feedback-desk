"""
Export the feedback log for Project 1 (the AI Data Analyst).

This is where the two projects meet: Project 1 answers "how many households
did each partner reach?"; with this file it can also answer "how many
complaints did each partner receive?" or "which governorate waits longest
for an answer?".

Privacy rules (PROJECT_PLAN.md §5, test T14):
  * NO name, phone number or message text, ever: the file may be shared
    with partners and donors.
  * A sensitive (referred) row keeps ONLY its category and date. Even its
    partner or governorate could identify a survivor in a small community.
  * Columns are fixed and named for analysis, one row per feedback.
"""
from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from . import distributions
from .policy import POLICY
from .store import events_for, list_tickets

COLUMNS = ["reference", "date", "month", "channel", "language", "governorate", "partner", "item",
           "distribution_id", "distribution_status", "category", "priority", "rule", "status",
           "days_open", "target_days", "overdue"]
RESOLVED_EVENTS = {"approved", "edited_and_approved", "closed"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _resolved_at(conn: sqlite3.Connection, ref: str) -> datetime | None:
    """When a person first approved or closed it: the end of 'open'."""
    for e in events_for(conn, ref):
        if e["event"] in RESOLVED_EVENTS:
            return _parse(e["at"])
    return None


def build_export(conn: sqlite3.Connection, now: datetime | None = None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    status_of = dict(zip(distributions.load()["distribution_id"], distributions.load()["status"]))
    rows = []
    for t in sorted(list_tickets(conn), key=lambda t: t["ref"]):
        created = _parse(t["created_at"])
        if t["restricted"]:
            rows.append({"reference": "", "date": created.date().isoformat(), "category": "sensitive"})
            continue
        end = _resolved_at(conn, t["ref"]) or now
        rule = (t["priority_rule"] or "").split(":")[0]
        target = POLICY[rule][1] if rule in POLICY else None
        days = max((end - created).days, 0)
        dst = t["distribution_id"] if t["distribution_id"] in status_of else None   # never export a wrong number
        rows.append({
            "reference": t["ref"], "date": created.date().isoformat(), "month": created.strftime("%Y-%m"),
            "channel": t["channel"], "language": t["language"], "governorate": t["governorate"],
            "partner": t["partner"], "item": t["item"], "distribution_id": dst,
            "distribution_status": status_of.get(dst),
            "category": t["category"], "priority": t["priority"], "rule": rule or None, "status": t["status"],
            "days_open": days, "target_days": target,
            "overdue": ("yes" if days > target else "no") if target is not None else None,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 with BOM, so Excel on Windows shows Arabic correctly (Project 1 reads it too)."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8-sig")
