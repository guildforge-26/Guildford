# ADR-002: Scoring model, prompt design, and cost

## Status
Accepted

## Context
Every new posting that survives the cheap prefilter needs to be scored
against Tommy's profile: track, tier, 0-100 total score, a seven-part
breakdown, hard-filter result, matching facts, gaps, resume version, warm
angle, and next action -- plus an AI/automation-experience bonus. This is
the one paid, per-posting step in the pipeline, so its cost shape drives
several other decisions (caching, call caps, spend caps).

## Decision

**Model:** `claude-sonnet-5` by default, set via `CLAUDE_MODEL` in `.env`
so it can be changed without a code edit. Pricing at time of writing:
$2.00 / MTok input, $10.00 / MTok output (see `config.py::PRICING`).
Sonnet-tier is the right cost/quality point for a bounded, well-specified
classification/extraction task against a fixed rubric -- this is not
open-ended reasoning.

**Thinking:** explicitly disabled (`thinking: {"type": "disabled"}`).
Extended thinking is for open-ended reasoning; scoring against a fixed
rubric doesn't need it, and leaving it on (Sonnet 5's default) would only
add latency and token cost for no quality gain here.

**Output format:** plain-JSON-in-the-prompt, not a structured-outputs beta
or tool-use. The system prompt tells the model exactly which top-level
keys to return and to emit nothing else; the code strips markdown fences
if present, parses with `json.loads`, and retries once with a sharper
reminder if parsing/validation fails. This keeps the integration portable
across `anthropic` SDK versions rather than pinning to a specific
structured-output API shape.

**Prompt structure and caching:** `briefing.txt` plus the fixed response-
format instructions form the *system* prompt, marked
`cache_control: {"type": "ephemeral"}`. It is byte-identical on every call
in a run (and across runs within the cache TTL), so after the first call,
Anthropic's prompt caching serves it at roughly 10% of input price instead
of full price. Only the per-posting text goes in the user message, which
is never cached (it's different every time).

**Scored once, ever:** `scores.posting_id` is the primary key
(`db.py::save_score` / `has_score`), and the pipeline checks `has_score`
before calling the model at all. A posting is never re-scored, even across
runs, which is both a cost control and the idempotency guarantee the spec
asks for.

## Cost math (see `scripts/estimate_cost.py`)

Assuming ~1,800 system-prompt tokens, ~2,200 posting tokens, ~600 output
tokens, 6 runs/day, and a handful of new postings per run:

- First call in a run (cache write, 1.25x on the system-prompt portion):
  ~$0.015
- Later calls in the same/nearby runs (cache read, 0.1x on the
  system-prompt portion): ~$0.012
- At 5 postings/run: **~$0.06/run, ~$0.38/day, ~$11/month** -- comfortably
  under the default $2/day and $30/month caps.

Real per-call cost is logged to `spend_ledger` from the actual
`response.usage` on every call, so these are pre-launch estimates to
review before scheduling, not the number to trust once real data exists.

## Consequences
- Changing models only requires an `.env` edit plus updating `PRICING` in
  `config.py` if the new model isn't already listed there.
- If `briefing.txt` grows very large, the cache-write cost of the first
  call in each 5-minute cache window becomes the dominant cost term --
  worth revisiting the TTL (`cache_control: {"type": "ephemeral", "ttl":
  "1h"}`) if run cadence and briefing size make that trade-off favorable.
