#!/usr/bin/env bash
# Adds the job-alert cron lines without touching any of your existing
# crontab entries. Safe to re-run -- it skips lines that are already there.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "No venv found at ${VENV_PYTHON}."
  echo "Run: cd ${PROJECT_DIR} && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

mkdir -p "${PROJECT_DIR}/logs"

PIPELINE_LINE="0 */4 * * * cd ${PROJECT_DIR} && ${VENV_PYTHON} scripts/run_pipeline.py >> logs/cron.log 2>&1"
DIGEST_LINE="0 * * * * cd ${PROJECT_DIR} && ${VENV_PYTHON} scripts/run_digest.py >> logs/cron.log 2>&1"
FRACTIONAL_LINE="30 4 * * * cd ${PROJECT_DIR} && ${VENV_PYTHON} scripts/run_fractional_scan.py >> logs/cron.log 2>&1"

EXISTING="$(crontab -l 2>/dev/null || true)"
NEW="$EXISTING"

add_if_missing() {
  local line="$1"
  if ! grep -qF "$line" <<< "$NEW"; then
    NEW="$(printf '%s\n%s' "$NEW" "$line")"
    echo "Added: $line"
  else
    echo "Already present, skipping: $line"
  fi
}

add_if_missing "$PIPELINE_LINE"
add_if_missing "$DIGEST_LINE"
add_if_missing "$FRACTIONAL_LINE"

printf '%s\n' "$NEW" | crontab -
echo
echo "Done. Run scripts/check_cron.sh to verify, and 'crontab -l' to see the full table."
