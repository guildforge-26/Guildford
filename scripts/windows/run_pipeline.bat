@echo off
REM Every-4-hours entry point for Windows Task Scheduler.
REM %~dp0 is this file's own folder, so this works regardless of where the
REM repo is cloned to.
cd /d "%~dp0..\.."
"venv\Scripts\python.exe" scripts\run_pipeline.py >> logs\cron.log 2>&1
