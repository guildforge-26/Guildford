"""Setup & Onboarding Chat page (Feature 1: Conversational Onboarding Engine)."""

import json
import sqlite3

import streamlit as st

import db
from gemini_client import get_api_key, send_onboarding_message

INITIAL_ASSISTANT_MESSAGE = (
    "Let's set up your company. First, what's your company's name?"
)

START_MARKER = "<<<ONBOARDING_COMPLETE>>>"
END_MARKER = "<<<END>>>"


def _init_chat_state() -> None:
    if "onboarding_messages" not in st.session_state:
        st.session_state.onboarding_messages = [
            {"role": "assistant", "content": INITIAL_ASSISTANT_MESSAGE}
        ]


def _extract_completion(text: str) -> tuple[str, dict | None]:
    """Split a model response into (visible_text, completion_payload_or_None)."""
    if START_MARKER not in text:
        return text, None

    visible, _, rest = text.partition(START_MARKER)
    payload, _, _ = rest.partition(END_MARKER)
    try:
        data = json.loads(payload.strip())
    except json.JSONDecodeError:
        return text, None
    return visible.strip(), data


def _render_saved_company(company: dict) -> None:
    st.success(f"Company already onboarded: **{company['name']}**")
    with st.expander("View saved structure", expanded=True):
        st.write(f"**Problem:** {company['problem_statement']}")
        st.write(f"**Solution:** {company['solution']}")
        st.write(f"**Revenue model:** {company['revenue_model']}")
        for seat in company["seats"]:
            st.markdown(f"**Seat: {seat['seat_name']}** — {seat['description']}")
            if seat["responsibilities"]:
                st.markdown("Responsibilities:")
                for r in seat["responsibilities"]:
                    st.markdown(f"- {r}")
            if seat["kpis"]:
                st.markdown("KPIs:")
                for k in seat["kpis"]:
                    st.markdown(f"- {k['kpi_name']}: {k['target_metric']}")

    if st.button("Start a new onboarding"):
        st.session_state.onboarding_start_new = True
        st.session_state.pop("onboarding_messages", None)
        st.rerun()


def render() -> None:
    st.subheader("Setup & Onboarding Chat")

    api_key = get_api_key()
    if not api_key:
        st.info("Add your Gemini API key in the sidebar to begin onboarding.")
        return

    existing_company = db.get_latest_company()
    if existing_company and not st.session_state.get("onboarding_start_new"):
        _render_saved_company(existing_company)
        return

    _init_chat_state()

    for msg in st.session_state.onboarding_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("Type your answer...")
    if not user_input:
        return

    st.session_state.onboarding_messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            text, error = send_onboarding_message(st.session_state.onboarding_messages, api_key)

        if error:
            st.session_state["gemini_last_error"] = error
            st.error(error)
            return

        st.session_state["gemini_last_error"] = None
        visible_text, completion_data = _extract_completion(text)
        st.write(visible_text)
        st.session_state.onboarding_messages.append({"role": "assistant", "content": visible_text})

        if completion_data:
            try:
                db.save_onboarding(completion_data)
                st.session_state.onboarding_start_new = False
                st.success("Company structure saved.")
                st.rerun()
            except (KeyError, sqlite3.Error) as e:
                st.error(f"Failed to save onboarding data: {e}")
