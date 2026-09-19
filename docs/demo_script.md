# Demo script (3 minutes): screen recording outline

Fill in the bracketed specifics once the system has real data (post
week-one, alongside `docs/case_study.md`). Structure below is ready to
record against as soon as at least one real alert has fired.

## 0:00-0:20 -- Cold open
"This is a job-alert system I directed Claude Code to build: it reads my
LinkedIn and Indeed alert emails plus public company job boards, scores
every posting against my real background using Gemini's free API, and
pushes me an alert within hours -- without ever scraping LinkedIn/Indeed
or applying on my behalf. Claude Code wrote and tested the whole thing;
Gemini is what actually reads each posting and scores it, at zero cost."

## 0:20-1:00 -- An alert arriving
Show a real ntfy push notification landing on screen (score >= 80).
Open `alerts/YYYY-MM-DD.md` to show the durable log entry next to it.

## 1:00-1:45 -- The score breakdown
Open the digest draft in Gmail (or query the `scores` table) for that
same posting. Walk through: total score, the seven-part breakdown, the
AI/automation bonus, matching facts, top gaps, resume version, warm
angle, next action. "This isn't a keyword match -- it's reasoning against
my actual background, with a paper trail."

## 1:45-2:30 -- Guardrails, live
- Show `scripts/check_cron.sh` output (schedule installed, recent runs).
- Run `scripts/estimate_cost.py`: "$0/call on Gemini's free tier -- the
  actual limit isn't dollars, it's the free tier's daily request quota,
  which this stays comfortably under."
- Create a `STOP` file, run the pipeline by hand, show it halts
  immediately and logs why. Delete the `STOP` file.
- Point at `docs/adr/ADR-003-guardrails-and-safety.md` for the full list,
  and `docs/adr/ADR-006-scoring-model-gemini-free-tier.md` for why the
  scoring engine moved to Gemini and what changed as a result.

## 2:30-2:50 -- The tracker
`jobs list today`, `jobs applied <id>`, `jobs list due` -- show a
follow-up surfacing after 5 business days.

## 2:50-3:00 -- Close
"I specified the requirements, the hard filters, the scoring rubric, and
the guardrails. Claude Code generated and tested the code against them.
Numbers and limits are in the case study -- nothing here is claimed
without a log line behind it."
