"""
lead_store.py
-------------
Keeps every lead you have ever found in a local SQLite file (leads.db) so results
survive restarts, repeat searches can show only NEW leads, and you can reopen all
saved leads later. Your edits (Manual Email / Contacted) stay in cache.json and are
layered on top by place_id, so they work for saved leads too.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DB_FILE = Path(__file__).parent / "leads.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    place_id     TEXT PRIMARY KEY,
    data         TEXT NOT NULL,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    search_label TEXT NOT NULL DEFAULT ''
)
"""

# Columns that are user edits or rebuilt on every run — never stored with the lead
_NOT_STORED = ("Manual Email", "Contacted", "Seen Before", "First Seen", "Last Seen")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def known_ids() -> set[str]:
    with _connect() as conn:
        return {row[0] for row in conn.execute("SELECT place_id FROM leads")}


def version() -> tuple[int, str]:
    """(row count, newest last_seen) — changes whenever the saved leads change."""
    with _connect() as conn:
        n, newest = conn.execute("SELECT COUNT(*), COALESCE(MAX(last_seen), '') FROM leads").fetchone()
    return n, newest


def count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]


def save_leads(df: pd.DataFrame, search_label: str = "") -> None:
    """Insert new leads; refresh data and last_seen of known ones (first_seen is kept)."""
    if df.empty:
        return
    records = json.loads(df.drop(columns=list(_NOT_STORED), errors="ignore").to_json(orient="records"))
    now = _now()
    rows = [(r["place_id"], json.dumps(r, ensure_ascii=False), now, now, search_label) for r in records]
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO leads (place_id, data, first_seen, last_seen, search_label)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(place_id) DO UPDATE SET
                   data = excluded.data, last_seen = excluded.last_seen""",
            rows,
        )


def load_leads() -> pd.DataFrame:
    """All saved leads, most recently seen first (empty DataFrame if none)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT data, first_seen, last_seen FROM leads ORDER BY last_seen DESC, first_seen DESC"
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    records = [{**json.loads(d), "First Seen": first, "Last Seen": last} for d, first, last in rows]
    df = pd.DataFrame(records)
    df["Seen Before"] = True
    return df


def clear() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM leads")
