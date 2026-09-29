"""
What a person may see about their own feedback ("Track my feedback").

Access: the reference alone is not enough (FB-0001, FB-0002... are easy to
guess). The person must also give the phone number they left, or the feedback
must have been sent from this browser session. A missing reference and a wrong
phone get the SAME answer, so the page cannot be used to discover references.

Content, in the language of the feedback:
  * a plain status and the question we asked, if any;
  * the reply ONLY after a person approved it;
  * never the category, priority, partner notes, reviewer notes or an AI draft;
  * a referred (sensitive) case shows only that a trained person will make
    contact: its reply is given confidentially, never on a web page.
Reading an approved reply here counts as delivery (method "web").
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from .models import DeliveryMethod, Status
from .store import events_for, get_ticket, update_ticket

APPROVAL_EVENTS = {"approved", "edited_and_approved"}

STATUS_TEXT = {
    "received": {"ar": "استلمنا ملاحظتك.", "en": "We have received your feedback."},
    "reviewing": {"ar": "فريقنا يراجع ملاحظتك وسيرد عليك.", "en": "Our team is reviewing your feedback and will reply."},
    "waiting": {"ar": "نحتاج منك معلومة واحدة لنكمل.", "en": "We need one more detail from you to continue."},
    "confidential": {"ar": "سيتواصل معك أحد أفراد فريقنا المدرَّبين بشكل سري.",
                     "en": "A trained member of our team will contact you confidentially."},
    "answered": {"ar": "رد فريقنا على ملاحظتك.", "en": "Our team has replied."},
    "closed": {"ar": "أُغلقت هذه الملاحظة.", "en": "This feedback is closed."},
}


@dataclass
class PersonView:
    ref: str
    language: str
    state: str
    status_text: str
    question: str | None = None
    options: list[str] = field(default_factory=list)
    reply: str | None = None


def _phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")[-9:]          # 059... and +970 59... are the same number


def phone_matches(given: str, stored: str) -> bool:
    g, s = _phone(given), _phone(stored)
    return len(g) >= 7 and g == s


def approved_reply(conn: sqlite3.Connection, t: dict) -> str | None:
    """The reply, only if a person approved it (a case closed from 'draft_ready' holds an unapproved draft)."""
    if any(e["event"] in APPROVAL_EVENTS for e in events_for(conn, t["ref"])):
        return t["draft_response"]
    return None


def person_view(conn: sqlite3.Connection, ref: str, phone: str = "", trusted: bool = False,
                record_delivery: bool = True) -> PersonView | None:
    """None when the reference does not exist OR the phone does not match (same answer for both)."""
    t = get_ticket(conn, (ref or "").strip().upper())
    if t is None or not (trusted or phone_matches(phone, t["phone"] or "")):
        return None
    lang = t["language"] if t["language"] in ("ar", "en") else "ar"
    status = t["status"]
    if t["restricted"]:
        state, reply = "confidential", None
    else:
        reply = approved_reply(conn, t)
        if status == Status.WAITING_FOR_INFO.value:
            state = "waiting"
        elif reply:
            state = "answered"
        elif status == Status.CLOSED.value:
            state = "closed"
        elif status == Status.NEW.value:
            state = "received"
        else:
            state = "reviewing"                            # draft_ready / needs_rework: internal work
    view = PersonView(t["ref"], lang, state, STATUS_TEXT[state][lang], reply=reply)
    if state == "waiting":
        view.question = next((e["detail"] for e in reversed(events_for(conn, t["ref"]))
                              if e["event"] == "ask_for_info"), None)
        view.options = t["options"]
    if reply and record_delivery and status == Status.APPROVED.value:
        update_ticket(conn, t["ref"], "community", "reply_delivered", DeliveryMethod.WEB.value,
                      status=Status.DELIVERED, delivered_via=DeliveryMethod.WEB)
    return view
