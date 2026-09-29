"""
Shared UI helpers for both pages. Presentation only: every decision (who may
see what, what is allowed) lives in feedback/, so it is tested without a browser.
"""
from __future__ import annotations

import csv
import html
from pathlib import Path

import streamlit as st

from feedback import distributions
from feedback.store import connect

ROOT = Path(__file__).parent
DB_PATH = ROOT / "feedback.db"
SAMPLES = ROOT / "data" / "sample_feedback.csv"

STATUS_LABEL = {
    "new": "🆕 New", "waiting_for_info": "⏳ Waiting for info", "draft_ready": "📝 Draft ready",
    "referred": "🔒 Referred", "needs_rework": "↩️ Needs rework", "approved": "✅ Approved", "closed": "📁 Closed",
}
PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
PRIORITY_ICON = {"Critical": "🟣", "High": "🔴", "Medium": "🟠", "Low": "🟢"}
CHANNEL_LABEL = {"web": "🌐 Web form", "hotline": "☎️ Hotline", "in_person": "🧍 In person"}
DIST_STATUS_ICON = {"Completed": "✅", "Pending": "⏳", "Cancelled": "⛔"}

# Arabic and English on the same page: every line picks its own direction.
CSS = """
<style>
textarea, .msg { unicode-bidi: plaintext; text-align: start; }
/* Alerts, captions and buttons: each paragraph takes the direction of its first letter,
   so an Arabic sentence with "FB-0001" in it is not scrambled. */
[data-testid="stAlert"] p, [data-testid="stCaptionContainer"] p, .stButton button p, [data-testid="stMarkdownContainer"] p {
  unicode-bidi: plaintext; text-align: start; }
.msg { white-space: pre-wrap; padding: .65rem .85rem; border-radius: .5rem;
       border: 1px solid rgba(128,128,128,.35); margin: .25rem 0 .75rem; }
.dist { padding: .6rem .85rem; border-radius: .5rem; border: 1px solid rgba(128,128,128,.35);
        background: rgba(128,128,128,.06); margin: .25rem 0 .75rem; line-height: 1.7; }
</style>
"""


@st.cache_resource
def get_conn():
    """One SQLite connection per server process."""
    return connect(DB_PATH)


def pipeline() -> dict:
    """Classifier and drafter. Stage 4: rules + templates. Stage 6 plugs Gemini in here."""
    return {}


def show_text(text: str) -> None:
    """Text written by the public: escaped (never rendered as HTML) and direction-aware."""
    st.markdown(f'<div class="msg" dir="auto">{html.escape(text or "")}</div>', unsafe_allow_html=True)


def distribution_card(distribution_id: str | None) -> None:
    """The facts from Project 1's data for the linked distribution."""
    if not distribution_id:
        st.caption("No distribution linked.")
        return
    df = distributions.load()
    hit = df[df["distribution_id"] == distribution_id]
    if hit.empty:
        st.caption(f"{distribution_id}: not in aid_distributions.csv")
        return
    d = hit.iloc[0]
    st.markdown(
        f'<div class="dist"><b>{html.escape(d["distribution_id"])}</b> · {DIST_STATUS_ICON.get(d["status"], "")} '
        f'{html.escape(d["status"])}<br>{html.escape(d["partner"])} · {html.escape(d["item"])}<br>'
        f'{html.escape(d["governorate"])} · {d["date"]:%d %b %Y} · {html.escape(str(d["households_reached"]))} households reached'
        f'</div>', unsafe_allow_html=True)


def sample_rows(valid_only: bool = True) -> list[dict]:
    rows = list(csv.DictReader(open(SAMPLES, encoding="utf-8")))
    return [r for r in rows if r["expected_action"] != "reject_form"] if valid_only else rows
