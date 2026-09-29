"""Stage 1: form validation (T11) and the SQLite feedback store (T12 + audit log)."""
import csv
from pathlib import Path

import pytest

from feedback.models import MSG_DST, MSG_SHORT, Channel, Status, Submission, normalise_dst, validate_form
from feedback.store import (StoreError, connect, counts, create_ticket, events_for, get_ticket,
                            list_tickets, reset_all, update_ticket)

ROWS = list(csv.DictReader(open(Path(__file__).parent.parent / "data" / "sample_feedback.csv", encoding="utf-8")))


@pytest.fixture
def db(tmp_path):
    """A brand-new database file for every test: tests never share state."""
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def sub(message="ما استلمت طرد الغذاء بتوزيع DST-017 برفح", **kw):
    return Submission(message=message, **kw)


# --- T11: invalid forms never create a ticket -------------------------------------
@pytest.mark.parametrize("row", [r for r in ROWS if r["expected_action"] == "reject_form"], ids=lambda r: r["id"])
def test_T11_sample_invalid_forms_are_rejected(row):
    s, errors = validate_form(message=row["message"])
    assert s is None and errors["message"] == MSG_SHORT


@pytest.mark.parametrize("row", [r for r in ROWS if r["expected_action"] != "reject_form"], ids=lambda r: r["id"])
def test_every_valid_sample_passes_validation(row):
    s, errors = validate_form(message=row["message"], channel=row["channel"])
    assert errors == {} and s.channel.value == row["channel"]


def test_error_message_is_bilingual():
    assert "اكتب ما حدث" in MSG_SHORT and "Please describe" in MSG_SHORT


def test_long_message_rejected():
    _, errors = validate_form(message="x" * 2001)
    assert "under 2000" in errors["message"]


@pytest.mark.parametrize("phone, ok", [("0591234567", True), ("+970 59 123 4567", True), ("", True),
                                       ("12", False), ("call me", False)])
def test_phone_format(phone, ok):
    s, errors = validate_form(message="ما استلمت من التوزيع شي", phone=phone)
    assert (s is not None) == ok and ("phone" in errors) != ok


@pytest.mark.parametrize("raw, expected", [("DST-017", "DST-017"), ("dst 017", "DST-017"), ("DST017", "DST-017")])
def test_distribution_id_is_normalised(raw, expected):
    s, _ = validate_form(message="ما استلمت من التوزيع شي", distribution_id=raw)
    assert s.distribution_id == expected


@pytest.mark.parametrize("raw", ["DST-17", "017", "XX-017", "DST-0170"])
def test_bad_distribution_id_rejected(raw):
    _, errors = validate_form(message="ما استلمت من التوزيع شي", distribution_id=raw)
    assert errors["distribution_id"] == MSG_DST


def test_governorate_must_be_one_from_the_data():
    assert validate_form(message="ما استلمت من التوزيع شي", governorate="Rafah")[0] is not None
    assert "governorate" in validate_form(message="ما استلمت من التوزيع شي", governorate="Jenin")[1]


def test_unknown_channel_rejected():
    assert "channel" in validate_form(message="ما استلمت من التوزيع شي", channel="fax")[1]


def test_distribution_id_found_inside_arabic_text():
    assert normalise_dst("الكرتونة وصلت مبلولة من توزيع DST-059") == "DST-059"


def test_feedback_without_a_name_gets_an_anonymous_reference():
    assert sub().person_ref.startswith("anon-")
    assert sub(name="أم أحمد").person_ref == "أم أحمد"


# --- T12: distinct references, persisted across restarts ----------------------------
def test_T12_references_are_distinct_and_sequential(db):
    a, b = create_ticket(db, sub()), create_ticket(db, sub("متى توزيع الطرود الجاي في دير البلح؟"))
    assert (a["ref"], b["ref"]) == ("FB-0001", "FB-0002")
    assert a["status"] == Status.NEW.value and a["restricted"] is False


def test_T12_feedback_survives_an_app_restart(tmp_path):
    path = tmp_path / "persist.db"
    conn = connect(path)
    t = create_ticket(conn, sub())
    conn.close()                                          # "restart the app"
    conn2 = connect(path)
    assert get_ticket(conn2, t["ref"])["message"] == t["message"]
    assert create_ticket(conn2, sub("بعد إعادة التشغيل العداد يكمل"))["ref"] == "FB-0002"


def test_distribution_id_extracted_from_message(db):
    assert create_ticket(db, sub("الطحين خربان من توزيع dst 059 والله"))["distribution_id"] == "DST-059"


def test_channel_decides_who_is_recorded_as_sender(db):
    web = create_ticket(db, sub())
    call = create_ticket(db, sub(channel=Channel.HOTLINE))
    assert events_for(db, web["ref"])[0]["actor"] == "community"
    assert events_for(db, call["ref"])[0]["actor"] == "operator:hotline"


# --- audit log and safe updates -------------------------------------------------------
def test_every_change_is_logged(db):
    t = create_ticket(db, sub())
    update_ticket(db, t["ref"], "agent", "classify_feedback", "rules", category="distribution",
                  priority="High", status="draft_ready")
    update_ticket(db, t["ref"], "officer:Aya", "approved", status="approved")
    ev = events_for(db, t["ref"])
    assert [e["event"] for e in ev] == ["received", "classify_feedback", "approved"]
    assert ev[-1]["actor"] == "officer:Aya"


def test_invalid_status_or_priority_is_refused(db):
    t = create_ticket(db, sub())
    with pytest.raises(ValueError):
        update_ticket(db, t["ref"], "agent", "x", status="Referred")          # typo -> crash, not a lost case
    with pytest.raises(ValueError):
        update_ticket(db, t["ref"], "agent", "x", priority="Urgent")
    assert get_ticket(db, t["ref"])["status"] == "new"


def test_history_and_identity_fields_cannot_be_edited(db):
    t = create_ticket(db, sub(phone="0591234567"))
    for field in ("created_at", "channel", "person_ref", "phone"):
        with pytest.raises(StoreError, match=field):
            update_ticket(db, t["ref"], "agent", "x", **{field: "changed"})
    with pytest.raises(StoreError):
        update_ticket(db, "FB-9999", "agent", "x", status="closed")


def test_sql_injection_is_stored_as_text(db):
    evil = "Robert'); DROP TABLE feedback; -- ما استلمت"
    t = create_ticket(db, sub(evil))
    assert get_ticket(db, t["ref"])["message"] == evil
    assert len(list_tickets(db)) == 1


def test_restricted_cases_can_be_left_out_of_a_list(db):
    a = create_ticket(db, sub())
    b = create_ticket(db, sub("موظف طلب مني مصاري عشان يسجلني"))
    update_ticket(db, b["ref"], "agent", "refer_confidential", status="referred",
                  priority="Critical", restricted=True, category="sensitive")
    assert [t["ref"] for t in list_tickets(db)] == [b["ref"], a["ref"]]        # newest first
    assert [t["ref"] for t in list_tickets(db, include_restricted=False)] == [a["ref"]]


def test_filters_and_counts(db):
    a = create_ticket(db, sub())
    create_ticket(db, sub("متى التوزيع الجاي في رفح؟"))
    update_ticket(db, a["ref"], "agent", "x", status="draft_ready", priority="High", partner="Sanad Aid")
    assert [t["ref"] for t in list_tickets(db, partner="Sanad Aid")] == [a["ref"]]
    c = counts(db)
    assert (c["total"], c["high"], c["drafts"], c["critical"]) == (2, 1, 1, 0)


def test_lists_round_trip_and_arabic_is_kept(db):
    t = create_ticket(db, sub())
    t = update_ticket(db, t["ref"], "agent", "ask", status="waiting_for_info", missing=["distribution"],
                      options=["DST-029 · نور للإغاثة", "DST-053"])
    assert t["missing"] == ["distribution"] and t["options"][0] == "DST-029 · نور للإغاثة"


def test_reset_all_restarts_numbering(db):
    create_ticket(db, sub())
    reset_all(db)
    assert list_tickets(db) == [] and create_ticket(db, sub())["ref"] == "FB-0001"
