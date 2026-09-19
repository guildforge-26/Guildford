"""Unit tests for the pure parts of scoring.py (JSON extraction/validation,
cost math, DB-row shaping) that don't require a live Claude API call or a
real briefing.txt. The "does a posting actually score correctly" question
needs both of those -- see docs/test_plan.md for the manual pre-launch run.
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
    "track": "track4", "tier": "A", "total_score": 88,
    "breakdown": {"fit": {"score": 20, "max": 20, "notes": "great fit"}, "ai_bonus": {"score": 5, "notes": "applied AI experience"}},
    "hard_filter": {"passed": True, "reason": "meets all hard filters"},
    "matching_facts": ["fact1", "fact2", "fact3"],
    "top_gaps": ["gap1", "gap2", "gap3"],
    "resume_version": "ops-leader-v2",
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
    bad = {k: v for k, v in VALID_RESPONSE.items() if k != "hard_filter"}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_validate_rejects_out_of_range_score():
    bad = {**VALID_RESPONSE, "total_score": 150}
    with pytest.raises(ScoringError):
        _validate(bad)


def test_compute_cost_usd_accounts_for_cache_read_and_write():
    pricing = {"input_per_mtok": 2.0, "output_per_mtok": 10.0, "cache_write_5m_multiplier": 1.25, "cache_read_multiplier": 0.10}
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    assert compute_cost_usd(usage, pricing) == pytest.approx(12.0)

    usage_cached = SimpleNamespace(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000, cache_read_input_tokens=0)
    assert compute_cost_usd(usage_cached, pricing) == pytest.approx(2.5)

    usage_read = SimpleNamespace(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=1_000_000)
    assert compute_cost_usd(usage_read, pricing) == pytest.approx(0.2)


def test_score_to_db_row_extracts_ai_bonus():
    result = ScoreResult(data=VALID_RESPONSE, input_tokens=100, output_tokens=50,
                          cache_creation_input_tokens=0, cache_read_input_tokens=0, cost_usd=0.01)
    row = score_to_db_row(result, "claude-sonnet-5")
    assert row["track"] == "track4"
    assert row["total_score"] == 88
    assert row["ai_bonus_score"] == 5
    assert row["hard_filter_passed"] == 1
