# Requirements: Job Alert System

Written before/alongside the first code so the build has a fixed target.
Source of truth for *what* to build is the build spec Tommy provided
("CLAUDE CODE BUILD SPEC: 4-HOUR JOB ALERT OPERATION"); source of truth
for candidate facts, hard filters and the scoring rubric is `briefing.txt`
(not committed -- see `briefing.txt.example`).

## 1. Purpose

Find new, real job postings across Tommy's four target tracks, score each
one against his profile, and alert him to the strong ones within hours of
posting -- without scraping LinkedIn or Indeed, and without ever applying
or messaging on his behalf.

## 2. Scope

In scope:
- Reading LinkedIn/Indeed job-alert emails via the Gmail API (read-only).
- Reading public ATS job-board JSON (Greenhouse, Lever, Ashby, Workable)
  for a configurable list of target companies.
- Reading the Adzuna job API (Canada) and, if a real feed is found and
  configured, Job Bank / Government of Canada / municipal feeds.
- Deduplicating, cheaply pre-filtering, enriching and scoring postings
  with Claude, then alerting on strong matches.
- A CLI to track applications and follow-ups.
- Guardrails so the system cannot run away, overspend, or double-alert.

Out of scope (explicitly, per the spec's hard rules):
- Scraping LinkedIn, Indeed, or any site whose terms prohibit it.
- Submitting applications or sending messages on Tommy's behalf.
- Sending anything outbound without a human-reviewable step (digest =
  Gmail *draft*, not a sent email).

## 3. Sources

| Source | What | Why not scraping |
|---|---|---|
| A. Gmail alert emails | LinkedIn/Indeed saved-search emails, read-only Gmail API | Reads mail Tommy already receives; never touches either site directly |
| B. ATS boards | Public Greenhouse/Lever/Ashby/Workable JSON APIs, from `targets.yaml` | These are public, documented-by-convention endpoints meant for embedding a careers page -- not access-controlled or scraped |
| C. Adzuna | Public, keyed job-search API, Canada endpoint | Documented public API with terms that permit this use |
| D. Job Bank / GC / municipal | Public feeds, **off by default** | No documented real-time public postings API was found/verified while building this; wiring exists but is inert until a real feed URL is confirmed (see ADR-001) |

## 4. Hard rules (verbatim intent from the spec)

1. Never scrape a site whose terms prohibit it -- sources above only.
2. Never submit an application or send a message on Tommy's behalf.
3. Never store API keys in code -- `.env`, gitignored.
4. Never send personal details (phone, clearance file numbers, ID numbers)
   anywhere except the scoring model call, and only what `briefing.txt`
   itself contains (it already excludes those fields).
5. If a source fails, log it, keep going, report it in the next digest --
   never crash the run.

## 5. Pipeline

Collect -> deduplicate -> cheap prefilter -> enrich -> score (Claude) ->
store -> alert. See `docs/adr/` for the reasoning behind each stage's
design, and `src/jobalerts/pipeline.py` for the implementation.

## 6. Scoring & alert thresholds

- Score 0-100, seven-part breakdown plus an AI/automation-experience bonus,
  computed by Claude against `briefing.txt`'s rubric.
- Score >= 80 (>= 70 for Track 2 fractional/interim CFO/COO): immediate
  push notification.
- Score 65-79: included in the next digest.
- A posting is scored exactly once, ever (cached via the `scores` table).

## 7. Guardrails (see ADR-003 for the full list and how each is tested)

Run lock, STOP kill switch, 20-minute wall-clock timeout, max retries per
source, circuit breaker per source, per-run model-call cap, daily/monthly
spend caps, idempotent processing throughout, structured logs with a run
ID on every line.

## 8. Applications tracking

A local `applications` table plus a `jobs` CLI (`jobs applied`, `jobs
status`, `jobs list`), with 5-business-day follow-up due dates surfaced in
the digest.

## 9. Cost control

Estimated and shown before scheduling (`scripts/estimate_cost.py`), capped
per run and per day/month, with real cost logged per call.

## 10. Deliverables

Code, README, `targets.yaml`, `.env.example`, the scheduled jobs, ADRs, a
test plan, weekly metrics, and (end of week one) a case study.

## 11. Open items pending `briefing.txt`

The scaffold in this repo works end-to-end on its infrastructure (DB,
guardrails, collectors, pipeline plumbing, CLI, tests) without
`briefing.txt`. What's blocked until it's provided:
- The actual scoring rubric and hard filters used in `scoring.py`'s system
  prompt (currently it just reads whatever's at `briefing.txt` verbatim).
- `targets.yaml`'s company list (spec Part G).
- `config/tracks.yaml`'s title-keyword lists and disqualifying-phrase list
  are placeholders inferred from the spec's own search-string appendix and
  test instructions -- confirm/replace once the real briefing is available.
