"""SQLite persistence for Executive OS (Feature 1: Conversational Onboarding).

Tables created here follow the schema in PROJECT-BLUEPRINT.md §4:
Companies, Seats, Responsibilities, KPIs. Scorecards and ActionItems
belong to later features and are intentionally not created yet.
"""

import os
import sqlite3
from datetime import datetime, timezone

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "executive_os.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet. Never drops or overwrites data."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS Companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                problem_statement TEXT,
                solution TEXT,
                revenue_model TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS Seats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES Companies(id),
                seat_name TEXT NOT NULL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS Responsibilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seat_id INTEGER NOT NULL REFERENCES Seats(id),
                description_1 TEXT,
                description_2 TEXT,
                description_3 TEXT,
                description_4 TEXT,
                description_5 TEXT
            );

            CREATE TABLE IF NOT EXISTS KPIs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seat_id INTEGER NOT NULL REFERENCES Seats(id),
                kpi_name TEXT NOT NULL,
                target_metric TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_onboarding(data: dict) -> int:
    """Persist a completed onboarding payload. Returns the new company id.

    Expected shape:
    {
        "company": {"name", "problem_statement", "solution", "revenue_model"},
        "seats": [
            {
                "seat_name", "description",
                "responsibilities": [5 strings],
                "kpis": [{"kpi_name", "target_metric"}, ...]
            },
            ...
        ]
    }
    """
    company = data["company"]
    seats = data.get("seats", [])

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO Companies (name, problem_statement, solution, revenue_model, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                company["name"],
                company.get("problem_statement", ""),
                company.get("solution", ""),
                company.get("revenue_model", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        company_id = cur.lastrowid

        for seat in seats:
            cur.execute(
                "INSERT INTO Seats (company_id, seat_name, description) VALUES (?, ?, ?)",
                (company_id, seat["seat_name"], seat.get("description", "")),
            )
            seat_id = cur.lastrowid

            responsibilities = list(seat.get("responsibilities", []))[:5]
            responsibilities += [""] * (5 - len(responsibilities))
            cur.execute(
                """INSERT INTO Responsibilities
                   (seat_id, description_1, description_2, description_3, description_4, description_5)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (seat_id, *responsibilities),
            )

            for kpi in seat.get("kpis", []):
                cur.execute(
                    "INSERT INTO KPIs (seat_id, kpi_name, target_metric) VALUES (?, ?, ?)",
                    (seat_id, kpi["kpi_name"], kpi.get("target_metric", "")),
                )

        conn.commit()
        return company_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_latest_company() -> dict | None:
    """Read the most recently created company, with its seats/responsibilities/KPIs, fresh from SQLite."""
    conn = get_connection()
    try:
        company_row = conn.execute(
            "SELECT * FROM Companies ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if company_row is None:
            return None

        company = dict(company_row)
        seats = []
        for seat_row in conn.execute(
            "SELECT * FROM Seats WHERE company_id = ? ORDER BY id", (company["id"],)
        ).fetchall():
            seat = dict(seat_row)

            resp_row = conn.execute(
                "SELECT * FROM Responsibilities WHERE seat_id = ? ORDER BY id LIMIT 1",
                (seat["id"],),
            ).fetchone()
            responsibilities = (
                [resp_row[f"description_{i}"] for i in range(1, 6) if resp_row[f"description_{i}"]]
                if resp_row
                else []
            )

            kpis = [
                dict(k)
                for k in conn.execute(
                    "SELECT kpi_name, target_metric FROM KPIs WHERE seat_id = ? ORDER BY id",
                    (seat["id"],),
                ).fetchall()
            ]

            seat["responsibilities"] = responsibilities
            seat["kpis"] = kpis
            seats.append(seat)

        company["seats"] = seats
        return company
    finally:
        conn.close()
