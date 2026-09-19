#!/usr/bin/env bash
# Sanity-checks that the schedule is actually installed and has run.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Crontab entries for this project ==="
crontab -l 2>/dev/null | grep -F "$PROJECT_DIR" || echo "(none found -- run scripts/install_cron.sh)"

echo
echo "=== STOP kill switch ==="
if [[ -f "${PROJECT_DIR}/STOP" ]]; then
  echo "STOP file is PRESENT at ${PROJECT_DIR}/STOP -- all runs will halt immediately."
else
  echo "No STOP file -- runs are enabled."
fi

echo
echo "=== Lock file ==="
if [[ -f "${PROJECT_DIR}/data/pipeline.lock" ]]; then
  echo "Lock file exists (holder PID: $(cat "${PROJECT_DIR}/data/pipeline.lock" 2>/dev/null || echo unknown))."
  echo "If no run is actually in progress, this is stale and safe to investigate/remove."
else
  echo "No lock file -- no run currently in progress."
fi

echo
echo "=== Most recent runs (from the database) ==="
"${PROJECT_DIR}/venv/bin/python" - <<'PYEOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src")) if False else None
sys.path.insert(0, str(Path.cwd() / "src"))
from jobalerts import db as dbmod
from jobalerts.config import get_settings

settings = get_settings()
if not settings.db_path.exists():
    print("No database yet -- no runs recorded.")
else:
    with dbmod.connect(settings) as conn:
        for row in dbmod.recent_runs(conn, limit=10):
            print(f"{row['run_id']:<40} {row['kind']:<10} {row['status']:<10} started {row['started_at']}")
PYEOF

echo
echo "=== Today's log tail ==="
LOGFILE="${PROJECT_DIR}/logs/run-$(date -u +%Y-%m-%d).log"
if [[ -f "$LOGFILE" ]]; then
  tail -n 20 "$LOGFILE"
else
  echo "No log file yet at ${LOGFILE}"
fi
