# Job Alert System

Reads Tommy's LinkedIn/Indeed job-alert emails plus public company job
boards, scores every new posting against his real background with Claude,
and pushes an alert on the strong ones within hours -- without scraping
LinkedIn or Indeed, and without ever applying or messaging on his behalf.

See `docs/requirements.md` for what this does and why, `docs/adr/` for why
it's built this way, and `docs/test_plan.md` for how to verify it before
turning on the schedule.

## 0. Before you do anything else

This repo does **not** contain your real `briefing.txt` (your verified
background, hard filters, target tracks, and scoring rubric) -- it's
gitignored on purpose (hard rule 4 / deliverable 7: no personal data
committed). Copy the template and fill it in:

```bash
cp briefing.txt.example briefing.txt
# edit briefing.txt with your real content
```

Everything below works without it (collection, dedup, prefilter,
guardrails, the CLI), but scoring is disabled until it's present --
the pipeline logs `briefing_missing` and skips scoring rather than erroring.

## 1. Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in what you have so far (see section 2 for the
things only you can do). Anything left blank just means that source/
channel is skipped and logged -- nothing crashes.

Run the tests to confirm the install is sound:

```bash
venv/bin/python -m pytest tests/ -v
```

## 2. What you need to do by hand

1. **Create the LinkedIn and Indeed email alert searches.** Location:
   Calgary, Alberta and Canada (remote) for all. Set each to "daily" or
   "as soon as posted."

   **Track 1:**
   - `"Director of Business Development" OR "Business Development Manager" construction OR engineering OR advisory`
   - `"Client Relationship Director" OR "Strategic Partnerships"`
   - `"Pursuit Manager" OR "Growth Director"`

   **Track 2:**
   - `"Fractional CFO" OR "Interim CFO" OR "Fractional COO" OR "Interim COO"`
   - `"Virtual CFO" OR "Part-time CFO"`

   **Track 3:**
   - `"Chief Operating Officer" OR "COO" small company OR founder-led`
   - `"Integrator" EOS`
   - `"Director of Operations" OR "General Manager" OR "Chief of Staff" founder`

   **Track 4:**
   - `"AI Operations" OR "AI Transformation" OR "Director of Automation" OR "Digital Transformation" Calgary`
   - `"AI Implementation" OR "AI Strategy" OR "Fractional Chief AI Officer" OR "AI Program Manager"`
   - Add "oil and gas" OR energy OR construction OR legal variants of the above for Calgary employers.

2. **Get an Adzuna API key**: register at https://developer.adzuna.com/,
   create an app, put the app ID and key in `.env` as `ADZUNA_APP_ID` /
   `ADZUNA_APP_KEY`.

3. **Choose an ntfy.sh topic**: pick a hard-to-guess private name (e.g.
   `tg-jobs-8f2k1`) and set it as `NTFY_TOPIC` in `.env`. Install the ntfy
   app (iOS/Android) or use https://ntfy.sh/<your-topic> in a browser, and
   subscribe to that topic to receive pushes.

4. **Authorize Gmail** (see section 3 below).

5. **Fill in `targets.yaml`** with the Calgary construction, development
   and advisory firms from your briefing's Part G (see
   `briefing.txt.example` for the format).

## 3. Authorize Gmail

1. In Google Cloud Console, create a project (or use an existing one),
   enable the Gmail API, and create an OAuth client ID of type "Desktop
   app."
2. Download the client secret JSON and save it as `gmail_credentials.json`
   in the project root (path configurable via `GMAIL_CREDENTIALS_PATH`).
3. Set `DIGEST_TO_EMAIL` in `.env` to your own email address.
4. Run anything that touches Gmail once by hand, e.g.:
   ```bash
   venv/bin/python scripts/run_digest.py
   ```
   A browser window opens for a one-time consent screen (read-only mail
   access + draft-only compose access -- it can never send on your
   behalf). The resulting token is cached at `GMAIL_TOKEN_PATH` so future
   runs, including cron, are non-interactive.

## 4. Dry run with sample data

Before touching any live source, you can exercise dedup/prefilter/scoring
against the fixtures in `tests/fixtures/sample_postings.json` (five
postings crafted to hit every case in `docs/test_plan.md` section 2:
under $100k, requires a CPA, an ML Engineer title, an AI Ops role at a
Calgary energy company, and a normal marketing role). See
`docs/test_plan.md` for the exact walkthrough and what to check.

## 5. Estimate cost before scheduling

```bash
venv/bin/python scripts/estimate_cost.py
```

Adjust `--postings-per-run` and `--cache-hit-rate` to match what you
observe once real runs exist. Compare against `DAILY_SPEND_CAP_USD` /
`MONTHLY_SPEND_CAP_USD` in `.env`.

## 6. Run the pre-launch tests, then turn on the schedule

Follow `docs/test_plan.md` section 2 end to end and confirm the scores
match your judgment. **Only after that**, turn on the schedule:

```bash
scripts/install_cron.sh   # adds the 3 cron jobs, safe to re-run
scripts/check_cron.sh     # shows installed jobs, recent runs, log tail
```

Three cron jobs are installed:
- Every 4 hours: collect, prefilter, score, alert (`run_pipeline.py`)
- Every hour: checks if it's 7am or 4pm Mountain time and drafts the
  digest if so, DST-safe (`run_digest.py`)
- Once a day (4:30am): the fractional CFO/COO opportunity scan
  (`run_fractional_scan.py`)

## 7. The kill switch

```bash
touch STOP       # halts all runs immediately, on the next check
rm STOP          # resumes normal operation
```

## 8. Tracking applications

```bash
venv/bin/python scripts/jobs.py applied a1b2c3d4 --contact "Jane Recruiter"
venv/bin/python scripts/jobs.py status 7 interview
venv/bin/python scripts/jobs.py list today
venv/bin/python scripts/jobs.py list due
```

(Consider adding a shell alias so you can just type `jobs ...`:
`alias jobs="/path/to/venv/bin/python /path/to/scripts/jobs.py"`.)

The short id in each alert/digest entry (first 8 characters of the
posting's id) is what you pass to `jobs applied`.

## 9. Where things live

- `data/jobs.db` -- the SQLite database (gitignored).
- `logs/run-YYYY-MM-DD.log` -- structured JSON logs, one line per event,
  every line tagged with a run ID.
- `alerts/YYYY-MM-DD.md` -- every alert of the day, plain text.
- `docs/adr/` -- why things are built this way.
- `docs/case_study.md`, `docs/demo_script.md` -- templates to fill in
  after week one, with real numbers only.

## 10. Privacy

`briefing.txt`, `.env`, `gmail_credentials.json`, `gmail_token.json`,
`data/*.db`, `logs/*.log`, and `alerts/*.md` are all gitignored. Before
sharing this repo publicly, double check `git log` and `git diff` for any
of those having been accidentally committed, and consider stripping
`targets.yaml` and `config/tracks.yaml` of anything you'd rather not
disclose (they contain search-strategy details but no personal data by
design).
