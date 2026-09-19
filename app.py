"""Executive OS - Streamlit entry point (Feature 1: Conversational Onboarding)."""

import streamlit as st

import db
import onboarding
from gemini_client import get_api_key

st.set_page_config(page_title="Executive OS", layout="wide")

db.init_db()

st.sidebar.title("Executive OS")

api_key = get_api_key()
if not api_key:
    st.sidebar.error(
        "Gemini API key not found. Set GEMINI_API_KEY as an environment "
        "variable, in a local .env, or in Streamlit secrets."
    )
else:
    st.sidebar.success("Gemini API key detected.")

last_error = st.session_state.get("gemini_last_error")
if last_error:
    st.sidebar.error(f"Last Gemini API error: {last_error}")

st.title("Executive OS")
onboarding.render()
