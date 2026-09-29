"""
The feedback agent: one loop per message, plus the actions staff take.

    submit ─► ticket ─► safeguarding guardrail ─┬─ sensitive ─► REFER (Critical, restricted, no draft)
                                                └─ safe ─► classify ─► LOOKUP distribution ─► policy
                                                     ├─ distribution unclear ─► ASK (one question + options)
                                                     └─ clear / not needed ─► DRAFT (status-aware, needs approval)
    follow_up ─► the person's answer is added ─► the same loop runs again

Allowed actions (PROJECT_PLAN §7): classify_feedback, lookup_distribution,
ask_for_info, draft_response, refer_confidential, finish. Each is written to
the audit log.

The classifier and drafter are passed in as functions, so the Gemini
versions (stage 6) plug in without changing this loop. What an LLM can and
cannot change:
  * it can ADD a referral, never remove the guardrail's;
  * it never picks the distribution (the lookup tool does) or the priority;
  * its draft must pass check_draft() for the ticket's language and
    distribution, otherwise the template is used and the reason is logged.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from . import distributions, guardrail
from .classifier import Classification, classify as rule_classify
from .drafter import check_draft, question_for, template_draft
from .models import Category, DeliveryMethod, Status, normalise_dst
from .policy import assess, extract_facts
from .store import create_ticket, get_ticket, update_ticket
from .text import detect_language

Classifier = Callable[[str, str], Classification]
Drafter = Callable[..., "str | tuple[str, str]"]          # template -> str, LLM -> (text, who wrote it)

FOCAL_POINT = "focal_point"
OFFICER = "officer"

# Which staff action is allowed from which status (a small state machine).
ALLOWED = {
    "approve": {Status.DRAFT_READY, Status.NEEDS_REWORK, Status.REFERRED},
    "reject": {Status.DRAFT_READY},
    "refer": {Status.NEW, Status.WAITING_FOR_INFO, Status.DRAFT_READY, Status.NEEDS_REWORK},
    "close": set(Status) - {Status.CLOSED},
    "deliver": {Status.APPROVED},
    "no_answer": {Status.APPROVED},
}


class ActionError(Exception):
    """A staff action that is not allowed now, or not allowed for this role (shown in the UI)."""


@dataclass
class Outcome:
    ticket: dict
    action: str                                   # refer_confidential | ask_for_info | draft_response
    question: str | None = None
    options: list[str] = field(default_factory=list)


def submit(conn: sqlite3.Connection, sub, classifier: Classifier = rule_classify,
           drafter: Drafter = template_draft) -> Outcome:
    ticket = create_ticket(conn, sub)
    return process(conn, ticket["ref"], classifier, drafter)


def process(conn: sqlite3.Connection, ref: str, classifier: Classifier = rule_classify,
            drafter: Drafter = template_draft) -> Outcome:
    t = get_ticket(conn, ref)
    message = t["message"]
    lang = t["language"] or detect_language(message)             # fixed by the FIRST message

    # 1. safeguarding FIRST: a sensitive message never reaches the classifier LLM or the drafter
    ref_hit = guardrail.check(message)
    referral = (ref_hit.label, f"{ref_hit.code}: '{ref_hit.matched}'") if ref_hit else None

    # 2. classify (rules only for sensitive messages: nothing leaves the building)
    try:
        c = classifier(message, lang) if not referral else rule_classify(message, lang)
    except Exception as err:                                      # LLM down -> rules
        c = rule_classify(message, lang)
        c.planner = f"rules (fallback: {type(err).__name__})"
    update_ticket(conn, ref, "agent", "classify_feedback", c.planner,
                  language=lang, category=c.category, category_reason=c.reason, planner=c.planner)
    if not referral and c.refer:                                  # an LLM may ADD a referral, never remove one
        referral = (f"Flagged by the classifier: {c.refer_reason}", f"classifier_flag: {c.refer_reason}")

    if referral:
        label, detail = referral
        a = assess(c.category, extract_facts(message), referred=True)
        t = update_ticket(conn, ref, "agent", "refer_confidential", detail,
                          status=Status.REFERRED, category=Category.SENSITIVE, priority=a.priority,
                          category_reason=f"Referred by the guardrail: {label}",
                          priority_rule=f"{a.rule}: {a.rule_text}", restricted=True,
                          referral_reason=label, draft_response=None, missing=[], options=[])
        return Outcome(t, "refer_confidential")

    # 3. the TOOL: which distribution is this about? (facts from Project 1's file)
    # The id comes from the ticket field (set from the form or the first message, or
    # corrected by a follow-up answer), not re-read from the text.
    look = distributions.lookup(message, t["distribution_id"], t["governorate"], id_from_text=False)
    dist = look.distribution
    link = dict(distribution_id=dist["distribution_id"], governorate=dist["governorate"],
                partner=dist["partner"], item=dist["item"]) if dist else dict(
        governorate=look.hints.one("governorates") or t["governorate"],
        partner=look.hints.one("partners"), item=look.hints.one("items"))
    update_ticket(conn, ref, "agent", "lookup_distribution", look.summary(), **link)

    # 4. written policy
    a = assess(c.category, extract_facts(message), dist["status"] if dist else None,
               distribution_found=dist is not None)
    common = dict(priority=a.priority, priority_rule=f"{a.rule}: {a.rule_text}")

    # 5. act
    if a.missing:
        q, options = question_for(look, lang)
        t = update_ticket(conn, ref, "agent", "ask_for_info", q, status=Status.WAITING_FOR_INFO,
                          missing=a.missing, options=options, draft_response=None, **common)
        return Outcome(t, "ask_for_info", q, options)

    def template() -> str:
        return template_draft(message, c.category, a.rule, lang, look)

    try:
        out = drafter(message, c.category, a.rule, lang, look)
        draft, author = out if isinstance(out, tuple) else (out, "template")
        problems = check_draft(draft, lang, dist["distribution_id"] if dist else None)
        if problems:                                               # unsafe or wrong draft -> template, reason logged
            update_ticket(conn, ref, "agent", "draft_rejected_by_safety_check", f"{author}: {', '.join(problems)}")
            draft, author = template(), "template (LLM draft failed the safety check)"
    except Exception as err:
        update_ticket(conn, ref, "agent", "drafter_fallback", str(err)[:300] or type(err).__name__)
        draft, author = template(), f"template (fallback: {type(err).__name__})"

    t = update_ticket(conn, ref, "agent", "draft_response", f"drafted by: {author}", status=Status.DRAFT_READY,
                      draft_response=draft, missing=[], options=[], **common)
    return Outcome(t, "draft_response")


def follow_up(conn: sqlite3.Connection, ref: str, answer: str, classifier: Classifier = rule_classify,
              drafter: Drafter = template_draft) -> Outcome:
    """The person answers our one question (typed or an option picked): same ticket, processed again (T3)."""
    t = get_ticket(conn, ref)
    if t is None:
        raise ActionError(f"Feedback {ref} not found.")
    if t["status"] != Status.WAITING_FOR_INFO.value:
        raise ActionError("This feedback is not waiting for more information.")
    answer = (answer or "").strip()
    if len(answer) < 3:
        raise ActionError("Please type your answer. / اكتب جوابك.")
    fields = {"message": f"{t['message']}\n\n[Follow-up] {answer}"}
    # The answer wins: a new number replaces an old wrong one (DST-099); an answer
    # without a number ("blankets, North Gaza") clears it so place + item are used.
    fields["distribution_id"] = normalise_dst(answer)
    update_ticket(conn, ref, "community", "follow_up_answer", answer[:200], **fields)
    return process(conn, ref, classifier, drafter)


# --- staff actions --------------------------------------------------------------------------
def _guard(conn, ref: str, action: str, role: str) -> dict:
    t = get_ticket(conn, ref)
    if t is None:
        raise ActionError(f"Feedback {ref} not found.")
    if t["restricted"] and role != FOCAL_POINT:                     # confidentiality is enforced here, not only on screen
        raise ActionError("Restricted case: only the safeguarding focal point can act on it.")
    if Status(t["status"]) not in ALLOWED[action]:
        raise ActionError(f"Cannot {action} feedback that is '{t['status']}'.")
    return t


def approve(conn, ref: str, reviewer: str, edited_text: str | None = None, role: str = OFFICER) -> dict:
    """A person approves the reply (optionally edited). Only now is it a real reply."""
    t = _guard(conn, ref, "approve", role)
    text = (edited_text if edited_text is not None else t["draft_response"] or "").strip()
    if not text:
        raise ActionError("Write the reply before approving (referred cases have no AI draft).")
    edited = edited_text is not None and edited_text.strip() != (t["draft_response"] or "").strip()
    return update_ticket(conn, ref, f"{role}:{reviewer}", "edited_and_approved" if edited else "approved", None,
                         status=Status.APPROVED, draft_response=text)


def reject(conn, ref: str, reviewer: str, reason: str, role: str = OFFICER) -> dict:
    _guard(conn, ref, "reject", role)
    if not (reason or "").strip():
        raise ActionError("Please give a reason, so the draft can be improved.")
    return update_ticket(conn, ref, f"{role}:{reviewer}", "rejected", reason.strip(),
                         status=Status.NEEDS_REWORK, reviewer_note=reason.strip())


def refer(conn, ref: str, reviewer: str, reason: str, role: str = OFFICER) -> dict:
    """An officer can always hand a case to the focal point; afterwards they can no longer read it."""
    _guard(conn, ref, "refer", role)
    if not (reason or "").strip():
        raise ActionError("Please say why this needs the safeguarding focal point.")
    return update_ticket(conn, ref, f"{role}:{reviewer}", "referred_by_staff", reason.strip(),
                         status=Status.REFERRED, category=Category.SENSITIVE, priority="Critical",
                         priority_rule="S1: Confidential referral", restricted=True,
                         referral_reason=reason.strip(), draft_response=None)


def close(conn, ref: str, reviewer: str, note: str = "", role: str = OFFICER) -> dict:
    _guard(conn, ref, "close", role)
    return update_ticket(conn, ref, f"{role}:{reviewer}", "closed", note or None, status=Status.CLOSED)


# --- closing the feedback loop: the person must actually hear the answer ----------------------
def deliver(conn, ref: str, staff: str, method: str, role: str = OFFICER) -> dict:
    """Record that the person received the approved reply (call-back, in person, confidential contact)."""
    t = _guard(conn, ref, "deliver", role)
    method = DeliveryMethod(method)
    if t["restricted"] and method is not DeliveryMethod.CONFIDENTIAL:
        raise ActionError("Referred cases are answered only by confidential contact.")
    return update_ticket(conn, ref, f"{role}:{staff}", "reply_delivered", method.value,
                         status=Status.DELIVERED, delivered_via=method)


def no_answer(conn, ref: str, staff: str, note: str = "", role: str = OFFICER) -> dict:
    """A call-back that did not reach the person: logged, the reply stays waiting to be delivered."""
    _guard(conn, ref, "no_answer", role)
    return update_ticket(conn, ref, f"{role}:{staff}", "call_attempt_no_answer", note or None)


def call_attempts(conn, ref: str) -> int:
    from .store import events_for
    return sum(e["event"] == "call_attempt_no_answer" for e in events_for(conn, ref))
