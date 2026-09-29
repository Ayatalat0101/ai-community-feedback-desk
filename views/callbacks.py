"""
Call-back list: closing the feedback loop.

An approved reply is not the end. Most people in this context gave feedback
by phone or in person and will never open a web page, so a hotline operator
calls them back, reads the approved reply, and records the result:
  ✅ delivered (by call, or in person)   → status "delivered"
  📵 no answer                            → logged; it stays on the list
Referred cases appear only for the safeguarding focal point, who records a
confidential contact. Feedback without a phone number waits for the person
to read it on "Track my feedback".
"""
import streamlit as st

from feedback import agent
from feedback.agent import FOCAL_POINT, ActionError, call_attempts
from feedback.store import list_tickets
from ui import CHANNEL_LABEL, CSS, PRIORITY_ICON, PRIORITY_RANK, ROLE_LABEL, get_conn, role_picker, show_text

st.markdown(CSS, unsafe_allow_html=True)
conn = get_conn()
role = role_picker()
staff = st.sidebar.text_input("Your name", value="Aya", max_chars=40, key="cb_name").strip() or "Staff"

st.title("📞 Call-back list")
st.caption(f"Viewing as **{ROLE_LABEL[role]}**. Approved replies the person has not heard yet: call, read the "
           "reply, and record what happened. The export for Project 1 counts how many replies were delivered.")

approved = [t for t in list_tickets(conn, status="approved") if t["restricted"] == (role == FOCAL_POINT)]
approved.sort(key=lambda t: (PRIORITY_RANK.get(t["priority"], 4), t["created_at"]))
to_call = [t for t in approved if t["phone"]]
online_only = [t for t in approved if not t["phone"]]


def record(fn, ref, *args, done: str):
    try:
        fn(conn, ref, staff, *args, role=role)
        st.toast(done)
        st.rerun()
    except ActionError as err:
        st.error(str(err))


if not approved:
    st.success("Nothing to deliver. Every approved reply has reached the person.")

for t in to_call:
    with st.container(border=True):
        top = st.columns([3, 2])
        tries = call_attempts(conn, t["ref"])
        top[0].markdown(f"**{t['ref']}** · {PRIORITY_ICON.get(t['priority'], '')} {t['priority']} · "
                        f"{CHANNEL_LABEL.get(t['channel'], t['channel'])} · language: **{t['language']}**"
                        + (f" · 📵 {tries} unanswered call(s)" if tries else ""))
        top[1].markdown(f"☎️ **{t['phone']}** · {t['person_ref']}")
        show_text(t["draft_response"])
        b = st.columns(3)
        if role == FOCAL_POINT:
            if b[0].button("🔒 Contacted confidentially", key=f"conf_{t['ref']}", type="primary",
                           use_container_width=True):
                record(agent.deliver, t["ref"], "confidential", done="Recorded as delivered")
        else:
            if b[0].button("✅ Delivered by call", key=f"call_{t['ref']}", type="primary", use_container_width=True):
                record(agent.deliver, t["ref"], "phone_call", done="Recorded as delivered")
            if b[1].button("🧍 Told in person", key=f"inp_{t['ref']}", use_container_width=True):
                record(agent.deliver, t["ref"], "in_person", done="Recorded as delivered")
        if b[2].button("📵 No answer", key=f"na_{t['ref']}", use_container_width=True):
            record(agent.no_answer, t["ref"], "", done="Call attempt logged")

if online_only:
    st.subheader("🌐 No phone number: waiting for the person to read it online")
    st.caption("They see the reply on **Give feedback → Track my feedback** with their reference, "
               "or a volunteer can tell them in person.")
    for t in online_only:
        cols = st.columns([4, 1])
        cols[0].markdown(f"**{t['ref']}** · {PRIORITY_ICON.get(t['priority'], '')} {t['priority']} · "
                         f"{CHANNEL_LABEL.get(t['channel'], t['channel'])}")
        method, label = ("confidential", "🔒 Contacted") if role == FOCAL_POINT else ("in_person", "🧍 Told in person")
        if cols[1].button(label, key=f"inp2_{t['ref']}", use_container_width=True):
            record(agent.deliver, t["ref"], method, done="Recorded as delivered")
