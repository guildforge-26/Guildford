@echo off
REM Hourly entry point for Windows Task Scheduler -- the script itself
REM decides internally whether it's actually 7am or 4pm Mountain time.
cd /d "%~dp0..\.."
"venv\Scripts\python.exe" scripts\run_digest.py >> logs\cron.log 2>&1
