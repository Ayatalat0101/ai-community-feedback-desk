"""Stage 3: the distribution lookup tool, rule classifier, status-aware drafts and the agent loop.

Every valid sample row runs through the REAL agent against a temporary database
and must produce its expected category, priority, action and distribution.
"""
import csv
from pathlib import Path

import pytest

from feedback import agent, distributions
from feedback.agent import FOCAL_POINT, ActionError
from feedback.classifier import classify
from feedback.drafter import BODY, check_draft
from feedback.models import Submission
from feedback.store import connect, events_for, get_ticket

ROWS = {r["id"]: r for r in csv.DictReader(open(Path(__file__).parent.parent / "data" / "sample_feedback.csv",
                                                 encoding="utf-8"))}
VALID = [r for r in ROWS.values() if r["expected_action"] != "reject_form"]


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "t.db")
    yield conn
    conn.close()


def send(db, row_id=None, message=None, **kw):
    return agent.submit(db, Submission(message=message or ROWS[row_id]["message"], **kw))


# --- the whole sample file through the real loop --------------------------------------------
@pytest.mark.parametrize("row", VALID, ids=[r["id"] for r in VALID])
def test_every_sample_gets_the_expected_outcome(db, row):
    out = send(db, row["id"])
    t = out.ticket
    assert out.action == {"escalate": "refer_confidential"}.get(row["expected_action"], row["expected_action"])
    assert t["priority"] == row["expected_priority"], t["priority_rule"]
    assert t["category"] == row["expected_category"]
    if row["expected_action"] == "draft_response" and row["expected_distribution"]:
        assert t["distribution_id"] == row["expected_distribution"]


# --- the lookup tool ------------------------------------------------------------------------
@pytest.mark.parametrize("text, gov, item, partner", [
    ("بطانيات بالشمال", "North Gaza", "Blanket", None),
    ("blankets in North Gaza from Nour", "North Gaza", "Blanket", "Nour Relief"),
    ("طقم مطبخ من سند في رفح", "Rafah", "Kitchen Set", "Sanad Aid"),
    ("الكرتونة في خانيونس", "Khan Younis", "Food Parcel", None),
    ("حقيبة شتوية دير البلح", "Deir al-Balah", "Winter Kit", None),
])
def test_names_in_arabic_dialect_and_english_are_recognised(text, gov, item, partner):
    h = distributions.extract_hints(text)
    assert h.governorates == [gov] and h.items == [item]
    assert h.one("partners") == partner


def test_bare_gaza_is_not_guessed_as_gaza_city():
    assert distributions.extract_hints("توزيع في شمال غزة").governorates == ["North Gaza"]
    assert distributions.extract_hints("أنا من غزة").governorates == []


def test_lookup_never_invents_a_distribution():
    df = distributions.load()
    for text in ["بطانيات في شمال غزة", "طرد غذائي في رفح", "blankets Rafah Nour"]:
        for m in distributions.lookup(text).matches:
            assert m["distribution_id"] in set(df["distribution_id"])


def test_lookup_outcomes():
    assert distributions.lookup("DST-017").outcome == "found"
    assert distributions.lookup("DST-099").outcome == "not_found_id"
    assert distributions.lookup("بطانيات شمال غزة").outcome == "multiple"
    assert distributions.lookup("بطانيات شمال غزة نور مارس").outcome == "multiple"       # DST-019 + DST-029
    assert distributions.lookup("حقيبة نظافة في شمال غزة").outcome == "no_match"
    assert distributions.lookup("ما استلمت شي").outcome == "no_info"


def test_when_is_the_next_one_prefers_planned_distributions():
    look = distributions.lookup("متى توزيع طرد الغذاء الجاي في دير البلح؟")
    assert look.outcome == "found" and look.distribution["distribution_id"] == "DST-048"


# --- T1-T5 ----------------------------------------------------------------------------------------
def test_T1_not_received_from_a_completed_distribution(db):
    t = send(db, "F01").ticket
    assert (t["distribution_id"], t["partner"], t["priority"]) == ("DST-017", "Sanad Aid", "High")
    assert t["priority_rule"].startswith("H1") and "مؤسسة سند" in t["draft_response"]
    assert "مراجعة كشف" in t["draft_response"]


def test_T2_several_matches_ask_one_question_with_real_options(db):
    out = send(db, "F02")
    assert out.action == "ask_for_info" and out.ticket["status"] == "waiting_for_info"
    assert [o.split(" · ")[0] for o in out.options] == ["DST-019", "DST-029", "DST-053", "DST-055", "DST-060"]
    assert out.question.startswith("يوجد 5 توزيعات") and out.ticket["draft_response"] is None


def test_T3_picking_an_option_continues_the_same_ticket(db):
    out = send(db, "F02")
    out2 = agent.follow_up(db, out.ticket["ref"], out.options[1])           # "DST-029 · نور للإغاثة · ..."
    t = out2.ticket
    assert t["ref"] == out.ticket["ref"] and out2.action == "draft_response"
    assert (t["distribution_id"], t["priority"]) == ("DST-029", "High")      # completed + not received -> H1
    assert "[Follow-up]" in t["message"]


def test_T4_cancelled_distribution_is_explained_without_a_promise(db):
    t = send(db, "F05").ticket
    assert t["priority_rule"].startswith("M1") and "was cancelled" in t["draft_response"]
    assert check_draft(t["draft_response"], "en", "DST-001") == []


def test_T5_unknown_number_asks_to_check_it_and_a_correction_works(db):
    out = send(db, "F19")
    assert out.action == "ask_for_info" and "DST-099" in out.question
    out2 = agent.follow_up(db, out.ticket["ref"], "آسف الرقم الصحيح DST-017")
    assert out2.ticket["distribution_id"] == "DST-017" and out2.action == "draft_response"


def test_correction_without_a_number_uses_place_and_item(db):
    out = send(db, "F19")
    out2 = agent.follow_up(db, out.ticket["ref"], "طرد الغذاء برفح من سند")
    assert out2.action == "ask_for_info" and out2.ticket["distribution_id"] is None     # several Sanad parcels in Rafah
    assert "DST-099" not in out2.question


def test_follow_up_only_when_waiting(db):
    t = send(db, "F01").ticket
    with pytest.raises(ActionError):
        agent.follow_up(db, t["ref"], "DST-017")


# --- T10 + language ------------------------------------------------------------------------------
@pytest.mark.parametrize("row_id, lang, words", [
    ("F04", "ar", "التوزيع القادم"), ("F20", "en", "has not taken place yet"),
    ("F17", "en", "Hygiene Kit"), ("F25", "ar", "طرد غذائي")])
def test_T10_reply_is_in_the_language_of_the_feedback(db, row_id, lang, words):
    t = send(db, row_id).ticket
    assert t["language"] == lang and words in t["draft_response"]
    assert check_draft(t["draft_response"], lang, t["distribution_id"]) == []


def test_arabic_follow_up_question_stays_arabic_after_an_english_answer(db):
    out = send(db, "F16")
    assert out.question.startswith("عن أي توزيع")
    out2 = agent.follow_up(db, out.ticket["ref"], "DST-059")
    assert out2.ticket["language"] == "ar" and "مع الاحترام" in out2.ticket["draft_response"]


# --- referrals ------------------------------------------------------------------------------------
@pytest.mark.parametrize("row_id", ["F09", "F10", "F11", "F12", "F13", "F14", "F15"])
def test_T6_T7_T8_referrals_have_no_draft_and_are_restricted(db, row_id):
    t = send(db, row_id).ticket
    assert (t["status"], t["priority"], t["category"], t["restricted"]) == ("referred", "Critical", "sensitive", True)
    assert t["draft_response"] is None


def test_T7_sensitive_message_never_reaches_the_classifier(db):
    calls = []
    def spy(message, lang):
        calls.append(message)
        return classify(message, lang)
    agent.submit(db, Submission(message=ROWS["F10"]["message"]), classifier=spy)
    assert calls == []


def test_confidentiality_is_enforced_in_the_agent_not_only_on_screen(db):
    ref = send(db, "F09").ticket["ref"]
    with pytest.raises(ActionError, match="focal point"):
        agent.close(db, ref, "Aya")                                           # officer role
    t = agent.approve(db, ref, "Mona", "سنتواصل معك هاتفياً بسرية.", role=FOCAL_POINT)
    assert t["status"] == "approved" and events_for(db, ref)[-1]["actor"] == "focal_point:Mona"


def test_officer_can_refer_but_then_loses_access(db):
    ref = send(db, "F06").ticket["ref"]
    agent.refer(db, ref, "Aya", "She told me on the phone that he also touched her")
    assert get_ticket(db, ref)["restricted"] is True
    with pytest.raises(ActionError, match="focal point"):
        agent.approve(db, ref, "Aya", edited_text="Any reply text")


# --- T13 + staff actions -----------------------------------------------------------------------------
def test_T13_approve_and_reject(db):
    a = send(db, "F03").ticket["ref"]
    assert agent.approve(db, a, "Aya")["status"] == "approved"
    b = send(db, "F17").ticket["ref"]
    with pytest.raises(ActionError):
        agent.reject(db, b, "Aya", "")
    t = agent.reject(db, b, "Aya", "Mention the replacement process")
    assert t["status"] == "needs_rework" and events_for(db, b)[-1]["detail"] == "Mention the replacement process"


def test_edit_and_approve_is_logged_differently(db):
    ref = send(db, "F08").ticket["ref"]
    agent.approve(db, ref, "Aya", edited_text="شكراً جزيلاً، سننقل كلامك لفريق سند.")
    assert events_for(db, ref)[-1]["event"] == "edited_and_approved"


def test_every_step_is_in_the_audit_log(db):
    ref = send(db, "F01").ticket["ref"]
    assert [e["event"] for e in events_for(db, ref)] == [
        "received", "classify_feedback", "lookup_distribution", "draft_response"]
    assert events_for(db, ref)[2]["detail"] == "found DST-017 (Completed)"


# --- T15 (rules part) + the safety check ----------------------------------------------------------------
def test_classifier_failure_falls_back_to_rules(db):
    def down(message, lang):
        raise TimeoutError("LLM down")
    t = agent.submit(db, Submission(message=ROWS["F25"]["message"]), classifier=down).ticket
    assert t["category"] == "distribution" and t["planner"].startswith("rules (fallback")


def test_unsafe_draft_is_replaced_by_the_template(db):
    bad = lambda *a: "مرحباً، سنعطيك طرد جديد بكرة. ارسل لنا رقم الهوية."
    t = agent.submit(db, Submission(message=ROWS["F25"]["message"]), drafter=bad).ticket
    assert t["draft_response"] != bad() and "نأسف للمشكلة" in t["draft_response"]
    rejected = [e for e in events_for(db, t["ref"]) if e["event"] == "draft_rejected_by_safety_check"]
    assert "promises aid" in rejected[0]["detail"] and "asks for ID" in rejected[0]["detail"]


@pytest.mark.parametrize("key", list(BODY))
@pytest.mark.parametrize("lang", ["ar", "en"])
def test_every_template_passes_the_safety_check(key, lang):
    text = BODY[key][lang].format(dst="DST-017", partner="P", item="I", gov="G", date="2026-02-10",
                                  partner_or_team="P")
    assert check_draft(text) == [] and check_draft(text, lang, "DST-017") == []
