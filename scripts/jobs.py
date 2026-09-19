#!/usr/bin/env python3
"""Applications-tracker CLI entry point.

    venv/bin/python scripts/jobs.py applied a1b2c3d4
    venv/bin/python scripts/jobs.py status 7 interview
    venv/bin/python scripts/jobs.py list today
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobalerts.cli import cli  # noqa: E402

if __name__ == "__main__":
    cli()
