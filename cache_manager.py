"""
cache_manager.py
----------------
Persists per-lead user edits (Manual Email, Contacted status) to a local
JSON file so they survive app restarts.

Cache is keyed by `place_id` and only ever stores values the user actually
edited (so it stays small and never overwrites one tab's edit with another's).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

CACHE_FILE = Path(__file__).parent / "cache.json"

# Default values for editable fields
EDITABLE_DEFAULTS: dict[str, Any] = {
    "Manual Email": "",
    "Contacted": "Not contacted",
}


def load_cache() -> dict[str, dict[str, Any]]:
    """Load the cache from disk (dropping entries that only hold defaults)."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        pid: entry
        for pid, entry in raw.items()
        if isinstance(entry, dict)
        and any(entry.get(k, d) != d for k, d in EDITABLE_DEFAULTS.items())
    }


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Save the cache dict to disk atomically (write temp file, then replace)."""
    tmp = CACHE_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass  # Fail silently — edits are still in session state


def apply_cache_to_df(df: pd.DataFrame, cache: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """
    Return a copy of `df` with the editable columns filled from the cache.
    Missing values fall back to defaults; an API-provided 'Email' pre-fills
    'Manual Email'.
    """
    out = df.copy()
    pids = out["place_id"]
    api_email = (
        out["Email"].fillna("").astype(str) if "Email" in out.columns
        else pd.Series("", index=out.index)
    )
    for field, default in EDITABLE_DEFAULTS.items():
        cached = pids.map(lambda p, f=field: cache.get(p, {}).get(f))
        fallback = api_email if field == "Manual Email" else default
        out[field] = cached.where(cached.notna(), fallback)
    out["Contacted On"] = pids.map(lambda p: cache.get(p, {}).get("Contacted On", "")).fillna("")
    return out


def apply_edits(
    edited_rows: dict[Any, dict[str, Any]],
    view_df: pd.DataFrame,
    cache: dict[str, dict[str, Any]],
) -> bool:
    """
    Write the cells reported by `st.data_editor` (`edited_rows`: {row_position:
    {column: value}}) into the cache. `view_df` must be the exact frame, in the
    exact order, that was shown in the editor. Returns True if anything changed.
    """
    changed = False
    for pos, changes in edited_rows.items():
        pos = int(pos)
        if not 0 <= pos < len(view_df):
            continue
        pid = view_df["place_id"].iat[pos]
        for field, value in changes.items():
            if field not in EDITABLE_DEFAULTS:
                continue
            if value is None or (isinstance(value, float) and value != value):
                value = EDITABLE_DEFAULTS[field]
            value = str(value).strip() if field == "Manual Email" else value
            entry = cache.setdefault(pid, {})
            if entry.get(field) != value:
                entry[field] = value
                changed = True
                if field == "Contacted":     # date drives the follow-up reminders
                    if value == EDITABLE_DEFAULTS["Contacted"]:
                        entry.pop("Contacted On", None)
                    else:
                        entry["Contacted On"] = date.today().isoformat()
    return changed
