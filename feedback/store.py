"""
Feedback store: the ONLY module that talks to SQLite.

Why SQLite?
-----------
Feedback must survive restarts and be visible to the officer days later
(the response targets are 24 hours to 14 days). SQLite is a real SQL
database in one file, built into Python, with no server to install.

Rules followed everywhere below:
1. Parameterised queries (`?`), never f-strings with values: a message like
   "'); DROP TABLE feedback; --" is stored as text, not executed.
2. Every change writes an audit event in the SAME transaction, so the
   history can never disagree with the ticket (who referred, who approved).
3. Status / category / priority / channel are checked against the enums.
4. `restricted` marks a safeguarding case. The store keeps it; the screens
   decide who may read it (stage 4), and the export drops its details (stage 5).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Category, Channel, Priority, Status, Submission, normalise_dst

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    seq               INTEGER PRIMARY KEY AUTOINCREMENT,
    ref               TEXT UNIQUE,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    channel           TEXT NOT NULL,
    person_ref        TEXT NOT NULL,
    phone             TEXT,
    language          TEXT,
    message           TEXT NOT NULL,
    distribution_id   TEXT,
    governorate       TEXT,
    partner           TEXT,
    item              TEXT,
    category          TEXT,
    category_reason   TEXT,
    priority          TEXT,
    priority_rule     TEXT,
    status            TEXT NOT NULL,
    restricted        INTEGER NOT NULL DEFAULT 0,
    missing           TEXT DEFAULT '[]',
    options           TEXT DEFAULT '[]',
    draft_response    TEXT,
    referral_reason   TEXT,
    reviewer_note     TEXT,
    planner           TEXT
);
CREATE TABLE IF NOT EXISTS feedback_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ref     TEXT NOT NULL REFERENCES feedback(ref),
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    event   TEXT NOT NULL,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
"""

EDITABLE = {"language", "message", "distribution_id", "governorate", "partner", "item",
            "category", "category_reason", "priority", "priority_rule", "status", "restricted",
            "missing", "options", "draft_response", "referral_reason", "reviewer_note", "planner"}
ENUM_FIELDS = {"status": Status, "category": Category, "priority": Priority}
JSON_FIELDS = ("missing", "options")


class StoreError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path = "feedback.db") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row                 # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        d[f] = json.loads(d.get(f) or "[]")
    d["restricted"] = bool(d.get("restricted"))
    return d


def create_ticket(conn: sqlite3.Connection, sub: Submission, actor: str | None = None) -> dict:
    """Insert feedback and give it a readable, unique reference (FB-0001, FB-0002...).
    The number comes from SQLite's AUTOINCREMENT inside one transaction,
    so two submissions can never get the same reference."""
    now = _now()
    dst = sub.distribution_id or normalise_dst(sub.message)
    actor = actor or ("community" if sub.channel is Channel.WEB else f"operator:{sub.channel.value}")
    with conn:
        cur = conn.execute(
            "INSERT INTO feedback (created_at, updated_at, channel, person_ref, phone, message,"
            " distribution_id, governorate, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, sub.channel.value, sub.person_ref, sub.phone or None, sub.message, dst,
             sub.governorate or None, Status.NEW.value))
        ref = f"FB-{cur.lastrowid:04d}"
        conn.execute("UPDATE feedback SET ref = ? WHERE seq = ?", (ref, cur.lastrowid))
        conn.execute("INSERT INTO feedback_events (ref, at, actor, event, detail) VALUES (?, ?, ?, ?, ?)",
                     (ref, now, actor, "received", sub.channel.value))
    return get_ticket(conn, ref)


def get_ticket(conn: sqlite3.Connection, ref: str) -> dict | None:
    return _row(conn.execute("SELECT * FROM feedback WHERE ref = ?", (ref,)).fetchone())


def list_tickets(conn: sqlite3.Connection, status: str | None = None, priority: str | None = None,
                 category: str | None = None, partner: str | None = None,
                 include_restricted: bool = True) -> list[dict]:
    """Newest first. Filters are optional and always parameterised."""
    sql, args = "SELECT * FROM feedback WHERE 1=1", []
    for col, val in (("status", status), ("priority", priority), ("category", category), ("partner", partner)):
        if val:
            sql += f" AND {col} = ?"                # column names are fixed above, values are parameters
            args.append(val)
    if not include_restricted:
        sql += " AND restricted = 0"
    sql += " ORDER BY seq DESC"
    return [_row(r) for r in conn.execute(sql, args).fetchall()]


def update_ticket(conn: sqlite3.Connection, ref: str, actor: str, event: str,
                  detail: str | None = None, **fields: Any) -> dict:
    """Change fields AND record who did it, in one transaction."""
    unknown = set(fields) - EDITABLE
    if unknown:
        raise StoreError(f"Cannot edit field(s): {sorted(unknown)}")
    for name, enum in ENUM_FIELDS.items():
        if name in fields and fields[name] is not None:
            fields[name] = enum(fields[name]).value              # ValueError on a typo
    for f in JSON_FIELDS:
        if f in fields:
            fields[f] = json.dumps(list(fields[f] or []), ensure_ascii=False)
    if "restricted" in fields:
        fields["restricted"] = int(bool(fields["restricted"]))
    if get_ticket(conn, ref) is None:
        raise StoreError(f"Feedback {ref} not found.")

    now = _now()
    with conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE feedback SET {sets}, updated_at = ? WHERE ref = ?", (*fields.values(), now, ref))
        conn.execute("INSERT INTO feedback_events (ref, at, actor, event, detail) VALUES (?, ?, ?, ?, ?)",
                     (ref, now, actor, event, detail))
    return get_ticket(conn, ref)


def events_for(conn: sqlite3.Connection, ref: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT at, actor, event, detail FROM feedback_events WHERE ref = ? ORDER BY id", (ref,)).fetchall()]


def reset_all(conn: sqlite3.Connection) -> None:
    """Demo helper: delete every ticket and event (the dashboard asks for confirmation)."""
    with conn:
        conn.execute("DELETE FROM feedback_events")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('feedback', 'feedback_events')")


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Numbers for the dashboard header."""
    q = lambda sql: conn.execute(sql).fetchone()[0]
    open_ = "status NOT IN ('approved', 'closed')"
    return {
        "critical": q(f"SELECT COUNT(*) FROM feedback WHERE priority = 'Critical' AND {open_}"),
        "high": q(f"SELECT COUNT(*) FROM feedback WHERE priority = 'High' AND {open_}"),
        "waiting": q("SELECT COUNT(*) FROM feedback WHERE status = 'waiting_for_info'"),
        "drafts": q("SELECT COUNT(*) FROM feedback WHERE status IN ('draft_ready', 'needs_rework')"),
        "total": q("SELECT COUNT(*) FROM feedback"),
    }
