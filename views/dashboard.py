"""
Feedback dashboard: the human-in-the-loop half of the system, with two roles.

  Feedback officer          sees every non-sensitive case in full; a referred
                            case appears only as "🔒 Restricted" with no text.
  Safeguarding focal point  sees and acts on referred cases.

Demo note: the role is chosen in the sidebar so one link shows both views.
A real deployment would take the role from a login. The agent functions
check the role again (feedback/agent.py), so hiding is not only cosmetic.
"""
import pandas as pd
import streamlit as st

from feedback import agent
from feedback.agent import FOCAL_POINT, OFFICER, ActionError
from feedback.models import Submission
from feedback.store import counts, events_for, get_ticket, list_tickets, reset_all
from ui import (CHANNEL_LABEL, CSS, PRIORITY_ICON, PRIORITY_RANK, STATUS_LABEL, distribution_card, get_conn,
                sample_rows, show_text)

st.markdown(CSS, unsafe_allow_html=True)
conn = get_conn()
st.session_state.setdefault("selected", None)
ROLE_LABEL = {OFFICER: "Feedback officer", FOCAL_POINT: "Safeguarding focal point"}

# --- sidebar: role, reviewer, demo data ---------------------------------------------------
with st.sidebar:
    role = st.radio("Role (demo)", list(ROLE_LABEL), format_func=ROLE_LABEL.get, key="role")
    reviewer = st.text_input("Your name", value="Aya", max_chars=40).strip() or "Staff"
    st.divider()
    st.caption("**Demo data**")
    if st.button("Load the sample feedback", use_container_width=True):
        for r in sample_rows():
            agent.submit(conn, Submission(message=r["message"], channel=r["channel"]))
        st.toast(f"Loaded {len(sample_rows())} sample messages")
        st.rerun()
    confirm = st.checkbox("I want to delete all feedback")
    if st.button("Delete all feedback", disabled=not confirm, use_container_width=True):
        reset_all(conn)
        st.session_state.selected = None
        st.rerun()

st.title("🗂️ Feedback dashboard")
st.caption(f"Viewing as **{ROLE_LABEL[role]}**. "
           + ("Referred cases are hidden from this role." if role == OFFICER
              else "You can read and act on referred (sensitive) cases."))

c = counts(conn)
m = st.columns(5)
m[0].metric("🟣 Critical open", c["critical"])
m[1].metric("🔴 High open", c["high"])
m[2].metric("📝 Drafts to review", c["drafts"])
m[3].metric("⏳ Waiting for the person", c["waiting"])
m[4].metric("Total feedback", c["total"])

# --- filters + queue -------------------------------------------------------------------------
f = st.columns(4)
status = f[0].selectbox("Status", ["All"] + list(STATUS_LABEL), format_func=lambda s: STATUS_LABEL.get(s, s))
priority = f[1].selectbox("Priority", ["All", "Critical", "High", "Medium", "Low"])
category = f[2].selectbox("Category", ["All", "distribution", "information", "conduct", "access",
                                       "appreciation", "sensitive"])
partner = f[3].selectbox("Partner", ["All", "Nour Relief", "Sanad Aid", "Amal Foundation", "Rahma Network"])
tickets = list_tickets(conn, *(None if v == "All" else v for v in (status, priority, category, partner)))

if not tickets:
    st.info("No feedback here yet. Send some from **Give feedback**, or click **Load the sample feedback**.")
    st.stop()

hidden = lambda t: t["restricted"] and role != FOCAL_POINT
tickets.sort(key=lambda t: (t["status"] in ("approved", "closed"), PRIORITY_RANK.get(t["priority"], 4),
                            -int(t["ref"][3:])))
table = pd.DataFrame([{
    "Ref": t["ref"], "Received (UTC)": t["created_at"][5:16].replace("T", " "),
    "Channel": CHANNEL_LABEL.get(t["channel"], t["channel"]).split(" ", 1)[0],
    "Lang": t["language"], "Category": "🔒 restricted" if hidden(t) else t["category"],
    "Priority": f"{PRIORITY_ICON.get(t['priority'], '')} {t['priority'] or ''}",
    "Status": STATUS_LABEL.get(t["status"], t["status"]),
    "Distribution": "" if hidden(t) else (t["distribution_id"] or ""),
    "Partner": "" if hidden(t) else (t["partner"] or ""),
    "Feedback": "🔒 Safeguarding focal point only" if hidden(t)
                else t["message"].split("\n\n[Follow-up]")[0][:70],
} for t in tickets])
small = st.column_config.TextColumn(width="small")
event = st.dataframe(table, hide_index=True, use_container_width=True, on_select="rerun",
                     selection_mode="single-row", key="queue", height=min(38 * (len(table) + 1), 420),
                     column_config={"Channel": small, "Lang": small, "Priority": st.column_config.TextColumn(width=95)})
if event.selection.rows:
    st.session_state.selected = table.iloc[event.selection.rows[0]]["Ref"]
refs = list(table["Ref"])
if st.session_state.selected not in refs:
    st.session_state.selected = refs[0]

# --- selected feedback --------------------------------------------------------------------------
t = get_ticket(conn, st.session_state.selected)
st.divider()
st.subheader(f"{t['ref']} · {STATUS_LABEL[t['status']]}")

if hidden(t):
    st.warning("🔒 **Restricted case.** It was referred confidentially to the safeguarding focal point. "
               "Its content, category details and history are not shown to this role.", icon="🔒")
    st.stop()


def act(fn, *args, done: str):
    try:
        fn(conn, t["ref"], reviewer, *args, role=role)
        st.toast(done)
        st.rerun()
    except ActionError as err:
        st.error(str(err))


history = events_for(conn, t["ref"])
left, right = st.columns([3, 2])
with left:
    st.markdown("**Feedback**")
    show_text(t["message"])
    st.caption(f"{CHANNEL_LABEL.get(t['channel'], t['channel'])} · From: {t['person_ref']} · "
               f"Phone: {t['phone'] or '—'} · Language: {t['language']}")
with right:
    st.markdown(f"**Category:** `{t['category']}`  \n{t['category_reason']}")
    st.markdown(f"**Priority:** {PRIORITY_ICON.get(t['priority'], '')} {t['priority']}  \n{t['priority_rule']}")
    if t["referral_reason"]:
        st.error(f"**Referral:** {t['referral_reason']}", icon="🔒")
    else:
        st.markdown("**Distribution** (from Project 1's data)")
        distribution_card(t["distribution_id"])
        if not t["distribution_id"] and (t["partner"] or t["governorate"]):
            st.caption(f"Mentioned: {t['partner'] or ''} {t['governorate'] or ''}")
    drafted = next((e["detail"][12:] for e in reversed(history)
                    if e["event"] == "draft_response" and (e["detail"] or "").startswith("drafted by: ")), "")
    st.caption(f"Classified by: {t['planner']}" + (f" · Drafted by: {drafted}" if drafted else ""))
    if t["reviewer_note"]:
        st.info(f"**Reviewer note:** {t['reviewer_note']}", icon="↩️")

if t["status"] in ("draft_ready", "needs_rework", "referred"):
    if t["status"] == "referred":
        st.markdown("**✍️ Reply: referred case, no AI draft. Write the reply yourself (it is saved as the approved reply).**")
    else:
        st.markdown("**📝 Draft — human review required**")
    text = st.text_area("Reply", value=t["draft_response"] or "", height=190,
                        key=f"draft_{t['ref']}_{t['updated_at']}", label_visibility="collapsed")
    reason = st.text_input("Reason (required to reject or refer)", key=f"reason_{t['ref']}")
    b = st.columns(4)
    edited = text.strip() != (t["draft_response"] or "").strip()
    if b[0].button("✅ Save edits & approve" if edited else "✅ Approve", type="primary", use_container_width=True):
        act(agent.approve, text if edited else None, done="Reply approved")
    if b[1].button("↩️ Reject draft", use_container_width=True, disabled=t["status"] != "draft_ready"):
        act(agent.reject, reason, done="Draft sent back for rework")
    if b[2].button("🔒 Refer to focal point", use_container_width=True, disabled=t["status"] == "referred"):
        act(agent.refer, reason, done="Referred confidentially")
    if b[3].button("📁 Close", use_container_width=True):
        act(agent.close, reason, done="Closed")
elif t["status"] == "approved":
    st.markdown("**✅ Approved reply** (reviewed by a person)")
    show_text(t["draft_response"])
    if st.button("📁 Close"):
        act(agent.close, "", done="Closed")
elif t["status"] == "waiting_for_info":
    asked = next((e["detail"] for e in reversed(history) if e["event"] == "ask_for_info"), "")
    st.markdown("**⏳ Question sent to the person**")
    show_text(asked + ("\n\n" + "\n".join(f"• {o}" for o in t["options"]) if t["options"] else ""))
    if st.button("🔒 Refer to focal point anyway"):
        act(agent.refer, "Referred while waiting for the person", done="Referred")

with st.expander("History (audit log)"):
    st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
