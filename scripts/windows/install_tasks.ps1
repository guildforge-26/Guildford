# Installs the 3 scheduled tasks for the Job Alert System on Windows.
# No admin rights needed (these are per-user tasks). Run from PowerShell:
#   cd path\to\Guildford
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install_tasks.ps1
#
# Safe to re-run: -Force replaces an existing task of the same name rather
# than erroring.

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "No venv found at $PythonExe`nRun first: python -m venv venv `&`& venv\Scripts\pip install -r requirements.txt"
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "logs") | Out-Null

function Install-JobTask {
    param([string]$Name, [string]$BatPath, $Trigger)
    $Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ProjectDir
    $TaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $TaskSettings -Force | Out-Null
    Write-Host "Registered task: $Name"
}

# Every 4 hours: collect, prefilter, score, alert.
$PipelineTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration (New-TimeSpan -Days 3650)
Install-JobTask -Name "JobAlerts-Pipeline" `
    -BatPath (Join-Path $ProjectDir "scripts\windows\run_pipeline.bat") -Trigger $PipelineTrigger

# Every hour: the digest script itself checks whether it's actually 7am or
# 4pm Mountain time before doing anything (DST-safe -- see run_digest.py).
$DigestTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
Install-JobTask -Name "JobAlerts-Digest" `
    -BatPath (Join-Path $ProjectDir "scripts\windows\run_digest.bat") -Trigger $DigestTrigger

# Once a day: the fractional CFO/COO opportunity scan.
$FractionalTrigger = New-ScheduledTaskTrigger -Daily -At "04:30"
Install-JobTask -Name "JobAlerts-FractionalScan" `
    -BatPath (Join-Path $ProjectDir "scripts\windows\run_fractional_scan.bat") -Trigger $FractionalTrigger

Write-Host ""
Write-Host "Done. Open Task Scheduler (Start menu -> search 'Task Scheduler') and look under"
Write-Host "Task Scheduler Library for JobAlerts-Pipeline, JobAlerts-Digest, JobAlerts-FractionalScan"
Write-Host "to confirm they're there."
Write-Host ""
Write-Host "These only run while your computer is on and awake. A run that's missed because the"
Write-Host "computer was off or asleep is simply skipped -- nothing is lost, since the next run"
Write-Host "looks back further than its own interval (see COLLECT_LOOKBACK_HOURS in .env)."
