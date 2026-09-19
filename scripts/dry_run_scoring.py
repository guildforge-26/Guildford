#!/usr/bin/env python3
"""Manual pre-launch dry run (docs/test_plan.md section 2): scores the
fixtures in tests/fixtures/sample_postings.json through the real pipeline
stages (prefilter -> score) using your real briefing.txt and a real,
live Gemini call for whichever fixtures pass the cheap prefilter.

Requires GEMINI_API_KEY and briefing.txt to be in place. Writes to the
normal DB_PATH (default data/jobs.db) using a throwaway run_id -- this is
NOT a separate scratch database, so re-running it will skip fixtures
already scored (has_score is checked, same as the real pipeline) unless
you delete data/jobs.db first.

Usage:
    venv/bin/python scripts/dry_run_scoring.py
    venv/bin/python scripts/dry_run_scoring.py --fixtures path/to/other.json
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from google import genai  # noqa: E402

from jobalerts import db as dbmod  # noqa: E402
from jobalerts.config import get_settings  # noqa: E402
from jobalerts.dedupe import build_posting_record  # noqa: E402
from jobalerts.prefilter import load_tracks_config, run_prefilter  # noqa: E402
from jobalerts.scoring import ScoringError, score_posting, score_to_db_row  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", default="tests/fixtures/sample_postings.json")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.briefing_path.exists():
        print(f"ERROR: briefing.txt not found at {settings.briefing_path}")
        return 1
    if not settings.gemini_api_key:
        print("ERROR: GEMINI_API_KEY not set")
        return 1

    tracks_config = load_tracks_config(str(settings.tracks_config_path))
    briefing_text = settings.briefing_path.read_text(encoding="utf-8")
    client = genai.Client(api_key=settings.gemini_api_key)

    fixtures = json.loads(Path(args.fixtures).read_text())
    run_id = f"dry_run_{uuid.uuid4().hex[:6]}"
    collected_at = datetime.now(timezone.utc).isoformat()

    with dbmod.connect(settings) as conn:
        for raw in fixtures:
            record = build_posting_record(
                source=raw["source"], source_id=raw.get("source_id"), title=raw["title"],
                company=raw["company"], location=raw.get("location"), url=raw.get("url"),
                salary_text=raw.get("salary_text"), posted_at=raw.get("posted_at"),
                collected_at=collected_at, run_id=run_id,
            )
            posting_id, _ = dbmod.upsert_posting(conn, record)
            if raw.get("raw_text"):
                dbmod.set_posting_enriched(conn, posting_id, raw["raw_text"])

            print(f"\n=== {raw['title']} @ {raw['company']} ===")

            pf = run_prefilter(
                {**record, "raw_text": raw.get("raw_text")}, tracks_config,
                settings.min_salary_usd, settings.min_monthly_retainer_usd,
            )
            if not pf.passed:
                dbmod.set_posting_status(conn, posting_id, "prefiltered_out", pf.reason)
                print(f"PREFILTERED OUT: {pf.reason}")
                continue

            if dbmod.has_score(conn, posting_id):
                print("Already scored in a previous dry run -- skipping (delete data/jobs.db to rescore).")
                continue

            print("Passed prefilter, scoring live with Gemini...")
            posting = dbmod.get_posting(conn, posting_id)
            try:
                result = score_posting(client, settings.gemini_model, settings.pricing, briefing_text, dict(posting))
            except ScoringError as exc:
                print(f"SCORING FAILED: {exc}")
                continue

            row = score_to_db_row(result, settings.gemini_model)
            dbmod.save_score(conn, posting_id, row, run_id)
            print(f"Track: {row['track']}  Tier: {row['tier']}  Score: {row['total_score']}/100")
            print(f"Verified: {bool(row.get('verified', 1))}")
            print(f"Hard filter passed: {bool(row['hard_filter_passed'])}  Reason: {row['hard_filter_reason']}")
            print(f"Breakdown: {row['breakdown_json']}")
            print(f"Matching facts: {row['matching_facts_json']}")
            print(f"Gaps: {row['top_gaps_json']}")
            print(f"Resume version: {row['resume_version']}")
            print(f"Warm angle: {row['warm_angle']}")
            print(f"Next action: {row['next_action']}")
            print(f"Cost: ${row['cost_usd']}  Tokens in/out: {row['input_tokens']}/{row['output_tokens']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
