# ADR-003: Guardrails, runaway protection, and safety

## Status
Accepted

## Context
This system runs unattended on a schedule and spends real money per
scoring call. It's also Tommy's portfolio piece, so the guardrails need to
be both real and demonstrable, not just claimed.

## Decision
All of the following live in `src/jobalerts/guardrails.py` unless noted,
and are unit-tested in `tests/test_guardrails.py`:

| Guardrail | Mechanism |
|---|---|
| Run lock (no overlapping runs) | `fcntl.flock` on `data/pipeline.lock`, non-blocking -- a second run gets `LockHeld` and exits immediately as `skipped_lock_held` |
| Kill switch | `check_stop()` raises `StopRequested` if a `STOP` file exists at the project root; checked at run start and again mid-run after enrichment |
| Wall-clock timeout | `RunTimer`, checked between every pipeline stage; default 20 minutes (`RUN_TIMEOUT_SECONDS`) |
| Per-source retries | `with_retries()`, default 3 attempts (`MAX_RETRIES_PER_SOURCE`), used by every collector via `collectors/base.py::run_collector` |
| Circuit breaker | `CircuitBreaker`, backed by the `source_health` table -- a source that fails `CIRCUIT_BREAKER_FAILURE_THRESHOLD` times in a row is paused for `CIRCUIT_BREAKER_COOLDOWN_HOURS`, independent of every other source |
| Model-call budget | `ModelCallBudget`, capped per run at `MAX_MODEL_CALLS_PER_RUN` |
| Daily/monthly spend caps | `SpendGuard`, backed by the `spend_ledger` table (real cost per call, not an estimate) -- when a cap would be exceeded, scoring stops for the rest of the run, an alert is sent (if `NTFY_TOPIC` is set), and collection continues normally |
| Idempotent processing | `postings.dedupe_key` UNIQUE, `scores.posting_id` PK, `alerts` UNIQUE(posting_id, channel, alert_type), `processed_emails.message_id` PK, `digest_log`/`fractional_scan_log` PK on date[, slot] -- a repeated run cannot double-collect, double-score, or double-alert (see `tests/test_db.py`) |
| Nothing outbound without approval | Digests are Gmail **drafts**, created via the `gmail.compose` scope, never sent; there is no code path that calls Gmail's send endpoint or any LinkedIn/Indeed write API |
| Structured logs with a run ID | `logging_utils.py::get_run_logger` -- every log line is a JSON object with `run_id`, written to both stdout and `logs/run-YYYY-MM-DD.log` |
| One source's failure doesn't crash the run | Every collector call is wrapped so an exception becomes a logged error and an empty result, never a crash (hard rule 5); the pipeline's top-level `try/except` is a final safety net that still records the run as `failed` with the error captured, rather than letting cron see a bare traceback |

## Consequences
- These guardrails add a small amount of bookkeeping (extra tables,
  extra checks between stages) in exchange for being independently
  testable and demonstrable -- see the "Guardrail drills" section of
  `docs/test_plan.md` and the 3-minute demo script
  (`docs/demo_script.md`), which shows the STOP switch and a spend-cap
  trip live.
- The circuit breaker and spend caps are deliberately per-source and
  global respectively -- a single dead ATS board slug degrades gracefully
  instead of taking down the whole run, while a runaway cost anywhere
  still halts all scoring.
