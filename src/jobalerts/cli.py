"""`jobs` command-line tool for the applications tracker.

Examples:
    jobs applied a1b2c3d4 --contact "Jane Recruiter"
    jobs status 7 interview
    jobs list today
    jobs list due
    jobs list applications --status applied
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import click

from . import db as dbmod
from . import timeutil
from .config import get_settings


def _add_business_days(start: date, n: int) -> date:
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            added += 1
    return d


def _resolve_posting(conn, id_prefix: str):
    rows = conn.execute("SELECT * FROM postings WHERE id LIKE ?", (f"{id_prefix}%",)).fetchall()
    if not rows:
        raise click.ClickException(f"No posting found matching id prefix {id_prefix!r}")
    if len(rows) > 1:
        candidates = ", ".join(r["id"][:12] for r in rows)
        raise click.ClickException(f"Ambiguous id prefix {id_prefix!r}, matches: {candidates}")
    return rows[0]


@click.group()
def cli():
    """Job Alert System applications tracker."""


@cli.command()
@click.argument("posting_id_prefix")
@click.option("--contact", default=None, help="Contact name/email for this application")
@click.option("--date", "date_applied_str", default=None, help="YYYY-MM-DD, defaults to today")
def applied(posting_id_prefix: str, contact: str | None, date_applied_str: str | None):
    """Record that you applied to a posting (use the short id from an alert)."""
    settings = get_settings()
    date_applied = datetime.strptime(date_applied_str, "%Y-%m-%d").date() if date_applied_str else date.today()
    next_step_due = _add_business_days(date_applied, settings.followup_business_days)

    with dbmod.connect(settings) as conn:
        posting = _resolve_posting(conn, posting_id_prefix)
        app_id = dbmod.add_application(
            conn, posting["id"], posting["company"], posting["title"], contact,
            date_applied.isoformat(), next_step_due.isoformat(),
        )
    click.echo(f"Application #{app_id} recorded: {posting['title']} at {posting['company']}. Follow up by {next_step_due}.")


@cli.command(name="status")
@click.argument("application_id", type=int)
@click.argument("new_status")
@click.option("--next-step", default=None, help="Free-text note on what happens next")
def set_status(application_id: int, new_status: str, next_step: str | None):
    """Update an application's status: applied, interview, offer, rejected, withdrawn, no_response."""
    settings = get_settings()
    with dbmod.connect(settings) as conn:
        updated = dbmod.update_application_status(conn, application_id, new_status, next_step)
    if not updated:
        raise click.ClickException(f"No application #{application_id}")
    click.echo(f"Application #{application_id} -> {new_status}")


@cli.command(name="list")
@click.argument("what", default="today")
@click.option("--status", "status_filter", default=None)
def list_cmd(what: str, status_filter: str | None):
    """what: today | applications | due"""
    settings = get_settings()
    with dbmod.connect(settings) as conn:
        if what == "today":
            since = timeutil.sqlite_utc(timeutil.local_midnight_utc(date.today(), settings.timezone))
            rows = dbmod.scores_with_postings_since(conn, since)
            if not rows:
                click.echo("No scored postings today yet.")
            for r in rows:
                click.echo(f"[{r['id'][:8]}] {r['total_score']:>3} {r['tier']:<7} {r['track']:<7} {r['title']} @ {r['company']} ({r['location'] or 'n/a'})")

        elif what == "due":
            rows = dbmod.applications_due_followup(conn, date.today().isoformat())
            if not rows:
                click.echo("No follow-ups due.")
            for r in rows:
                click.echo(f"#{r['id']} {r['role']} @ {r['company']} -- applied {r['date_applied']}, due {r['next_step_due']}, status {r['status']}")

        elif what == "applications":
            rows = dbmod.list_applications(conn, status_filter)
            if not rows:
                click.echo("No applications.")
            for r in rows:
                click.echo(f"#{r['id']} {r['role']} @ {r['company']} -- {r['status']} (applied {r['date_applied']}, next step due {r['next_step_due']})")

        else:
            raise click.ClickException(f"Unknown list target {what!r}; use today, applications, or due")


if __name__ == "__main__":
    cli()
