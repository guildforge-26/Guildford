# ADR-006: Scoring model switch -- Claude to Gemini's free tier

## Status
Accepted (supersedes [ADR-002](ADR-002-scoring-model-and-cost.md))

## Context
ADR-002 chose `claude-sonnet-5` and estimated the running cost at roughly
$0.06/run, ~$11/month -- cheap, but not free. Once that estimate was in
hand, Tommy asked to switch the scoring engine to a free API instead,
specifically Google's Gemini, rather than pay even a small monthly amount.
This is a real architecture change, not a config toggle: the two APIs have
different SDKs, different response shapes, different cost models, and
different failure modes.

## Decision

**Model:** `gemini-3.6-flash`, called through a Google AI Studio API key
(`GEMINI_API_KEY`) with no Cloud Billing account attached -- this is what
keeps it genuinely free. Configurable via `GEMINI_MODEL` in `.env`, same
pattern as the old `CLAUDE_MODEL` setting. This was originally built
against `gemini-2.5-flash`, then corrected after Tommy set a real key and
tested it live in a fresh session on 2026-09-19: the older model name
(actually `gemini-2.0-flash`, which that live check happened to try) came
back deprecated/retired, and Google's API pointed to `gemini-3.6-flash` as
current, which returned a real HTTP 200 response. The model lineup had
moved to a 3.x generation faster than expected -- live verification against
a real key caught this; it would not have been caught by code review alone.

**SDK:** `google-genai` (`from google import genai`), the current
first-party Python SDK (the older `google-generativeai` package is
deprecated). `client.models.generate_content(model=..., contents=...,
config=types.GenerateContentConfig(...))`, confirmed directly against the
installed package's own type definitions rather than assumed from
documentation, since API surfaces like this drift and secondhand sources
disagree on details.

**JSON mode instead of prompt-only JSON:** `response_mime_type:
"application/json"` in `GenerateContentConfig` puts the model in native
JSON mode -- a real capability Claude's Messages API doesn't expose the
same way (structured outputs there is a separate, heavier beta surface
that wasn't worth adopting for this). This is strictly better than the
Claude-era approach of just asking nicely for JSON in the prompt: it
guarantees syntactically valid JSON, though not schema-valid JSON, so
`_validate()`'s schema checks and the fence-stripping fallback in
`_extract_json()` stay in place as defense in depth.

**Thinking disabled:** `ThinkingConfig(thinking_budget=0)`, same rationale
as ADR-002's Claude thinking-disabled choice -- this is bounded
classification against a fixed rubric, not open-ended reasoning, and
thinking would only cost latency and tokens against the free tier's
per-minute quota for no quality gain.

**No prompt caching.** ADR-002 cached `briefing.txt` because caching
turned real dollars into fewer real dollars. On a $0/call free tier that
motivation is gone entirely. Gemini does have a context-caching feature,
but it's a heavier, different API (explicit cache objects with their own
lifecycle) that would add real complexity for zero benefit here, so it was
dropped rather than ported. `briefing.txt` is sent in full, every call.

**Cost tracking kept, now always $0.** `PRICING["gemini-3.6-flash"]` has
`input_per_mtok` / `output_per_mtok` both at `0.0`. `compute_cost_usd()`
and the `spend_ledger` table stay wired up -- if Tommy ever attaches Cloud
Billing or points this at a paid model, updating `PRICING` is enough to
make cost tracking real again. Real-world consequence documented plainly
rather than left implicit: with cost always `0.0`, `SpendGuard`'s
cumulative daily/monthly checks can never exceed a positive cap, so the
`DAILY_SPEND_CAP_USD` / `MONTHLY_SPEND_CAP_USD` guardrails are now
permanently inert in practice on the free tier -- they're not deleted
(cheap to keep, meaningful again the moment a paid model is configured),
but they should not be relied on as an active guardrail right now.

**The guardrail that now actually matters: `MAX_MODEL_CALLS_PER_RUN`,**
lowered from 40 (an original placeholder) to 20, then to **3** once
research into the actual free tier landed: third-party reporting
(consistent across several sources, though not confirmed directly against
ai.google.dev/gemini-api/docs/rate-limits from this build environment,
which blocked outbound requests to that domain) put the newer Gemini 3.x
Flash generation's free daily quota as low as ~20 requests/day total --
sharply stricter than older Gemini models' several-hundred-per-day
figures. At 6 runs/day, 3 calls/run keeps total usage (~18/day, plus 1 for
the daily fractional-CFO scan) under that assumed ceiling with a little
headroom; `scripts/estimate_cost.py` was rewritten from a dollar-cost
estimator into a call-volume-vs-free-tier-quota estimator to check this
kind of budget before scheduling. The free tier also enforces a
per-minute cap on top of the daily one, and exceeding either returns a
429. **This RPD figure is unconfirmed against Google's own current
documentation** -- check ai.google.dev/gemini-api/docs/rate-limits for
`gemini-3.6-flash` specifically and adjust `MAX_MODEL_CALLS_PER_RUN` /
`scripts/estimate_cost.py --free-tier-rpd` before trusting this default.

**A real bug fixed alongside this switch, not just a nice-to-have:**
before this change, a posting whose scoring call failed for any reason was
never retried. `postings.dedupe_key` being unique means a posting can only
ever be *collected* once; the pipeline only ever attempted to *score*
postings from the batch it had just collected that run. A posting marked
`status = 'error'` after a failed scoring attempt would sit in the
database forever, never re-queued. This was a latent bug under Claude too
(rare, since paid-tier throughput rarely 429s), but a rate-limited free
tier makes transient scoring failures routine rather than exceptional,
which would have made the bug routinely lose real postings rather than
being a hard-to-trigger edge case. Fixed via `db.py::postings_needing_scoring()` --
every run now also retries any posting that's enriched but has no score
yet, regardless of which run originally collected it.

## Consequences
- Running this system now costs literally $0/month under normal use,
  instead of ADR-002's ~$11/month estimate.
- Scoring quality depends on how gemini-3.6-flash performs against
  `briefing.txt`'s rubric compared to claude-sonnet-5 -- this hasn't been
  measured empirically (no live comparison was run), so the manual
  pre-launch tests in `docs/test_plan.md` §2 are the first real check of
  whether Gemini's scores match Tommy's judgment as well as Claude's would
  have.
- The free-tier rate limit is much tighter than first assumed (3
  calls/run vs. an originally-planned 20-40), discovered only once a real
  key was tested live. Google's Gemini model lineup and free-tier terms
  move fast enough that a number confirmed today may already be stale by
  the time this is read -- re-verify at
  ai.google.dev/gemini-api/docs/rate-limits before raising
  `MAX_MODEL_CALLS_PER_RUN`.
- The free tier's rate limits are a real operational constraint that
  dollar-based guardrails never were: a burst of new postings in one run
  (e.g. after a slow week, or a first run with a large backlog) can now
  hit a 429 in a way a paid Claude account effectively never would at this
  volume. The retry-on-next-run fix keeps this from silently losing
  postings, but it does mean scoring can lag by a run or two under load,
  which didn't happen before.
- Anyone reading `docs/adr/ADR-002` needs the pointer to this document to
  know it no longer reflects reality -- added to its Status line rather
  than rewriting it, so the original Claude-based reasoning stays
  available as a record of what was actually decided and why, and why it
  changed.
