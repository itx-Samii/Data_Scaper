"""
pipeline.py
-----------
Follow-up reminders and outreach statistics, built from the Contacted status
(+ the date it was set) stored in cache.json.

Status flow:  Not contacted → Called / Messaged → (Followed up) → Replied → Won
                                                              ↘ Not interested
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

import pandas as pd

NOT_CONTACTED = "Not contacted"
STATUSES = ["Not contacted", "Called", "Messaged", "Followed up", "Replied", "Won", "Not interested"]
WAITING = ("Called", "Messaged")        # contacted once, no answer recorded yet → follow up


def status_counts(cache: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Number of leads per Contacted status (only leads that were contacted)."""
    counts = Counter(
        e["Contacted"] for e in cache.values()
        if e.get("Contacted") and e["Contacted"] != NOT_CONTACTED
    )
    return {s: counts[s] for s in STATUSES if counts.get(s)}


def contacts_per_day(cache: dict[str, dict[str, Any]], days: int = 14) -> pd.Series:
    """Leads whose status was last changed on each of the last `days` days (zero-filled)."""
    today = date.today()
    window = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    seen = Counter(e.get("Contacted On") for e in cache.values() if e.get("Contacted On"))
    return pd.Series([seen.get(d, 0) for d in window], index=window, name="Contacted")


def reply_rate(counts: dict[str, int]) -> float | None:
    """(Replied + Won) / contacted, or None if nobody was contacted yet."""
    contacted = sum(counts.values())
    if not contacted:
        return None
    return (counts.get("Replied", 0) + counts.get("Won", 0)) / contacted


def due_frame(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """
    Leads waiting for an answer for at least `days` days (oldest first). Leads
    contacted before dates were tracked have an unknown date and are listed too.
    Deterministic order — editor callbacks rebuild it to map row positions to leads.
    """
    waiting = df[df["Contacted"].isin(WAITING)].copy()
    contacted_on = pd.to_datetime(waiting["Contacted On"].replace("", pd.NA), errors="coerce")
    waiting["Days Since"] = (pd.Timestamp(date.today()) - contacted_on).dt.days.astype("Int64")
    due = waiting[waiting["Days Since"].isna() | (waiting["Days Since"] >= days)]
    return due.sort_values(["Contacted On", "place_id"], kind="stable").reset_index(drop=True)
