"""
AI Community Feedback Desk: entry point.

Two pages: the feedback form (community members, hotline operators,
volunteers) and the staff dashboard (feedback officer / safeguarding focal
point). In a real deployment they would be separate apps with a login for
staff; for the demo both are here so one link shows the whole flow.

The page files live in views/, not pages/: Streamlit auto-scans a folder
named pages/ and shows its own menu when a page URL is opened directly
(a lesson from the previous version of this project).

Run:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Community Feedback Desk", page_icon="💬", layout="wide")

pages = st.navigation([
    st.Page("views/give_feedback.py", title="Give feedback", icon="💬", default=True),
    st.Page("views/dashboard.py", title="Feedback dashboard", icon="🗂️"),
    st.Page("views/callbacks.py", title="Call-back list", icon="📞"),
])
pages.run()
