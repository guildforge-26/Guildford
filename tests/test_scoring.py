"""Unit tests for the pure parts of scoring.py (JSON extraction/validation,
cost math, DB-row shaping) that don't require a live Gemini API call or a
real briefing.txt. The "does a posting actually score correctly" question
needs both of those -- see docs/test_plan.md for the manual pre-launch run.

The response shape tested here is exactly briefing.txt Part I's schema:
flat int breakdown, hard_filter_failed/hard_filter_reason as top-level
fields, gaps as {gap, how_to_address} objects, tier in {A, B, C, skip}.
"""
from types import SimpleNamespace

import pytest

from jobalerts.scoring import (
    ScoreResult,
    ScoringError,
    _extract_json,
    _validate,
    compute_cost_usd,
    score_to_db_row,
)

VALID_RESPONSE = {
    "verified": True,
    "title": "Director of AI Operations",
    "company": "Calgary Energy Co",
    "location": "Calgary, AB",
    "url": "https://example.com/jobs/1",
    "salary": "not posted",
    "track": 4,
    "hard_filter_failed": False,
    "hard_filter_reason": "meets all hard filters",
    "breakdown": {
        "requirements_match": 30, "track_level_fit": 15, "industry_fit": 10, "location": 10,
        "compensation": 6, "access": 3, "timing_competition": 10, "ai_bonus": 5,
    },
    "total_score": 89,
    "tier": "A",
    "matching_facts": ["fact1", "fact2", "fact3"],
    "gaps": [{"gap": "gap1", "how_to_address": "address1"}, {"gap": "gap2", "how_to_address": "address2"}],
    "resume_version": "Integrator",
    "warm_angle": "mention shared connection",
    "next_action": "apply today",
}


def test_extract_json_plain():
    import json
    assert _extract_json(json.dumps(VALID_RESPONSE)) == VALID_RESPONSE


def test_extract_json_strips_markdown_fences():
    import json
    text = f"```json\n{json.dumps(VALID_RESPONSE)}\n```"
    assert _extract_json(text) == VALID_RESPONSE


def test_extract_json_finds_object_amid_prose():
    import json
    text = f"Here is the score:\n{json.dumps(VALID_RESPONSE)}\nHope that helps!"
    assert _extract_json(text) == VALID_RESPONSE


def test_extract_json_raises_on_garbage():
    with pytest.raises(ScoringError):
        _extract_json("no json here at all")


def test_validate_accepts_well_formed_response():
    _validate(VALID_RESPONSE)  # should not raise


def test_validate_rejects_missing_keys():
    bad = {k: v for k, v in VALID_RESPONSE.items() if k != "hard_filter_reason"}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_validate_rejects_out_of_range_score():
    bad = {**VALID_RESPONSE, "total_score": 150}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_validate_rejects_invalid_tier():
    bad = {**VALID_RESPONSE, "tier": "reject"}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_validate_rejects_hard_filter_failed_without_skip_tier():
    bad = {**VALID_RESPONSE, "hard_filter_failed": True, "tier": "A"}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_validate_accepts_hard_filter_failed_with_skip_tier():
    ok = {**VALID_RESPONSE, "hard_filter_failed": True, "tier": "skip", "total_score": 0}
    _validate(ok)  # should not raise


def test_compute_cost_usd_is_zero_on_the_free_tier():
    pricing = {"input_per_mtok": 0.0, "output_per_mtok": 0.0}
    usage = SimpleNamespace(prompt_token_count=1_000_000, candidates_token_count=1_000_000)
    assert compute_cost_usd(usage, pricing) == 0.0


def test_compute_cost_usd_math_holds_for_nonzero_pricing():
    # Exercises the arithmetic generically in case this ever points at a
    # paid model/tier -- the free-tier default is covered separately above.
    pricing = {"input_per_mtok": 2.0, "output_per_mtok": 10.0}
    usage = SimpleNamespace(prompt_token_count=1_000_000, candidates_token_count=500_000)
    assert compute_cost_usd(usage, pricing) == pytest.approx(7.0)


def test_score_to_db_row_extracts_ai_bonus_and_track():
    result = ScoreResult(data=VALID_RESPONSE, input_tokens=100, output_tokens=50, cost_usd=0.0)
    row = score_to_db_row(result, "gemini-3.6-flash")
    assert row["track"] == "4"
    assert row["total_score"] == 89
    assert row["ai_bonus_score"] == 5
    assert row["hard_filter_passed"] == 1
    assert row["verified"] == 1
    assert row["tier"] == "A"
    assert row["cost_usd"] == 0.0
    import json
    assert json.loads(row["top_gaps_json"]) == VALID_RESPONSE["gaps"]
    assert json.loads(row["raw_json"]) == VALID_RESPONSE


def test_score_to_db_row_inverts_hard_filter_failed():
    failed = {**VALID_RESPONSE, "hard_filter_failed": True, "hard_filter_reason": "below salary floor",
              "tier": "skip", "total_score": 0}
    result = ScoreResult(data=failed, input_tokens=100, output_tokens=50, cost_usd=0.0)
    row = score_to_db_row(result, "gemini-3.6-flash")
    assert row["hard_filter_passed"] == 0
    assert row["hard_filter_reason"] == "below salary floor"
