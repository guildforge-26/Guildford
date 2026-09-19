# ADR-007: Running on Windows via Task Scheduler

## Status
Accepted

## Context
The system needs to run on a machine that's actually on -- and Tommy's
choice for that machine is his own Windows computer, on during the hours
he's job-searching, not a 24/7 Linux/macOS server. Everything up to this
point (`scripts/install_cron.sh`, the guardrails, the docs) was built
assuming cron on a POSIX system, which surfaced two real problems:

1. **A blocking bug, not just a missing feature:** `guardrails.py`'s
   `pipeline_lock()` used `fcntl.flock`, a POSIX-only API. `import fcntl`
   fails immediately on Windows -- every run would have crashed on import
   before doing anything, on any OS branch, cron or not.
2. **`zoneinfo.ZoneInfo("America/Edmonton")` needs IANA timezone data**
   that Linux/macOS ship with the OS but Windows does not.
3. **cron itself doesn't exist on Windows** -- `install_cron.sh` /
   `check_cron.sh` are bash scripts calling `crontab`, neither of which
   run natively on Windows.

## Decision

**Fix the blocking bugs first, independent of which scheduler is used:**
- `pipeline_lock()` rewritten to use atomic file creation
  (`os.open(..., O_CREAT | O_EXCL)`), which is portable across POSIX and
  Windows, instead of `fcntl.flock`. A lock left behind by a crashed run
  used to release automatically (the OS drops `flock` locks when their
  owning process dies) -- the replacement has to detect staleness itself,
  via `psutil.pid_exists()` on the PID recorded in the lock file, since
  plain atomic file creation has no equivalent "owner died" signal.
  `psutil` added to `requirements.txt` for this.
- `tzdata` added to `requirements.txt`. Pure data package, official
  CPython-recommended way to give `zoneinfo` IANA data on platforms that
  don't ship it (Windows); a harmless no-op install everywhere else.

**Scheduler: native Windows Task Scheduler, not WSL.** WSL (Windows
Subsystem for Linux) would have let the existing bash scripts run
unmodified, but it adds a real installation and mental-model burden (a
Linux environment inside Windows, its own always-on-vs-sleep behavior to
reason about) for no benefit here -- the actual Python code underneath is
already cross-platform once the two bugs above are fixed, so there's
nothing Linux-specific left to run inside WSL for. Native Task Scheduler
means no extra layer: `python.exe` in a venv, called by three
`.bat` wrapper scripts (`scripts/windows/run_*.bat`), registered as
per-user scheduled tasks (no admin rights needed) by
`scripts/windows/install_tasks.ps1`, with `scripts/windows/check_tasks.ps1`
as the Task-Scheduler-flavored equivalent of `check_cron.sh`.

**`.bat` wrappers, not calling `python.exe` directly from the task
action.** The wrapper `cd`s into the project root (via `%~dp0..\..`, so it
works regardless of where the repo is cloned) and redirects output to
`logs\cron.log`, mirroring the Linux cron pattern
(`cd project && python script >> logs/cron.log 2>&1`) exactly. This also
means each wrapper is directly double-clickable for a manual test run,
without needing to remember the full command.

**`-StartWhenAvailable` on every task.** If the computer is off or asleep
at a scheduled time, Task Scheduler runs the job as soon as the machine is
next available instead of waiting for the next scheduled slot. This fits
the system's existing design rather than fighting it: postings are
deduplicated and scoring is idempotent, so a "catch-up" run immediately
after wake is simply a normal run, and `COLLECT_LOOKBACK_HOURS` (default
26h, longer than the 4h interval) already exists specifically so a missed
run's postings aren't lost, just collected a bit later.

## Consequences
- The lock and timezone fixes are correctness fixes for every platform,
  not just Windows -- the previous behavior was a latent crash-on-import
  risk that happened to never trigger because every environment this was
  tested in so far was Linux.
- Windows and Linux/macOS setups now genuinely diverge in `README.md`
  (separate command blocks, separate scheduling section) rather than one
  set of instructions with a mental find-and-replace -- worth keeping in
  sync if either path changes.
- Running on a personal computer that isn't always on means the system's
  actual cadence is "every 4 hours while the computer is on," not truly
  "every 4 hours." This was an explicit, informed choice (see the
  conversation that led to this ADR), and the design already tolerates it
  gracefully -- but it does mean postings can sit unscored for longer than
  4 hours if the computer is off overnight, which is worth knowing rather
  than assuming the system is checking around the clock.
