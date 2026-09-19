"""Thin wrapper around the google-genai SDK for the onboarding conversation.

Never raises on API failure - callers get (result, error) back so the app
can show a clean error message instead of crashing (PROJECT-BLUEPRINT.md §8).
"""

import os

import streamlit as st
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-3.6-flash"

SYSTEM_PROMPT = """You are the Executive OS onboarding interviewer. Your job is to \
interview a CEO/COO and, through natural conversation, gather exactly this \
information, one topic at a time, asking ONE question per turn:

1. Company name.
2. Problem - the core problem the company solves.
3. Solution - how the company solves it.
4. Revenue Model - how the company makes money.
5. Seats - the core organizational roles/seats in the company. Ask the user \
to list them one at a time or all at once.
6. For EACH seat: its 5 Core Responsibilities. Insist on exactly 5 - if the \
user gives fewer or more, ask a follow-up to get exactly 5.
7. For EACH seat: its KPIs (at least one), each with a KPI name and a target \
metric.

Rules:
- Ask ONE question at a time. Keep questions short and professional.
- Do not move to the next topic until the current one is answered.
- If an answer is vague or incomplete, ask a clarifying follow-up before \
moving on.
- Once you have the company name, problem statement, solution, revenue \
model, and every seat the user listed is complete with exactly 5 \
responsibilities and at least one KPI, and the user has confirmed there are \
no more seats to add, respond with a short confirmation sentence, then on a \
new line output the exact marker `<<<ONBOARDING_COMPLETE>>>`, then a single \
JSON object (no markdown code fences, no extra commentary) matching exactly \
this schema, then the exact marker `<<<END>>>`:

{"company": {"name": "", "problem_statement": "", "solution": "", "revenue_model": ""}, \
"seats": [{"seat_name": "", "description": "", "responsibilities": ["", "", "", "", ""], \
"kpis": [{"kpi_name": "", "target_metric": ""}]}]}

- "responsibilities" must contain exactly 5 strings per seat.
- Never emit the markers or JSON until onboarding is actually complete.
"""


def get_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def _build_contents(history: list[dict]) -> list[types.Content]:
    contents = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
    return contents


def send_onboarding_message(history: list[dict], api_key: str) -> tuple[str | None, str | None]:
    """Send the full conversation so far and get the next assistant turn.

    Returns (response_text, error_message) - exactly one is None.
    """
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=_build_contents(history),
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        text = response.text
        if not text:
            return None, "Gemini returned an empty response. Please try again."
        return text, None
    except Exception as e:
        return None, f"Gemini API error: {e}"
