"""Calls Claude to score one posting against briefing.txt.

Design choices (see docs/adr/ADR-002-scoring-model-and-cost.md):
- briefing.txt is sent as the cached system prompt (identical on every call
  within a run, so cache_control makes every call after the first ~90%
  cheaper on that portion).
- The model is asked to return raw JSON only (no tool-use, no structured
  outputs beta) so this works against any anthropic SDK >=0.40 without
  depending on a specific structured-output API shape.
- Thinking is explicitly disabled: this is a bounded extraction/classification
  task against a fixed rubric, not open-ended reasoning, so adaptive
  thinking would only add latency and cost.
- This module never touches the database or decides whether to call the
  model at all -- the pipeline checks db.has_score() and the call/spend
  budgets before calling score_posting(), so this stays pure and testable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

REQUIRED_TOP_LEVEL_KEYS = (
    "track",
    "tier",
    "total_score",
    "breakdown",
    "hard_filter",
    "matching_facts",
    "top_gaps",
    "resume_version",
    "warm_angle",
    "next_action",
)

_RESPONSE_FORMAT_INSTRUCTIONS = """
You are scoring ONE job posting against the candidate profile above.

Respond with ONLY a single valid JSON object -- no markdown code fences, no
commentary before or after it. It must have exactly these top-level keys:

{
  "track": "<track1|track2|track3|track4|none>",
  "tier": "<A|B|C|reject>",
  "total_score": <integer 0-100>,
  "breakdown": {
    "<part_1_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_2_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_3_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_4_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_5_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_6_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "<part_7_name>": {"score": <int>, "max": <int>, "notes": "<why>"},
    "ai_bonus": {"score": <int>, "notes": "<applied AI/automation experience relevance, or 0 if none>"}
  },
  "hard_filter": {"passed": <true|false>, "reason": "<why passed or which hard filter failed>"},
  "matching_facts": ["<fact 1>", "<fact 2>", "<fact 3>"],
  "top_gaps": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "resume_version": "<which resume version to use>",
  "warm_angle": "<a specific warm outreach angle for this posting>",
  "next_action": "<one concrete next action>"
}

Use the seven-part scoring method and hard filters exactly as defined in the
candidate profile above. If a hard filter fails, still return valid JSON
with "hard_filter": {"passed": false, ...}, "tier": "reject", and a
total_score that reflects the failure -- never omit fields or return prose.
""".strip()


class ScoringError(Exception):
    pass


@dataclass
class ScoreResult:
    data: dict
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: float


def build_system_prompt(briefing_text: str) -> str:
    return f"{briefing_text.strip()}\n\n---\n\n{_RESPONSE_FORMAT_INSTRUCTIONS}"


def build_user_message(posting: dict) -> str:
    fields = [
        f"Title: {posting.get('title', '')}",
        f"Company: {posting.get('company', '')}",
        f"Location: {posting.get('location', '')}",
        f"Salary (as stated): {posting.get('salary_text') or 'not stated'}",
        f"Source: {posting.get('source', '')}",
        f"URL: {posting.get('canonical_url') or posting.get('url', '')}",
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
    if len(data.get("matching_facts", [])) < 1 or len(data.get("top_gaps", [])) < 1:
        raise ScoringError("matching_facts / top_gaps must be non-empty lists")


def compute_cost_usd(usage, pricing: dict) -> float:
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input_per_mtok"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output_per_mtok"]
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write_cost = (cache_write / 1_000_000) * pricing["input_per_mtok"] * pricing["cache_write_5m_multiplier"]
    cache_read_cost = (cache_read / 1_000_000) * pricing["input_per_mtok"] * pricing["cache_read_multiplier"]
    return round(input_cost + output_cost + cache_write_cost + cache_read_cost, 6)


def score_posting(
    client: anthropic.Anthropic,
    model: str,
    pricing: dict,
    briefing_text: str,
    posting: dict,
    max_json_retries: int = 2,
) -> ScoreResult:
    system_prompt = build_system_prompt(briefing_text)
    user_message = build_user_message(posting)

    last_error: Optional[Exception] = None
    for attempt in range(1, max_json_retries + 2):
        messages = [{"role": "user", "content": user_message}]
        if attempt > 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid JSON matching the required schema. "
                        "Reply again with ONLY the JSON object, nothing else."
                    ),
                }
            )
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                thinking={"type": "disabled"},
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )
        except anthropic.APIStatusError as exc:
            raise ScoringError(f"Claude API error: {exc}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            data = _extract_json(text)
            _validate(data)
        except (ScoringError, json.JSONDecodeError) as exc:
            last_error = exc
            continue

        cost_usd = compute_cost_usd(response.usage, pricing)
        return ScoreResult(
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cost_usd=cost_usd,
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
    client: anthropic.Anthropic, model: str, pricing: dict, briefing_text: str, postings_summary: str,
) -> FractionalScanResult:
    system_prompt = build_fractional_scan_system_prompt(briefing_text)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            thinking={"type": "disabled"},
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": postings_summary}],
        )
    except anthropic.APIStatusError as exc:
        raise ScoringError(f"Claude API error: {exc}") from exc

    text = "".join(block.text for block in response.content if block.type == "text")
    data = _extract_json(text)
    if "flagged" not in data or not isinstance(data["flagged"], list):
        raise ScoringError(f"fractional scan response missing 'flagged' list: {data!r}")

    return FractionalScanResult(flagged=data["flagged"], cost_usd=compute_cost_usd(response.usage, pricing))


def score_to_db_row(result: ScoreResult, model: str) -> dict:
    data = result.data
    breakdown = data.get("breakdown", {})
    ai_bonus = breakdown.get("ai_bonus", {}) if isinstance(breakdown, dict) else {}
    return {
        "track": data.get("track"),
        "tier": data.get("tier"),
        "total_score": int(data.get("total_score", 0)),
        "breakdown_json": json.dumps(breakdown),
        "hard_filter_passed": int(bool(data.get("hard_filter", {}).get("passed"))),
        "hard_filter_reason": data.get("hard_filter", {}).get("reason"),
        "matching_facts_json": json.dumps(data.get("matching_facts", [])),
        "top_gaps_json": json.dumps(data.get("top_gaps", [])),
        "resume_version": data.get("resume_version"),
        "warm_angle": data.get("warm_angle"),
        "next_action": data.get("next_action"),
        "ai_bonus_score": ai_bonus.get("score", 0) if isinstance(ai_bonus, dict) else 0,
        "ai_bonus_notes": ai_bonus.get("notes") if isinstance(ai_bonus, dict) else None,
        "model_used": model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
    }
