@echo off
REM Once-daily entry point for Windows Task Scheduler.
cd /d "%~dp0..\.."
"venv\Scripts\python.exe" scripts\run_fractional_scan.py >> logs\cron.log 2>&1
