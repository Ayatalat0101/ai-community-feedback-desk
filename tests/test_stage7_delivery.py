"""Stage 7: closing the feedback loop. The person must actually hear the answer.

  approved ─► delivered (call-back / in person / read online / confidential contact)
Plus "Track my feedback": what a person may see, and who may see it.
"""
import csv
import sqlite3
from pathlib import Path

import pytest

from feedback import agent
from feedback.agent import FOCAL_POINT, ActionError, call_attempts
from feedback.customer_view import person_view, phone_matches
from feedback.export import build_export
from feedback.models import Submission
from feedback.store import connect, events_for, get_ticket

ROWS = {r["id"]: r for r in csv.DictReader(open(Path(__file__).parent.parent / "data" / "sample_feedback.csv",
                                                 encoding="utf-8"))}
PHONE = "0591234567"


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "t.db")
    yield conn
    conn.close()


def send(db, row_id, phone=PHONE):
    return agent.submit(db, Submission(message=ROWS[row_id]["message"], channel=ROWS[row_id]["channel"], phone=phone))


def approved(db, row_id="F01", **kw):
    ref = send(db, row_id, **kw).ticket["ref"]
    agent.approve(db, ref, "Aya")
    return ref


# --- delivery ------------------------------------------------------------------------------------
def test_approved_is_not_the_end_until_delivered(db):
    ref = approved(db)
    assert get_ticket(db, ref)["status"] == "approved"
    t = agent.deliver(db, ref, "Hiba", "phone_call")
    assert (t["status"], t["delivered_via"]) == ("delivered", "phone_call")
    assert events_for(db, ref)[-1]["actor"] == "officer:Hiba"


def test_unanswered_calls_are_logged_and_the_reply_stays_on_the_list(db):
    ref = approved(db)
    agent.no_answer(db, ref, "Hiba")
    agent.no_answer(db, ref, "Hiba", "phone off")
    assert call_attempts(db, ref) == 2 and get_ticket(db, ref)["status"] == "approved"


def test_only_approved_replies_can_be_delivered(db):
    ref = send(db, "F01").ticket["ref"]                            # still a draft
    with pytest.raises(ActionError, match="draft_ready"):
        agent.deliver(db, ref, "Hiba", "phone_call")
    with pytest.raises(ValueError):
        agent.deliver(db, approved(db, "F03"), "Hiba", "carrier_pigeon")


def test_referred_cases_are_answered_only_by_the_focal_point_confidentially(db):
    ref = send(db, "F09").ticket["ref"]
    agent.approve(db, ref, "Mona", "سنتواصل معك هاتفياً بسرية.", role=FOCAL_POINT)
    with pytest.raises(ActionError, match="focal point"):
        agent.deliver(db, ref, "Hiba", "phone_call")                # officer
    with pytest.raises(ActionError, match="confidential"):
        agent.deliver(db, ref, "Mona", "phone_call", role=FOCAL_POINT)
    assert agent.deliver(db, ref, "Mona", "confidential", role=FOCAL_POINT)["status"] == "delivered"


def test_a_delivered_reply_can_still_be_closed(db):
    ref = approved(db)
    agent.deliver(db, ref, "Hiba", "in_person")
    assert agent.close(db, ref, "Aya")["status"] == "closed"


# --- Track my feedback ----------------------------------------------------------------------------
@pytest.mark.parametrize("given, ok", [("0591234567", True), ("+970 59 123 4567", True),
                                       ("0599999999", False), ("", False)])
def test_phone_matching(given, ok):
    assert phone_matches(given, PHONE) is ok


def test_reference_alone_is_not_enough_and_errors_look_the_same(db):
    ref = send(db, "F01").ticket["ref"]
    assert person_view(db, ref, "") is None
    assert person_view(db, ref, "0599999999") is None
    assert person_view(db, "FB-9999", PHONE) is None
    assert person_view(db, ref.lower(), "+970 59 123 4567").ref == ref


def test_draft_is_never_shown_before_approval(db):
    t = send(db, "F01").ticket
    v = person_view(db, t["ref"], PHONE)
    assert t["draft_response"] and v.reply is None and v.state == "reviewing"


def test_reading_the_approved_reply_online_counts_as_delivery_once(db):
    ref = approved(db)
    v = person_view(db, ref, PHONE)
    assert v.state == "answered" and "مراجعة كشف" in v.reply
    assert get_ticket(db, ref)["delivered_via"] == "web"
    person_view(db, ref, PHONE)
    assert sum(e["event"] == "reply_delivered" for e in events_for(db, ref)) == 1


def test_person_sees_the_question_and_options_in_their_language(db):
    v = person_view(db, send(db, "F02").ticket["ref"], PHONE)
    assert v.state == "waiting" and v.question.startswith("يوجد 5") and len(v.options) == 5
    assert v.status_text == "نحتاج منك معلومة واحدة لنكمل."


def test_english_feedback_gets_english_status(db):
    assert person_view(db, approved(db, "F17"), PHONE).status_text == "Our team has replied."


def test_referred_case_shows_no_reply_even_after_approval(db):
    ref = send(db, "F10").ticket["ref"]
    agent.approve(db, ref, "Mona", "نص الرد السري", role=FOCAL_POINT)
    v = person_view(db, ref, PHONE)
    assert v.state == "confidential" and v.reply is None and "بشكل سري" in v.status_text
    assert get_ticket(db, ref)["status"] == "approved"             # not auto-delivered by a web visit


def test_rejection_reason_and_internal_fields_are_never_shown(db):
    ref = send(db, "F03").ticket["ref"]
    agent.reject(db, ref, "Aya", "too vague for the partner")
    v = person_view(db, ref, PHONE)
    assert v.state == "reviewing" and "vague" not in str(vars(v))


# --- export + upgrade ------------------------------------------------------------------------------
def test_export_shows_whether_the_answer_reached_the_person(db):
    a, b = approved(db, "F01"), approved(db, "F03")
    agent.deliver(db, a, "Hiba", "phone_call")
    df = build_export(db).set_index("reference")
    assert df.loc[a, ["reply_delivered", "delivered_via"]].tolist() == ["yes", "phone_call"]
    assert df.loc[b, "reply_delivered"] == "no"


def test_an_old_database_is_upgraded_not_broken(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)                                     # the stage 1-6 schema, without delivered_via
    old.executescript("CREATE TABLE feedback (seq INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, "
                      "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, channel TEXT NOT NULL, person_ref TEXT "
                      "NOT NULL, phone TEXT, language TEXT, message TEXT NOT NULL, distribution_id TEXT, governorate "
                      "TEXT, partner TEXT, item TEXT, category TEXT, category_reason TEXT, priority TEXT, "
                      "priority_rule TEXT, status TEXT NOT NULL, restricted INTEGER NOT NULL DEFAULT 0, missing "
                      "TEXT DEFAULT '[]', options TEXT DEFAULT '[]', draft_response TEXT, referral_reason TEXT, "
                      "reviewer_note TEXT, planner TEXT);"
                      "INSERT INTO feedback (ref, created_at, updated_at, channel, person_ref, message, status) "
                      "VALUES ('FB-0001', '2026-09-01T10:00:00+00:00', '2026-09-01T10:00:00+00:00', 'web', 'anon', "
                      "'old feedback text', 'approved');")
    old.commit()
    old.close()
    conn = connect(path)
    assert get_ticket(conn, "FB-0001")["message"] == "old feedback text"
    assert get_ticket(conn, "FB-0001")["delivered_via"] is None
