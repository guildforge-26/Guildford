#!/usr/bin/env python3
"""Cron entry point: the every-4-hours collect/score/alert run.

    0 */4 * * * /path/to/venv/bin/python /path/to/scripts/run_pipeline.py >> logs/cron.log 2>&1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobalerts.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    result = run_pipeline()
    print(result)
    return 0 if result["status"] in ("success", "partial", "skipped_lock_held", "killed_stop") else 1


if __name__ == "__main__":
    sys.exit(main())
