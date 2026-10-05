"""
client_store.py
---------------
Tracks the projects you WON: package, price, how much was paid, deadline, notes.
Stored in clients.json, keyed by the lead's place_id (the lead itself stays in leads.db).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

CLIENTS_FILE = Path(__file__).parent / "clients.json"

DEFAULTS: dict[str, Any] = {
    "Package": "",
    "Price": 0.0,
    "Currency": "USD",
    "Paid": 0.0,
    "Deadline": "",
    "Notes": "",
}
CURRENCIES = ["USD", "GBP", "EUR", "CAD", "AUD", "AED", "SAR", "PKR"]


def load_clients() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_clients(clients: dict[str, dict[str, Any]]) -> None:
    tmp = CLIENTS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CLIENTS_FILE)
    except OSError:
        pass


def clients_frame(won: pd.DataFrame, clients: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """`won` = leads with status Won (needs place_id, Name, Town). Adds the saved project fields."""
    out = won[["place_id", "Name", "Town"]].copy().reset_index(drop=True)
    for field, default in DEFAULTS.items():
        out[field] = out["place_id"].map(lambda p, f=field: clients.get(p, {}).get(f, DEFAULTS[f]))
    out["Price"] = pd.to_numeric(out["Price"], errors="coerce").fillna(0.0)
    out["Paid"] = pd.to_numeric(out["Paid"], errors="coerce").fillna(0.0)
    out["Outstanding"] = (out["Price"] - out["Paid"]).clip(lower=0)
    return out.sort_values(["Name", "place_id"], kind="stable").reset_index(drop=True)


def apply_client_edits(edited_rows: dict[Any, dict[str, Any]], view: pd.DataFrame,
                       clients: dict[str, dict[str, Any]]) -> bool:
    """Write the cells reported by st.data_editor (positions refer to `view`). True if changed."""
    changed = False
    for pos, changes in edited_rows.items():
        pos = int(pos)
        if not 0 <= pos < len(view):
            continue
        pid = view["place_id"].iat[pos]
        for field, value in changes.items():
            if field not in DEFAULTS:
                continue
            if value is None or (isinstance(value, float) and value != value):
                value = DEFAULTS[field]
            if field in ("Price", "Paid"):
                value = max(float(value), 0.0)
            entry = clients.setdefault(pid, {})
            if entry.get(field) != value:
                entry[field] = value
                changed = True
    return changed
