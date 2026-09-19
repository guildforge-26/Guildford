"""Calls Gemini (free tier) to score one posting against briefing.txt.

Design choices (see docs/adr/ADR-006-scoring-model-gemini-free-tier.md):
- briefing.txt is sent as-is as the system_instruction. Part A already says
  "return strict JSON only... no markdown fences" and Part I spells out the
  schema, so this module adds no separate formatting instructions of its
  own -- nothing here can drift out of sync with the real rubric.
- response_mime_type="application/json" puts the model in native JSON mode,
  which is stronger than a prompt instruction alone; _extract_json's
  fence-stripping/brace-scanning fallback stays in place as defense in
  depth, since JSON mode guarantees syntactically valid JSON but not
  schema-valid JSON (a model can still emit valid JSON missing a field).
- Thinking is explicitly disabled (thinking_budget=0): this is a bounded
  extraction/classification task against a fixed rubric, not open-ended
  reasoning, so it would only add latency and token usage against the free
  tier's per-minute token quota for no quality gain here.
- No prompt caching: Claude's design cached briefing.txt because caching
  saved real money. On the Gemini free tier every call is already $0, so
  the caching machinery was dropped rather than ported -- it would add
  complexity (Gemini's context-caching API is a different, heavier
  feature: explicit cache objects with their own lifecycle) for no benefit.
- This module never touches the database or decides whether to call the
  model at all -- the pipeline checks db.has_score() and the call budget
  before calling score_posting(), so this stays pure and testable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import errors, types

# Exactly briefing.txt Part I's top-level keys. briefing.txt is the full
# system prompt as-is (Part A already says "return strict JSON only... no
# markdown fences", and Part I spells out the schema) -- this module adds
# no separate formatting instructions of its own, so there is nothing here
# that can drift out of sync with the real rubric.
REQUIRED_TOP_LEVEL_KEYS = (
    "verified",
    "track",
    "hard_filter_failed",
    "hard_filter_reason",
    "breakdown",
    "total_score",
    "tier",
    "matching_facts",
    "gaps",
    "resume_version",
    "warm_angle",
    "next_action",
)

VALID_TIERS = {"A", "B", "C", "skip"}


class ScoringError(Exception):
    pass


@dataclass
class ScoreResult:
    data: dict
    input_tokens: int
    output_tokens: int
    cost_usd: float


def build_system_prompt(briefing_text: str) -> str:
    return briefing_text.strip()


def build_user_message(posting: dict, applicant_count: Optional[int] = None, contacts_notes: Optional[str] = None) -> str:
    fields = [
        f"Title: {posting.get('title', '')}",
        f"Company: {posting.get('company', '')}",
        f"Location: {posting.get('location', '')}",
        f"Salary (as stated): {posting.get('salary_text') or 'not stated'}",
        f"Source: {posting.get('source', '')}",
        f"URL: {posting.get('canonical_url') or posting.get('url', '')}",
        f"Posting date: {posting.get('posted_at') or 'not supplied'}",
        f"Applicant count: {applicant_count if applicant_count is not None else 'not supplied'}",
        f"Contacts/access notes: {contacts_notes or 'none supplied'}",
        "",
        "Full posting text:",
        posting.get("raw_text") or "(not available -- score on the fields above only)",
    ]
    return "\n".join(fields)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ScoringError(f"no JSON object found in model response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def _validate(data: dict) -> None:
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise ScoringError(f"model response missing keys: {missing}")
    if not isinstance(data["total_score"], (int, float)) or not (0 <= data["total_score"] <= 100):
        raise ScoringError(f"total_score out of range: {data.get('total_score')!r}")
    if data.get("tier") not in VALID_TIERS:
        raise ScoringError(f"tier must be one of {VALID_TIERS}: {data.get('tier')!r}")
    if not isinstance(data.get("breakdown"), dict):
        raise ScoringError(f"breakdown must be an object: {data.get('breakdown')!r}")
    if not isinstance(data.get("matching_facts"), list) or not isinstance(data.get("gaps"), list):
        raise ScoringError("matching_facts and gaps must be lists")
    if bool(data.get("hard_filter_failed")) and data.get("tier") != "skip":
        raise ScoringError(f"hard_filter_failed=true must carry tier='skip', got {data.get('tier')!r}")


def compute_cost_usd(usage_metadata, pricing: dict) -> float:
    input_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_mtok"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_mtok"]
    return round(input_cost + output_cost, 6)


def _generate(client: genai.Client, model: str, system_prompt: str, contents: str) -> types.GenerateContentResponse:
    try:
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except errors.APIError as exc:
        raise ScoringError(f"Gemini API error: {exc}") from exc


def score_posting(
    client: genai.Client,
    model: str,
    pricing: dict,
    briefing_text: str,
    posting: dict,
    max_json_retries: int = 2,
    applicant_count: Optional[int] = None,
    contacts_notes: Optional[str] = None,
) -> ScoreResult:
    system_prompt = build_system_prompt(briefing_text)
    user_message = build_user_message(posting, applicant_count=applicant_count, contacts_notes=contacts_notes)

    last_error: Optional[Exception] = None
    for attempt in range(1, max_json_retries + 2):
        contents = user_message
        if attempt > 1:
            contents += (
                "\n\nYour previous reply was not valid JSON matching the required schema. "
                "Reply again with ONLY the JSON object, nothing else."
            )

        response = _generate(client, model, system_prompt, contents)

        try:
            data = _extract_json(response.text or "")
            _validate(data)
        except (ScoringError, json.JSONDecodeError) as exc:
            last_error = exc
            continue

        usage = response.usage_metadata
        return ScoreResult(
            data=data,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            cost_usd=compute_cost_usd(usage, pricing),
        )

    raise ScoringError(f"gave up after {max_json_retries + 1} attempts, last error: {last_error}")


_FRACTIONAL_SCAN_INSTRUCTIONS = """
You are reviewing a list of job postings collected today. Some companies
post a full-time role (e.g. "Controller", "VP Finance", "Head of
Operations") when what they actually seem to need, based on the posting's
own language (stage, team size, budget, scope described), is a
fractional/part-time or interim CFO or COO instead. Flag ONLY postings
where there's a real signal of this (small team, early-stage or
budget-constrained language, "wearing many hats", founder-led) -- do not
flag every finance/ops posting you see.

Respond with ONLY a JSON object, no commentary:
{"flagged": [{"company": "...", "title": "...", "why": "...", "suggested_angle": "..."}]}
Use an empty list if nothing qualifies.
""".strip()


@dataclass
class FractionalScanResult:
    flagged: list
    cost_usd: float


def build_fractional_scan_system_prompt(briefing_text: str) -> str:
    return f"{briefing_text.strip()}\n\n---\n\n{_FRACTIONAL_SCAN_INSTRUCTIONS}"


def scan_for_fractional_leads(
    client: genai.Client, model: str, pricing: dict, briefing_text: str, postings_summary: str,
) -> FractionalScanResult:
    system_prompt = build_fractional_scan_system_prompt(briefing_text)
    response = _generate(client, model, system_prompt, postings_summary)

    data = _extract_json(response.text or "")
    if "flagged" not in data or not isinstance(data["flagged"], list):
        raise ScoringError(f"fractional scan response missing 'flagged' list: {data!r}")

    return FractionalScanResult(flagged=data["flagged"], cost_usd=compute_cost_usd(response.usage_metadata, pricing))


def score_to_db_row(result: ScoreResult, model: str) -> dict:
    data = result.data
    breakdown = data.get("breakdown", {}) if isinstance(data.get("breakdown"), dict) else {}
    ai_bonus_score = breakdown.get("ai_bonus", 0)
    return {
        "verified": int(bool(data.get("verified", True))),
        "track": str(data.get("track", 0)),
        "tier": data.get("tier"),
        "total_score": int(data.get("total_score", 0)),
        "breakdown_json": json.dumps(breakdown),
        "hard_filter_passed": int(not bool(data.get("hard_filter_failed"))),
        "hard_filter_reason": data.get("hard_filter_reason"),
        "matching_facts_json": json.dumps(data.get("matching_facts", [])),
        "top_gaps_json": json.dumps(data.get("gaps", [])),
        "resume_version": data.get("resume_version"),
        "warm_angle": data.get("warm_angle"),
        "next_action": data.get("next_action"),
        "ai_bonus_score": int(ai_bonus_score) if isinstance(ai_bonus_score, (int, float)) else 0,
        "ai_bonus_notes": None,
        "model_used": model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "raw_json": json.dumps(data),
    }
