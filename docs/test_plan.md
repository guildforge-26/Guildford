# Test Plan: Job Alert System

## 1. Automated unit tests (`pytest`)

Run with:

```bash
venv/bin/python -m pytest tests/ -v
```

Covers the pure, dependency-free logic:

- `test_dedupe.py` -- URL canonicalization, dedupe-key normalization,
  cross-source duplicate detection.
- `test_prefilter.py` -- geography allow-list, salary-floor parsing, track
  title-matching, disqualifying-requirement detection. Includes the exact
  cases the build spec asks for by hand: a posting under $100,000, a
  posting requiring a CPA, a Machine Learning Engineer title, and an AI
  Operations posting at a Calgary energy company.
- `test_scoring.py` -- JSON extraction/validation from a (mocked) model
  response, cost math (always $0 on the Gemini free tier, tested generically
  in case this ever points at a paid model), DB-row shaping. Does not call
  the live API.
- `test_guardrails.py` -- STOP file, run lock (concurrent-run rejection),
  wall-clock timeout, retry helper, model-call budget, circuit breaker
  trip/reset, spend-cap enforcement.
- `test_db.py` -- idempotency of posting upserts (incl. cross-source
  duplicates), alerts, scores, processed-email tracking, digest log, and
  the follow-up-due query.
- `test_workday_collector.py` -- Workday CXS response parsing and
  pagination against a mocked HTTP layer (per-target failure isolation,
  the all-targets-failed case). Mocked because a live tenant couldn't be
  reached from the sandbox this was built in -- see ADR-001 and
  `targets.yaml`'s note on the one seeded (unverified) target.

These run with no API key, no `briefing.txt`, and no network access, so
they're safe to run anywhere, anytime, including in CI.

## 2. Manual pre-launch tests (run once by hand, with `briefing.txt` and a
   real `GEMINI_API_KEY` in place, BEFORE turning on the cron schedule)

This is what the build spec asks Tommy to see and approve before
scheduling anything:

1. **Run once by hand with sample data.**
   ```bash
   venv/bin/python -c "
   import json, sys; sys.path.insert(0, 'src')
   from jobalerts.pipeline import _store_and_prefilter, _enrich_all, _score_all
   # or: point collectors at tests/fixtures/sample_postings.json instead of
   # live sources for a dry run -- see README 'Dry run with sample data'.
   "
   ```
   Confirm it runs to completion and produces score rows without errors.

2. **Show three scored postings with the full breakdown**, and check each
   score against your own judgment of the fit. Use `jobs list today` or
   read the `scores` table directly:
   ```bash
   venv/bin/python -c "
   import sys; sys.path.insert(0, 'src')
   from jobalerts import db as dbmod
   from jobalerts.config import get_settings
   with dbmod.connect(get_settings()) as conn:
       for row in dbmod.recent_runs(conn, limit=1): print(dict(row))
   "
   ```

3. **Confirm duplicates are dropped and hard filters work**, using
   `tests/fixtures/sample_postings.json`:
   - A posting under $100,000 (Junior Marketing Coordinator, $55,000) is
     dropped by the prefilter before it ever reaches the model.
   - A posting requiring a CPA (Fractional CFO at Northgate Advisory) is
     dropped by the prefilter's disqualifying-requirement check.
   - A Machine Learning Engineer posting (DataForge Inc.) is dropped by
     the prefilter's track-title match -- it never reaches the model.
   - A Director of AI Operations posting at a Calgary energy company
     (Prairie Sky Energy) passes the prefilter (Track 4) and should score
     HIGH once run through the real scoring call with `briefing.txt`.
   - The two duplicate-representation cases in `test_dedupe.py` /
     `test_db.py` show the same job arriving via two sources collapses to
     one row.

4. **Only after Tommy approves the above, turn on the schedule**
   (`scripts/install_cron.sh`, then verify with `scripts/check_cron.sh`).

## 3. Guardrail drills (recommended before go-live, cheap to run)

- Create a `STOP` file mid-run (or before a run) and confirm the run halts
  immediately and logs it.
- Start two runs back to back and confirm the second exits immediately
  with `skipped_lock_held` instead of racing the first.
- Set `MAX_MODEL_CALLS_PER_RUN=1` temporarily and confirm scoring stops
  after one call (`call_budget_exhausted` in the logs) while collection
  keeps working -- this is the guardrail that actually matters on a free,
  rate-limited API. (`DAILY_SPEND_CAP_USD`/`MONTHLY_SPEND_CAP_USD` are kept
  as infrastructure but can't be drilled meaningfully: Gemini's free tier
  is $0/call, so real recorded spend never grows and the cap can't trip --
  see ADR-006.)
- Point a collector at a bad URL/target and confirm the circuit breaker
  trips after `CIRCUIT_BREAKER_FAILURE_THRESHOLD` failures and the run
  still completes for the other sources.

## 4. Ongoing

- `scripts/check_cron.sh` after go-live to confirm the schedule fired and
  see the last few runs' status.
- Weekly metrics summary (postings collected/scored/alerted, applications,
  replies, interviews, cost per alert) -- see the case study for week one.
