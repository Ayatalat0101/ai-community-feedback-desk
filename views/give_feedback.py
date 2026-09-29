"""
Give feedback: a community member (or a hotline operator / volunteer on their
behalf) sends feedback, gets a reference, and answers at most one question.

What the person is NOT shown: category, priority, the linked partner's
internal details, the referral reason or the AI draft. Everything they see
is written in the language of their feedback.
"""
import streamlit as st

from feedback import agent
from feedback.agent import ActionError
from feedback.models import GOVERNORATES, validate_form
from feedback.distributions import AR
from ui import CHANNEL_LABEL, CSS, get_conn, pipeline, sample_rows, show_text

st.markdown(CSS, unsafe_allow_html=True)
conn = get_conn()

FIELDS = {"channel": "Channel", "name": "Name", "phone": "Phone", "distribution_id": "Distribution",
          "governorate": "Governorate", "message": "Message"}
TEXT = {   # what the person reads after sending, in the language of their feedback
    "thanks": {"ar": "شكراً لك. رقمك المرجعي **{ref}**، احتفظ به.",
               "en": "Thank you. Your reference is **{ref}**. Please keep it."},
    "refer_confidential": {"ar": "سيتواصل معك أحد أفراد فريقنا المدرَّبين بشكل سري.",
                           "en": "A trained member of our team will contact you confidentially."},
    "draft_response": {"ar": "فريقنا يراجع ملاحظتك وسيرد عليك.",
                       "en": "Our team is reviewing your feedback and will reply."},
    "one_more": {"ar": "سؤال واحد لنكمل:", "en": "One question so we can continue:"},
    "pick": {"ar": "اختر التوزيع:", "en": "Choose the distribution:"},
    "or_type": {"ar": "أو اكتب جوابك", "en": "Or type your answer"},
    "send": {"ar": "إرسال الجواب", "en": "Send answer"},
}
for k in ("f_name", "f_phone", "f_dst", "f_message"):
    st.session_state.setdefault(k, "")
st.session_state.setdefault("f_gov", "")
st.session_state.setdefault("f_channel", "web")
st.session_state.setdefault("form_errors", {})
st.session_state.setdefault("last", None)


def remember(out) -> None:
    t = out.ticket
    st.session_state.last = {"ref": t["ref"], "action": out.action, "question": out.question,
                             "options": out.options, "lang": t["language"] or "ar"}


def answer(ref: str, text: str) -> None:
    try:
        remember(agent.follow_up(conn, ref, text, **pipeline()))
    except ActionError as err:
        st.session_state.follow_error = str(err)


def fill_example():
    """Demo helper: copy a sample message (and its channel) into the form."""
    if choice := st.session_state.example:
        row = next(r for r in sample_rows() if r["id"] == choice.split(" ")[0])
        st.session_state.f_message, st.session_state.f_channel = row["message"], row["channel"]
        st.session_state.form_errors = {}


st.title("💬 Give feedback · شاركنا ملاحظتك")
st.caption("A fictional feedback desk for the aid distributions in Project 1. Please use invented details only. "
           "Write in Arabic or English: you will get the answer in the same language.")

st.selectbox("Try an example (demo)", [""] + [f"{r['id']} · {r['message'][:60]}" for r in sample_rows()],
             key="example", on_change=fill_example)

with st.form("feedback_form"):
    c1, c2, c3 = st.columns(3)
    c1.selectbox("Channel", list(CHANNEL_LABEL), format_func=CHANNEL_LABEL.get, key="f_channel",
                 help="Hotline operators and volunteers enter feedback on behalf of the person.")
    c2.text_input("Name (optional) · الاسم (اختياري)", key="f_name", max_chars=60)
    c3.text_input("Phone for a call back (optional) · رقم للتواصل", key="f_phone", placeholder="0591234567")
    c4, c5 = st.columns(2)
    c4.selectbox("Governorate (optional) · المحافظة", [""] + GOVERNORATES, key="f_gov",
                 format_func=lambda g: f"{g} · {AR[g]}" if g else "—")
    c5.text_input("Distribution number (optional) · رقم التوزيع", key="f_dst", placeholder="DST-017")
    st.text_area("Feedback * · الملاحظة", key="f_message", height=130,
                 placeholder="اكتب ما حدث بجملة أو جملتين. / Describe what happened in a sentence or two.")
    sent = st.form_submit_button("Send · إرسال", type="primary")

if sent:
    sub, errors = validate_form(channel=st.session_state.f_channel, name=st.session_state.f_name,
                                phone=st.session_state.f_phone, distribution_id=st.session_state.f_dst,
                                governorate=st.session_state.f_gov, message=st.session_state.f_message)
    st.session_state.form_errors = errors
    if sub:
        remember(agent.submit(conn, sub, **pipeline()))

for field, msg in st.session_state.form_errors.items():
    st.error(f"**{FIELDS.get(field, field)}:** {msg}")

last = st.session_state.last
if last:
    lang = last["lang"] if last["lang"] in ("ar", "en") else "ar"
    st.success(TEXT["thanks"][lang].format(ref=last["ref"]))
    if last["action"] in ("refer_confidential", "draft_response"):
        st.info(TEXT[last["action"]][lang])
    elif last["action"] == "ask_for_info":
        st.warning(TEXT["one_more"][lang], icon="❓")
        show_text(last["question"])
        if last["options"]:
            st.markdown(TEXT["pick"][lang])
            for i, opt in enumerate(last["options"]):
                st.button(opt, key=f"opt_{last['ref']}_{i}", on_click=answer, args=(last["ref"], opt),
                          use_container_width=True)
        with st.form(f"follow_up_{last['ref']}", clear_on_submit=True):
            typed = st.text_input(TEXT["or_type"][lang])
            if st.form_submit_button(TEXT["send"][lang]):
                answer(last["ref"], typed)
                st.rerun()
        if err := st.session_state.pop("follow_error", None):
            st.error(err)
