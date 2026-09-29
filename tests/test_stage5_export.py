"""Stage 5: the anonymised export for Project 1 (T14).

The export may be shared with partners and donors, so these tests look for
every piece of personal or sensitive data we put in, and make sure none of
it comes out.
"""
import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from feedback import agent
from feedback.export import COLUMNS, build_export, to_csv_bytes
from feedback.models import Submission
from feedback.store import connect

ROOT = Path(__file__).parent.parent
ROWS = [r for r in csv.DictReader(open(ROOT / "data" / "sample_feedback.csv", encoding="utf-8"))
        if r["expected_action"] != "reject_form"]
PHONE, NAME = "0599123456", "أم أحمد"


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "t.db")
    for r in ROWS:                                 # every sample, each with a name and a phone number
        agent.submit(conn, Submission(message=r["message"], channel=r["channel"], name=NAME, phone=PHONE))
    yield conn
    conn.close()


@pytest.fixture
def exported(db):
    return to_csv_bytes(build_export(db)).decode("utf-8-sig")


def test_T14_one_row_per_feedback_with_fixed_columns(db):
    df = build_export(db)
    assert list(df.columns) == COLUMNS and len(df) == len(ROWS)


def test_T14_no_names_phones_or_message_text(exported):
    assert PHONE not in exported and NAME not in exported
    for r in ROWS:
        assert r["message"] not in exported
    for word in ["استلمت", "received", "الموظف", "staff"]:          # no fragments of messages either
        assert word not in exported


def test_T14_sensitive_rows_keep_only_date_and_category(db, exported):
    df = build_export(db)
    sensitive = df[df["category"] == "sensitive"]
    assert len(sensitive) == 7
    for _, row in sensitive.iterrows():
        filled = {c for c in COLUMNS if pd.notna(row[c]) and row[c] != ""}
        assert filled == {"date", "category"}
    for code in ["psea", "fraud", "threat", "self_harm", "safety", "third_party_data", "Critical", "referred"]:
        assert code not in exported


def test_distribution_facts_come_from_project_1_data(db):
    df = build_export(db).set_index("reference")
    assert df.loc["FB-0001", ["distribution_id", "distribution_status", "partner"]].tolist() == \
        ["DST-017", "Completed", "Sanad Aid"]
    assert df.loc["FB-0005", "distribution_status"] == "Cancelled"


def test_a_wrong_distribution_number_is_never_exported(db):
    df = build_export(db)
    assert "DST-099" not in set(df["distribution_id"].dropna())


def test_days_open_stop_when_a_person_resolves_it(db):
    later = datetime.now(timezone.utc) + timedelta(days=10)
    agent.approve(db, "FB-0001", "Aya")
    df = build_export(db, now=later).set_index("reference")
    assert df.loc["FB-0001", "days_open"] == 0 and df.loc["FB-0001", "overdue"] == "no"       # approved today
    assert df.loc["FB-0003", "days_open"] == 10 and df.loc["FB-0003", "overdue"] == "yes"     # M1: 7-day target


def test_arabic_survives_excel(db):
    raw = to_csv_bytes(build_export(db))
    assert raw.startswith(b"\xef\xbb\xbf")                         # BOM: Excel on Windows opens it as UTF-8


# --- the real handoff: Project 1 loads the file and answers questions -----------------------------
PROJECT1 = Path(os.environ.get("PROJECT1_PATH", ROOT.parent / "ai-data-analyst"))


@pytest.mark.skipif(not (PROJECT1 / "agent" / "data_loader.py").exists(),
                    reason="Project 1 (ai-data-analyst) is not next to this project; set PROJECT1_PATH")
def test_project_1_answers_questions_about_the_export(db):
    sys.path.insert(0, str(PROJECT1))
    from agent.agent import answer
    from agent.data_loader import load_csv
    data, profile = load_csv(to_csv_bytes(build_export(db)), "feedback_log.csv")
    res = answer("How many feedback per partner?", data, profile)
    assert res.kind == "answer"
    counts = dict(zip(res.result.table["partner"], res.result.table["rows"]))
    assert counts["Sanad Aid"] == 4 and counts["Nour Relief"] == 4
    assert answer("count by category", data, profile).result.table.iloc[0]["category"] == "distribution"
