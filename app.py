"""
app.py
------
Data Scalper — Lead Generation Tool
Streamlit app that searches Geoapify / Google Places for businesses,
classifies them by website presence, and surfaces "Needs Website" leads.
"""

from __future__ import annotations

import html
import io
import os
import re
import urllib.parse
import zipfile
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import client_store
import lead_store
from cache_manager import CACHE_FILE, EDITABLE_DEFAULTS, apply_cache_to_df, apply_edits, load_cache, save_cache
from countries import COUNTRIES, DEFAULT_COUNTRY
from companies_house import CompaniesHouseDB, parse_uploaded_companies_file
from companies_house_api import MAX_COMPANIES, SIC_PRESETS, search_companies, sic_codes_for
from geoapify_api import GEOAPIFY_CATEGORIES, search_geoapify
from lead_scorer import SCORE_WEIGHTS, score_dataframe
from mockup import build_zip, render_mockup, slug
from outreach import (
    DEFAULT_SETTINGS, PLACEHOLDERS, SETTINGS_FILE, add_outreach, chatgpt_prompt, load_settings,
    phone_type, render, save_settings, whatsapp_digits,
)
from pipeline import STATUSES, contacts_per_day, due_frame, reply_rate, status_counts
from overture_api import MAX_OVERTURE_RESULTS, OVERTURE_CATEGORIES, search_overture
from places_api import CATEGORY_TYPES, MAX_PLACES_RESULTS, search_places
from ai_generator import AIError, PROVIDERS as AI_PROVIDERS, STYLES as AI_STYLES, generate_site, website_prompt
from website_classifier import classify_website

# ---------------------------------------------------------------------------
# Config & page setup
# ---------------------------------------------------------------------------

load_dotenv()

st.set_page_config(
    page_title="Data Scalper — Lead Gen",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

OVERTURE = "Overture Maps (free · worldwide · phone + email)"
APP_CSS = """
<style>
:root { --ink:#0f172a; --muted:#64748b; --line:#e6e8f0; --soft:#eef0f8; --brand:#4f46e5; --brand2:#7c3aed; }
.block-container { padding-top: 4.2rem; padding-bottom: 3rem; max-width: 1480px; }

/* ---------- header + KPI cards ---------- */
.ds-top { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:18px; margin:0 0 18px; }
.ds-title h1 { font-size:1.75rem; line-height:1.15; margin:0; padding:0; letter-spacing:-.02em; color:var(--ink); }
.ds-title p { margin:4px 0 0; color:var(--muted); font-size:.98rem; }
.ds-kpis { display:grid; grid-template-columns:repeat(5, minmax(118px, 1fr)); gap:10px; flex:1; min-width:560px; max-width:860px; }
.ds-kpi { background:#fff; border:1px solid var(--line); border-radius:14px; padding:11px 15px;
          box-shadow:0 1px 2px rgba(15,23,42,.04); position:relative; overflow:hidden; }
.ds-kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
                  background:linear-gradient(180deg,var(--brand),var(--brand2)); }
.ds-kpi b { display:block; font-size:1.55rem; line-height:1.1; color:var(--ink); }
.ds-kpi span { white-space:nowrap; font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; font-weight:700; }

/* ---------- search card ---------- */
.st-key-searchcard { background:#fff; border:1px solid var(--line) !important; border-radius:18px !important;
                     padding:6px 10px 4px; box-shadow:0 8px 30px rgba(79,70,229,.08); margin-bottom:14px; }
.st-key-searchcard [data-testid="stWidgetLabel"] p { font-size:.78rem; font-weight:600; color:var(--muted); }
.st-key-searchcard div[role="radiogroup"] { gap:8px; flex-wrap:wrap; }
.st-key-searchcard div[role="radiogroup"] label { background:var(--soft); border:1px solid transparent; border-radius:999px;
                                                  padding:5px 14px 5px 10px; }
.st-key-searchcard div[role="radiogroup"] label:has(input:checked) { background:#eef2ff; border-color:#a5b4fc; }
.st-key-searchcard div[role="radiogroup"] label p { font-weight:600; font-size:.9rem; }

/* ---------- tabs as a segmented control ---------- */
[role="tablist"] { gap:6px; background:#e8ebf5; padding:5px; border-radius:13px; width:fit-content; max-width:100%; overflow-x:auto; }
div[data-orientation="horizontal"]:has(> [role="tablist"]) { border-bottom:0 !important; box-shadow:none !important; }
[data-testid="stTab"] { border-radius:9px; padding:7px 15px; height:auto; }
[data-testid="stTab"] p { font-weight:600; color:#475569; }
[data-testid="stTab"][data-selected="true"] { background:#fff; box-shadow:0 1px 4px rgba(15,23,42,.14); }
[data-testid="stTab"][data-selected="true"] p { color:var(--brand); }
.react-aria-SelectionIndicator { display:none !important; }
[role="tabpanel"] { padding-top:16px; }

/* ---------- lead workspace ---------- */
.st-key-leadcard { background:#fff; border:1px solid var(--line) !important; border-radius:18px !important;
                   padding:10px 14px 8px; box-shadow:0 8px 30px rgba(15,23,42,.06); margin-top:16px; }
.ds-lead h2 { font-size:1.45rem; margin:0; padding:0; letter-spacing:-.01em; color:var(--ink); }
.ds-lead p { margin:2px 0 8px; color:var(--muted); font-size:.92rem; }
.ds-badge { display:inline-block; padding:3px 11px; margin:0 6px 4px 0; border-radius:999px; font-size:.76rem;
            font-weight:700; background:#eef2ff; color:#4338ca; border:1px solid #e0e7ff; }
.ds-badge.red { background:#fff1f2; color:#be123c; border-color:#fecdd3; }
.ds-badge.amber { background:#fffbeb; color:#b45309; border-color:#fde68a; }
.ds-badge.green { background:#ecfdf5; color:#047857; border-color:#a7f3d0; }
.ds-badge.gray { background:#f1f5f9; color:#475569; border-color:#e2e8f0; }
.ds-kv { display:grid; grid-template-columns:150px 1fr; gap:8px 14px; font-size:.93rem; }
.ds-kv div:nth-child(odd) { color:var(--muted); font-weight:600; }
.ds-empty { text-align:center; padding:46px 20px; border:2px dashed #d5d9ea; border-radius:18px; background:#fafbff; color:var(--muted); }
.ds-empty b { display:block; color:var(--ink); font-size:1.15rem; margin-bottom:4px; }

/* ---------- widgets ---------- */
[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:14px; padding:10px 14px;
                           box-shadow:0 1px 2px rgba(15,23,42,.04); }
[data-testid="stMetricLabel"] p { font-size:.78rem; font-weight:600; color:var(--muted); }
.stButton > button, .stDownloadButton > button, .stLinkButton > a { border-radius:11px; font-weight:600; }
.stButton > button[kind="primary"] { background:linear-gradient(135deg,var(--brand),var(--brand2)); border:0;
                                     box-shadow:0 4px 14px rgba(79,70,229,.35); }
.stButton > button[kind="primary"]:hover { filter:brightness(1.07); }
[data-testid="stExpander"] { border-radius:14px; border-color:var(--line); background:#fff; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
h3 { margin-top:.4rem; }

/* ---------- sidebar ---------- */
.ds-brand { display:flex; gap:12px; align-items:center; margin:2px 0 14px; }
.ds-logo { width:42px; height:42px; border-radius:12px; display:grid; place-items:center; font-size:1.3rem;
           background:linear-gradient(135deg,#6366f1,#a855f7); box-shadow:0 6px 16px rgba(99,102,241,.45); }
.ds-brand b { display:block; font-size:1.12rem; color:#fff; line-height:1.15; }
.ds-brand span { font-size:.76rem; color:#94a3b8; }
.ds-steps { display:grid; gap:7px; margin:4px 0 6px; font-size:.86rem; color:#cbd5e1; }
.ds-steps i { display:inline-grid; place-items:center; width:21px; height:21px; border-radius:50%; margin-right:9px;
              background:#334155; color:#e2e8f0; font-style:normal; font-size:.72rem; font-weight:700; }
section[data-testid="stSidebar"] .stButton > button { width:100%; }
section[data-testid="stSidebar"] [data-testid="stExpander"] { background:#162033; border-color:#263349; }
section[data-testid="stSidebar"] hr { border-color:#263349; }
</style>
"""

GEOAPIFY = "Geoapify (100% Free - No Card)"
GOOGLE = "Google Places (New)"
COMPANIES_HOUSE = "Companies House API (new UK companies)"

CONTACTED_OPTIONS = STATUSES
NEEDS_STATUSES = ["NO WEBSITE", "SOCIAL ONLY"]
SOURCE_LABELS = {
    OVERTURE: "Overture Maps",
    GEOAPIFY: "Geoapify / OpenStreetMap",
    GOOGLE: "Google Places API (New)",
    COMPANIES_HOUSE: "Companies House",
}
STRING_COLS = [
    "Name", "Address", "Town", "Phone", "Intl Phone", "Website", "Email", "Business Status", "Types",
    "Director Name",
]


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults = {
        "df": None,            # enriched + scored results (edits are layered on from the cache)
        "cache": None,         # dict loaded from cache.json
        "ch_db": None,         # CompaniesHouseDB | None
        "ch_sig": None,        # (filename, size) of the loaded Companies House file
        "search_done": False,
        "search_error": "",
        "notes": [],
        "edit_ver": 0,         # bumped after each edit so both editors rebuild from the cache
        "search_label": "",    # keyword/category of the last search (used in message text)
        "outreach": None,      # sender details + templates (persisted to outreach_settings.json)
        "clients": None,       # won projects (persisted to clients.json)
        "ai_sites": {},        # place_id -> (html, warnings, provider) generated this session
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
    if st.session_state["cache"] is None:
        st.session_state["cache"] = load_cache()
    if st.session_state["outreach"] is None:
        st.session_state["outreach"] = load_settings()
    if st.session_state["clients"] is None:
        st.session_state["clients"] = client_store.load_clients()
    for k, v in st.session_state["outreach"].items():
        st.session_state.setdefault(f"o_{k}", v)


def _reset_templates() -> None:
    for k in ("subject", "email_body", "whatsapp", "followup"):
        st.session_state[f"o_{k}"] = DEFAULT_SETTINGS[k]


_init_state()
st.html(APP_CSS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_one(
    provider: str, api_key: str, keyword: str, category: str, city: str,
    lat: float | None, lng: float | None, radius_km: float, max_results: int,
    sic_codes: tuple[str, ...] = (), months: int = 0, fetch_directors: bool = False,
    country: str = "", exclude_chains: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One provider call for one place."""
    notes: list[str] = []
    if provider == OVERTURE:
        raw = search_overture(
            keyword=keyword, category_key=category, city=city, lat=lat, lon=lng,
            radius_km=radius_km, max_results=max_results, country=country, notes=notes,
            exclude_chains=exclude_chains,
        )
    elif provider == COMPANIES_HOUSE:
        raw = search_companies(
            api_key, sic_codes=sic_codes, location=city, name_includes=keyword,
            months=months, max_results=max_results, fetch_directors=fetch_directors, notes=notes,
        )
    elif provider == GEOAPIFY:
        raw = search_geoapify(
            api_key, keyword=keyword, category_key=category, city=city,
            lat=lat, lon=lng, radius_km=radius_km, max_results=max_results, notes=notes,
            country=country,
        )
    else:
        raw = search_places(
            api_key, keyword=keyword, category=category, city=city,
            lat=lat, lng=lng, radius_km=radius_km, max_results=max_results, notes=notes,
            country=country,
        )
    return raw, notes


@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def _run_search(
    provider: str, api_key: str, keyword: str, category: str, city: str,
    lat: float | None, lng: float | None, radius_km: float, max_results: int,
    sic_codes: tuple[str, ...] = (), months: int = 0, fetch_directors: bool = False,
    country: str = "", exclude_chains: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Search every place in `city` (separated by ';'), merge and de-duplicate.
    Cached for 1 h so repeating a search doesn't burn API quota.
    """
    places = [c.strip() for c in re.split(r"[;\n]", city) if c.strip()] or [""]
    raw: list[dict[str, Any]] = []
    notes: list[str] = []
    seen: set[str] = set()
    last_error: RuntimeError | None = None
    for place in places:
        try:
            part, part_notes = _search_one(
                provider, api_key, keyword, category, place, lat, lng, radius_km,
                max_results, sic_codes, months, fetch_directors, country, exclude_chains,
            )
        except RuntimeError as e:
            if len(places) == 1:
                raise
            last_error = e
            notes.append(f"{place}: {e}")
            continue
        notes.extend(f"{place}: {n}" if len(places) > 1 else n for n in part_notes)
        for r in part:
            if r["place_id"] not in seen:
                seen.add(r["place_id"])
                raw.append(r)
    if not raw and last_error is not None:
        raise last_error
    return raw, list(dict.fromkeys(notes))


def _google_search_url(query: str) -> str:
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": query})


def _enrich(raw: list[dict[str, Any]], ch_db: CompaniesHouseDB | None, default_cc: str,
            hide_closed: bool, source: str = "", skip_chains: bool = False) -> pd.DataFrame:
    """Turn raw provider rows into the scored results table."""
    df = pd.DataFrame(raw)
    for col in STRING_COLS:
        df[col] = df[col].fillna("").astype(str) if col in df.columns else ""
    if hide_closed:
        df = df[~df["Business Status"].str.upper().str.startswith("CLOSED")]
    df = df.reset_index(drop=True)
    df["Source"] = source

    # The same business twice (two providers, repeated listing): keep the first
    digits = df["Phone"].str.replace(r"\D", "", regex=True).str[-9:]
    name_key = df["Name"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    dup_key = name_key + "|" + digits.where(digits != "", df["Town"].str.lower())
    df = df[~dup_key.duplicated()].reset_index(drop=True)

    if skip_chains and not df.empty:      # same name 3+ times in one search = chain / franchise
        chain_key = df["Name"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
        df = df[chain_key.map(chain_key.value_counts()) < 3].reset_index(drop=True)

    classified = [classify_website(w) for w in df["Website"]]
    df["Website Status"] = [c[0] for c in classified]
    df["Social Link"] = [c[1] or "" for c in classified]

    # Director: keep one already supplied (Companies House API / CSV), else look it up in the CSV index
    use_ch = ch_db is not None and ch_db.has_directors
    df["Director Name"] = [
        known or (ch_db.get_director(n) if use_ch else "")
        for n, known in zip(df["Name"], df["Director Name"])
    ]

    # Landlines can't use WhatsApp: only mobile / international numbers get a wa.me number
    df["Phone Type"] = [phone_type(i, p, default_cc) for i, p in zip(df["Intl Phone"], df["Phone"])]
    df["WhatsApp Digits"] = [whatsapp_digits(i, p, default_cc) for i, p in zip(df["Intl Phone"], df["Phone"])]
    df["WhatsApp Link"] = [f"https://wa.me/{d}" if d else "" for d in df["WhatsApp Digits"]]

    google = df["Google Search"].fillna("") if "Google Search" in df.columns else [""] * len(df)
    df["Google Search"] = [
        g or _google_search_url(f'"{n}" {t}') for g, n, t in zip(google, df["Name"], df["Town"])
    ]
    df["Facebook Search"] = [
        _google_search_url(f'"{n}" {t} facebook') if n else ""
        for n, t in zip(df["Name"], df["Town"])
    ]
    df["LinkedIn Search"] = [
        _google_search_url(f'"{d}" site:linkedin.com') if d else "" for d in df["Director Name"]
    ]
    return score_dataframe(df)


def _needs_view(df: pd.DataFrame) -> pd.DataFrame:
    """Needs-Website leads sorted by score. Deterministic, so callbacks can rebuild it."""
    needs = df[df["Website Status"].isin(NEEDS_STATUSES)]
    return needs.sort_values("Lead Score", ascending=False, kind="stable").reset_index(drop=True)


def _store_and_filter(df: pd.DataFrame, label: str, hide_contacted: bool, only_new: bool) -> pd.DataFrame:
    """Save every lead found, then hide the ones the user doesn't want to see again."""
    df["Seen Before"] = df["place_id"].isin(lead_store.known_ids())
    lead_store.save_leads(df, label)

    cache = st.session_state["cache"]
    default = EDITABLE_DEFAULTS["Contacted"]
    contacted = {pid for pid, e in cache.items() if e.get("Contacted", default) != default}
    keep = pd.Series(True, index=df.index)
    if hide_contacted:
        keep &= ~df["place_id"].isin(contacted)
    if only_new:
        keep &= ~df["Seen Before"]

    notes = st.session_state["notes"]
    notes.append(
        f"{len(df):,} found: {int((~df['Seen Before']).sum()):,} new, "
        f"{int(df['Seen Before'].sum()):,} already saved. "
        + (f"Hidden: {int((~keep).sum()):,} (contacted / not new). " if (~keep).any() else "")
        + "All are saved in leads.db."
    )
    return df[keep].reset_index(drop=True)


@st.cache_data(show_spinner=False)
def _saved_leads(version: tuple[int, str]) -> pd.DataFrame | None:
    """All saved leads, prepared. `version` only exists so the cache refreshes when the DB changes."""
    return _prepare_saved(lead_store.load_leads())


def _followup_df(days: int) -> pd.DataFrame:
    """Saved leads waiting for an answer ≥ `days` days. Same order everywhere (see due_frame)."""
    saved = _saved_leads(lead_store.version())
    if saved is None:
        return pd.DataFrame(columns=["place_id", "Contacted"])
    return due_frame(apply_cache_to_df(saved, st.session_state["cache"]), days)


_STRING_RESTORE = STRING_COLS + [
    "Website Status", "Social Link", "Phone Type", "WhatsApp Digits", "WhatsApp Link",
    "Facebook Search", "LinkedIn Search", "Google Search", "Source",
]


def _prepare_saved(df: pd.DataFrame) -> pd.DataFrame | None:
    """Saved leads → same shape as a fresh search (missing columns restored, re-scored)."""
    if df.empty:
        return None
    for col in _STRING_RESTORE:
        df[col] = df[col].fillna("").astype(str) if col in df.columns else ""
    return score_dataframe(df)


def _on_edit(editor_key: str, view_name: str) -> None:
    """data_editor callback: persist only the cells the user changed, then rebuild both editors."""
    edited = (st.session_state.get(editor_key) or {}).get("edited_rows", {})
    cache = st.session_state["cache"]
    if edited:
        if view_name == "followups":
            view = _followup_df(int(st.session_state.get("followup_days", 4)))
        else:
            df = apply_cache_to_df(st.session_state["df"], cache)
            view = df if view_name == "all" else _needs_view(df)
        if apply_edits(edited, view, cache):
            save_cache(cache)
    st.session_state["edit_ver"] += 1


def _set_lead_field(pid: str, field: str, key: str) -> None:
    """Widget callback: save one field (Contacted / Manual Email) of one lead."""
    cache = st.session_state["cache"]
    if apply_edits({0: {field: st.session_state[key]}}, pd.DataFrame({"place_id": [pid]}), cache):
        save_cache(cache)
    st.session_state["edit_ver"] += 1


def _step_focus(pids: list[str], delta: int) -> None:
    """Prev / Next buttons of the lead workspace."""
    cur = st.session_state.get("focus_pid")
    i = pids.index(cur) if cur in pids else 0
    st.session_state["focus_pid"] = pids[max(0, min(len(pids) - 1, i + delta))]


def _empty_state(title: str, text: str) -> None:
    st.markdown(f'<div class="ds-empty"><b>{html.escape(title)}</b>{html.escape(text)}</div>', unsafe_allow_html=True)


def _badge(text: str, tone: str = "") -> str:
    return f'<span class="ds-badge {tone}">{html.escape(text)}</span>'


def _link(url: str, label: str, new_tab: bool = True) -> str:
    if not url:
        return ""
    target = ' target="_blank" rel="noopener noreferrer"' if new_tab else ""
    return f'<a href="{html.escape(url, quote=True)}"{target}>{label}</a>'


LEADS_TABLE_CSS = """
<style>
.leads-table { border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; border-radius: 12px; overflow: hidden; }
.leads-table th { background: #eef0f8; color: #334155; padding: 8px 10px; text-align: left; border-bottom: 2px solid #dfe3f1; }
.leads-table td { padding: 7px 10px; border-bottom: 1px solid #edf0f7; vertical-align: middle; color: #0f172a; }
.leads-table tr:hover td { background: #f6f7ff; }
.leads-table a { color: #4f46e5; text-decoration: none; font-weight: 600; }
.leads-table a:hover { text-decoration: underline; }
</style>
"""


def _backup_zip() -> bytes:
    """Everything you would hate to lose: leads, your edits, clients, templates."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in (lead_store.DB_FILE, CACHE_FILE, client_store.CLIENTS_FILE, SETTINGS_FILE):
            if path.exists():
                zf.write(path, path.name)
    return buf.getvalue()


def _won_df() -> pd.DataFrame:
    """Saved leads whose status is Won."""
    saved = _saved_leads(lead_store.version())
    if saved is None:
        return pd.DataFrame(columns=["place_id", "Name", "Town"])
    won = {pid for pid, e in st.session_state["cache"].items() if e.get("Contacted") == "Won"}
    return saved[saved["place_id"].isin(won)]


def _clients_view() -> pd.DataFrame:
    return client_store.clients_frame(_won_df(), st.session_state["clients"])


def _on_client_edit(editor_key: str) -> None:
    edited = (st.session_state.get(editor_key) or {}).get("edited_rows", {})
    if edited and client_store.apply_client_edits(edited, _clients_view(), st.session_state["clients"]):
        client_store.save_clients(st.session_state["clients"])
    st.session_state["edit_ver"] += 1


def _show_html(page: str, height: int = 640) -> None:
    """Render a full HTML page inline (st.iframe on current Streamlit, components.html on older)."""
    if hasattr(st, "iframe"):
        st.iframe(page, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(page, height=height, scrolling=True)


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")   # BOM so Excel reads UTF-8


# ---------------------------------------------------------------------------
# Sidebar — configuration
# ---------------------------------------------------------------------------

def _has_key(env: str) -> bool:
    v = os.getenv(env, "").strip()
    return bool(v) and not v.lower().startswith("your_")


def _key_input(label: str, env: str, **kw) -> str:
    """API key field: hidden when the key is already in .env, otherwise a password box."""
    if _has_key(env):
        st.caption(f"🔑 {label} loaded from .env")
        return os.getenv(env, "").strip()
    return st.text_input(label, value=os.getenv(env, ""), type="password", **kw)


SOURCE_SHORT = {
    OVERTURE: "🌍 Overture Maps · free",
    GEOAPIFY: "🗺️ Geoapify",
    GOOGLE: "📍 Google Places",
    COMPANIES_HOUSE: "🇬🇧 UK Companies House",
}

with st.sidebar:
    st.markdown(
        '<div class="ds-brand"><div class="ds-logo">🔍</div>'
        '<div><b>Data Scalper</b><span>Lead finder for web designers</span></div></div>'
        '<div class="ds-steps">'
        '<div><i>1</i>Search a niche + city</div>'
        '<div><i>2</i>Pick a lead from the list</div>'
        '<div><i>3</i>Send the ready message</div>'
        '<div><i>4</i>Follow up · mark Won</div></div>',
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown("##### 🗂️ Your leads")
    st.caption(f"{lead_store.count():,} leads saved in leads.db — kept after you close the app.")
    load_saved = st.button("📂 Open all saved leads", width="stretch")
    if st.button("💾 Prepare backup (.zip)", width="stretch"):
        st.session_state["backup_zip"] = _backup_zip()
    if st.session_state.get("backup_zip"):
        st.download_button(
            "⬇️ Download backup", st.session_state["backup_zip"],
            file_name=f"data-scalper-backup-{date.today().isoformat()}.zip", mime="application/zip",
            width="stretch",
        )
        st.caption("Keep it somewhere safe (leads, your edits, clients, templates).")
    with st.expander("🗑️ Delete saved leads"):
        sure = st.checkbox("Yes, delete ALL saved leads")
        if st.button("Delete", disabled=not sure):
            lead_store.clear()
            st.rerun()

    st.divider()

    with st.expander("✉️ Your details & message templates"):
        st.text_input("Your name", key="o_sender_name")
        st.text_input("Your business (optional)", key="o_sender_business")
        st.text_input("Phone / WhatsApp (shown in signature)", key="o_sender_phone")
        st.text_input("Portfolio / website link", key="o_portfolio")
        st.text_input("Turnaround (days)", key="o_days")
        st.text_input("Email subject", key="o_subject")
        st.text_area("Email body", key="o_email_body", height=320)
        st.text_area("WhatsApp message", key="o_whatsapp", height=170)
        st.text_area("Follow-up message (sent a few days later)", key="o_followup", height=130)
        st.caption(f"Placeholders: {PLACEHOLDERS}")
        st.button("↺ Reset templates to default", on_click=_reset_templates)
        if not st.session_state["o_sender_name"].strip():
            st.warning("Add your name — messages currently say “[Your Name]”.")
    outreach_settings = {k: st.session_state[f"o_{k}"] for k in DEFAULT_SETTINGS}
    if outreach_settings != st.session_state["outreach"]:
        st.session_state["outreach"] = outreach_settings
        save_settings(outreach_settings)

    # --- Companies House CSV (advanced) ---
    with st.expander("⚙️ Advanced: Companies House CSV file"):
        ch_file = st.file_uploader(
            "Upload CSV (Officers CSV with director names)",
            type=["csv"],
            help="Optional. Looks up director names by company name. The free BasicCompanyData "
                 "file has no director names, so it won't fill the Director column.",
        )
        if ch_file is not None:
            sig = (ch_file.name, ch_file.size)
            if st.session_state["ch_sig"] != sig:
                with st.spinner("Indexing Companies House data…"):
                    try:
                        st.session_state["ch_db"] = CompaniesHouseDB(ch_file.getvalue())
                        st.session_state["ch_sig"] = sig
                    except Exception as e:
                        st.session_state["ch_db"], st.session_state["ch_sig"] = None, None
                        st.error(f"Failed to load CSV: {e}")
        else:
            st.session_state["ch_db"], st.session_state["ch_sig"] = None, None

        ch_db: CompaniesHouseDB | None = st.session_state["ch_db"]
        run_file = False
        if ch_file is not None:
            st.markdown("#### ⚡ Bulk Process All Companies")
            csv_limit = st.number_input(
                "Companies to process from file",
                min_value=50, max_value=50000, value=5000, step=500,
                help="Processes all companies from your uploaded file into full Needs-Website leads!",
            )
            run_file = st.button(f"🚀 Process File ({int(csv_limit):,} companies)", type="primary", width="stretch")

        if ch_db is not None:
            st.info(f"✅ {len(ch_db):,} companies loaded")
            if not ch_db.has_directors:
                st.caption("Note: Director lookup requires an Officers CSV with director names.")

    with st.expander("🔑 API keys status"):
        for label, env in (
            ("Geoapify", "GEOAPIFY_API_KEY"), ("Google Places", "GOOGLE_PLACES_API_KEY"),
            ("Companies House", "COMPANIES_HOUSE_API_KEY"), ("Gemini (AI)", "GEMINI_API_KEY"),
            ("Groq (AI)", "GROQ_API_KEY"), ("OpenRouter (AI)", "OPENROUTER_API_KEY"),
        ):
            st.write(("✅ " if _has_key(env) else "➖ ") + label)
        st.caption("Overture Maps needs no key. Keys live in the .env file — never share it.")

    with st.expander("ℹ️ Lead score formula"):
        for desc, weight in SCORE_WEIGHTS.items():
            st.write(f"• {desc}: **{weight} pts**")
        st.caption(
            "Total max = 100 pts. Without rating/review data (Geoapify) the score is "
            "website status + phone only, rescaled to 100. Closed businesses score 0."
        )


# ---------------------------------------------------------------------------
# Header slot (filled after the search ran) + search card
# ---------------------------------------------------------------------------

hero_slot = st.container()

keyword = ""
category = ""
sic_codes: tuple[str, ...] = ()
preset_labels: list[str] = []
months = 0
fetch_directors = False
city = ""
lat_val: float | None = None
lng_val: float | None = None
api_key = ""

with st.container(border=True, key="searchcard"):
    provider = st.radio(
        "Data source",
        [OVERTURE, GEOAPIFY, GOOGLE, COMPANIES_HOUSE],
        index=0,
        horizontal=True,
        format_func=SOURCE_SHORT.get,
        help="Overture Maps: free, no key, worldwide — often includes phone, email and Facebook page "
             "(searches take ~30 s). Geoapify: 3,000 free requests/day. Google: best data but paid after "
             "the free monthly quota. Companies House: new UK companies only.",
    )

    if provider == COMPANIES_HOUSE:
        country_name = "United Kingdom"
        r1 = st.columns(3)
        preset_labels = r1[0].multiselect("Business type", list(SIC_PRESETS), help="Matched on the company's SIC code.")
        extra_sic = r1[1].text_input("Extra SIC codes (optional)", placeholder="e.g. 96020, 43220")
        keyword = r1[2].text_input("Company name contains (optional)", placeholder="e.g. barber")
        r2 = st.columns([2, 2, 2, 1.3], vertical_alignment="bottom")
        city = r2[0].text_input(
            "Town or postcode (optional)", placeholder="e.g. Manchester, SW1A 1AA",
            help="Separate several places with ; (e.g. Leeds; Bradford). Matched against the company's registered office address.",
        )
        months = r2[1].slider("Registered in the last … months (0 = any age)", 0, 60, 12)
        fetch_directors = r2[2].checkbox(
            "Look up director names", value=False,
            help="One extra API request per company (~0.5 s each). Gives you a first name for the greeting.",
        )
        run_search = r2[3].button("🔍 Search", type="primary", width="stretch")
        sic_codes = sic_codes_for(preset_labels, extra_sic)
        api_key = _key_input(
            "Companies House API Key", "COMPANIES_HOUSE_API_KEY",
            help="Free: developer.company-information.service.gov.uk → Get started → create a 'Live' application → API key.",
            placeholder="e.g. 3f2a…",
        )
        st.caption("ℹ️ New companies are the best leads — most have no website yet. Phones come from the Google link.")
    else:
        r1 = st.columns(2)
        keyword = r1[0].text_input("Keyword", placeholder="e.g. plumbers, hair salon, accountants")
        if provider == OVERTURE:
            category = "|".join(r1[1].multiselect("Category (pick one or more)", list(OVERTURE_CATEGORIES)))
        elif provider == GEOAPIFY:
            category = r1[1].selectbox(
                "Category", options=[""] + list(GEOAPIFY_CATEGORIES.keys()),
                format_func=lambda x: x if x else "— select —",
            )
        else:
            category = r1[1].selectbox(
                "Category", options=[""] + CATEGORY_TYPES,
                format_func=lambda x: x.replace("_", " ").title() if x else "— select —",
            )
        r2 = st.columns([2, 3, 1.3], vertical_alignment="bottom")
        country_name = r2[0].selectbox(
            "Target country", list(COUNTRIES), index=list(COUNTRIES).index(DEFAULT_COUNTRY),
            help="Restricts the city lookup to this country (so 'Manchester' isn't found in the wrong "
                 "country) and sets the calling code used for WhatsApp links on local phone numbers.",
        )
        city = r2[1].text_input(
            "City or postcode", placeholder="e.g. Manchester, SW1A 1AA",
            help="Separate several places with ; (e.g. Leeds; Bradford). Max results applies to each place.",
        )
        run_search = r2[2].button("🔍 Search", type="primary", width="stretch")

        if provider == OVERTURE:
            api_key = "free"          # no key needed
            st.caption("✅ No API key needed · data: Overture Maps Foundation (Meta, Microsoft…) · leads without a real website come first.")
        elif provider == GEOAPIFY:
            api_key = _key_input(
                "Geoapify API Key", "GEOAPIFY_API_KEY",
                help="Free key from myprojects.geoapify.com", placeholder="e.g. b106...",
            )
            st.caption("ℹ️ OpenStreetMap data often lacks website tags — verify 'No Website' leads. No ratings/reviews.")
        else:
            api_key = _key_input(
                "Google Places API Key", "GOOGLE_PLACES_API_KEY",
                help="Required. Enable 'Places API (New)' (and optionally Geocoding API) in Google Cloud Console.",
                placeholder="AIza...",
            )

    country_iso, default_cc = COUNTRIES[country_name]

    with st.expander("⚙️ Search options — filters, radius, how many results"):
        o1, o2, o3 = st.columns(3)
        if provider == COMPANIES_HOUSE:
            location_mode = "City / Postcode name"
            radius_km = 10
        else:
            location_mode = o1.radio("Location type", ["City / Postcode name", "Lat / Lng + Radius"], index=0)
            if location_mode == "Lat / Lng + Radius":
                city = ""
                lat_val = o1.number_input("Latitude", value=51.5074, format="%.6f")
                lng_val = o1.number_input("Longitude", value=-0.1278, format="%.6f")
            radius_km = o1.slider("Radius (km)", 1, 50, 10)

        max_cap = {GOOGLE: MAX_PLACES_RESULTS, COMPANIES_HOUSE: MAX_COMPANIES, OVERTURE: MAX_OVERTURE_RESULTS}.get(provider, 5000)
        max_results = o2.number_input(
            "Max results to fetch (per place)",
            min_value=10, max_value=max_cap, value=min(100 if provider in (COMPANIES_HOUSE, OVERTURE) else 250, max_cap), step=50,
            help={
                GOOGLE: "Google Text Search returns at most 60 results per query.",
                COMPANIES_HOUSE: "Newest companies first. Max 500 per search.",
            }.get(provider, "Fetches up to 5,000 businesses across multiple pages."),
        )
        use_cache = o2.checkbox("Reuse results of identical searches (1 h)", value=True,
                                help="Saves API quota. Untick to force a fresh API call.")
        hide_closed = o3.checkbox("Hide permanently closed businesses", value=True)
        hide_contacted = o3.checkbox(
            "Hide leads I already contacted", value=True,
            help="Leads whose Contacted status is not 'Not contacted' are left out of new search results.",
        )
        only_new = o3.checkbox(
            "Only show leads never found before", value=False,
            help="Useful when repeating a search in the same area to find newly listed businesses.",
        )
        skip_chains = o3.checkbox(
            "Skip big chains / franchises", value=True,
            help="Drops well-known brands and any name that appears 3+ times in the same search "
                 "(Costa, McDonald's, Greggs…). They are not your clients.",
        )


# ---------------------------------------------------------------------------
# Search / Process logic
# ---------------------------------------------------------------------------

if load_saved:
    saved = _prepare_saved(lead_store.load_leads())
    st.session_state.update(
        df=saved, search_done=True, search_error="", search_label="",
        notes=[f"Showing all {len(saved):,} saved leads." if saved is not None else "No saved leads yet — run a search first."],
    )

elif run_file:
    if ch_file is None:
        st.error("⛔ Please upload a CSV file first.")
        st.stop()
    st.session_state.update(df=None, search_done=False, search_error="", notes=[])
    try:
        with st.spinner(f"Reading and converting companies from '{ch_file.name}'…"):
            raw = parse_uploaded_companies_file(ch_file.getvalue(), max_rows=int(csv_limit))
        if raw:
            with st.spinner(f"Enriching and scoring {len(raw):,} leads…"):
                enriched = _enrich(raw, st.session_state["ch_db"], default_cc, False, "CSV file")
                st.session_state["notes"] = [f"Processed {len(raw):,} companies directly from '{ch_file.name}'!"]
                st.session_state["df"] = _store_and_filter(enriched, ch_file.name, False, False)
        st.session_state["search_done"] = True
    except Exception as e:
        st.session_state["search_error"] = f"Failed to process CSV file: {e}"

elif run_search:
    problem = ""
    if not api_key:
        problem = f"Please enter your {provider.split()[0]} API key in the search box."
    elif provider == COMPANIES_HOUSE and not (sic_codes or keyword.strip() or city.strip()):
        problem = "Choose a business type, a company-name keyword, or a town/postcode."
    elif provider != COMPANIES_HOUSE and not keyword.strip() and not category:
        problem = "Please enter a keyword or choose a category."
    elif provider in (GEOAPIFY, OVERTURE) and location_mode == "City / Postcode name" and not city.strip():
        problem = f"{provider.split()[0]} needs a city or postcode (or switch to Lat / Lng)."
    if problem:
        st.error(f"⛔ {problem}")
        st.stop()

    st.session_state.update(df=None, search_done=False, search_error="", notes=[])

    if not use_cache:
        _run_search.clear()

    try:
        slow = " (looking up directors, this takes a while)" if fetch_directors else ""
        with st.spinner(f"Searching via {provider.split()[0]}{slow}…"):
            raw, notes = _run_search(
                provider, api_key, keyword.strip(), category, city.strip(),
                lat_val, lng_val, float(radius_km), int(max_results),
                sic_codes, int(months), bool(fetch_directors), country_iso, bool(skip_chains),
            )
        st.session_state["notes"] = notes
        st.session_state["search_label"] = (
            SIC_PRESETS[preset_labels[0]][1] if preset_labels
            else (keyword.strip() or category.split("|")[0])
        )
        if raw:
            with st.spinner(f"Enriching {len(raw)} results…"):
                enriched = _enrich(
                    raw, st.session_state["ch_db"], default_cc, hide_closed, SOURCE_LABELS[provider], skip_chains
                )
                st.session_state["df"] = _store_and_filter(
                    enriched, st.session_state["search_label"], hide_contacted, only_new
                )
        st.session_state["search_done"] = True
    except RuntimeError as e:
        st.session_state["search_error"] = str(e)


# ---------------------------------------------------------------------------
# Status messages
# ---------------------------------------------------------------------------

cache: dict = st.session_state["cache"]
df: pd.DataFrame | None = st.session_state["df"]
if df is not None:
    df = apply_cache_to_df(df, cache)   # layer saved edits (Manual Email / Contacted) on top
    df = add_outreach(df, outreach_settings, st.session_state["search_label"], default_cc)

_in_view = 0 if df is None else len(df)
_need = 0 if df is None else int(df["Website Status"].isin(NEEDS_STATUSES).sum())
_due = len(_followup_df(int(st.session_state.get("followup_days", 4))))
_won = sum(1 for e in cache.values() if e.get("Contacted") == "Won")
with hero_slot:
    st.markdown(
        f"""
<div class="ds-top">
  <div class="ds-title">
    <h1>Find businesses that need a website</h1>
    <p>Search a niche and a city, pick a lead, message them at the right time.</p>
  </div>
  <div class="ds-kpis">
    <div class="ds-kpi"><b>{_in_view:,}</b><span>In view</span></div>
    <div class="ds-kpi"><b>{_need:,}</b><span>Need website</span></div>
    <div class="ds-kpi"><b>{lead_store.count():,}</b><span>Saved</span></div>
    <div class="ds-kpi"><b>{_due:,}</b><span>Follow-ups</span></div>
    <div class="ds-kpi"><b>{_won:,}</b><span>Won</span></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

if st.session_state["search_error"]:
    st.error(f"🚨 {st.session_state['search_error']}")

for note in st.session_state["notes"]:
    st.info(f"ℹ️ {note}")

if st.session_state["search_done"]:
    if df is not None and not df.empty:
        if not (st.session_state["notes"] and st.session_state["notes"][0].startswith("Showing all")):
            st.success(f"✅ Search complete! Found **{len(df)}** businesses.")
    elif not st.session_state["search_error"]:
        st.warning(
            "⚠️ 0 businesses found for this search. Try increasing the radius (e.g. 15–25 km) "
            "or choosing a different Category / City."
        )

tab_needs, tab_all, tab_follow, tab_clients, tab_downloads = st.tabs(
    ["🎯 Leads to contact", "📊 All results", "📅 Follow-ups & stats", "💼 Clients", "⬇️ Downloads"]
)
ver = st.session_state["edit_ver"]


# ============================================================
# TAB 1 — ALL RESULTS
# ============================================================

with tab_all:
    if df is None or df.empty:
        if st.session_state["search_done"]:
            st.warning("⚠️ No records to display. Try a wider radius or a different location.")
        else:
            _empty_state("No results yet", "Run a search above to see every business found.")
    else:
        st.subheader(f"All Results — {len(df)} businesses found")

        display_cols = [
            "Name", "Address", "Phone", "Phone Type", "Local Time", "Call Window", "Website Status", "Social Link", "Rating", "Reviews",
            "Lead Score", "Best Channel", "Google Maps", "Business Status", "Source", "First Seen", "Manual Email", "Contacted",
        ]
        display_cols = [c for c in display_cols if c in df.columns]

        st.data_editor(
            df[display_cols],
            column_config={
                "Name": st.column_config.TextColumn("Name", width="medium"),
                "Address": st.column_config.TextColumn("Address", width="large"),
                "Website Status": st.column_config.TextColumn("Website Status", width="small"),
                "Social Link": st.column_config.LinkColumn("Social Link", width="medium"),
                "Google Maps": st.column_config.LinkColumn("Google Maps", display_text="📍 Open map", width="small"),
                "Rating": st.column_config.NumberColumn("⭐ Rating", format="%.1f"),
                "Reviews": st.column_config.NumberColumn("Reviews"),
                "Lead Score": st.column_config.ProgressColumn("Lead Score", min_value=0, max_value=100, format="%d"),
                "Manual Email": st.column_config.TextColumn("Manual Email", width="medium"),
                "Contacted": st.column_config.SelectboxColumn("Contacted", options=CONTACTED_OPTIONS, width="medium"),
            },
            disabled=[c for c in display_cols if c not in EDITABLE_DEFAULTS],
            width="stretch",
            num_rows="fixed",
            hide_index=True,
            key=f"editor_all_{ver}",
            on_change=_on_edit,
            args=(f"editor_all_{ver}", "all"),
        )

        counts = df["Website Status"].value_counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("🚫 No Website", int(counts.get("NO WEBSITE", 0)))
        c2.metric("📱 Social Only", int(counts.get("SOCIAL ONLY", 0)))
        c3.metric("✅ Has Website", int(counts.get("HAS WEBSITE", 0)))


# ============================================================
# TAB 2 — NEEDS WEBSITE
# ============================================================

with tab_needs:
    if df is None or df.empty:
        _empty_state("No leads yet", "Run a search above, or open your saved leads from the sidebar.")
    else:
        needs_df = _needs_view(df)
        if needs_df.empty:
            st.success("All businesses in this search have a real website!")
        else:
            preview_max = 250
            shown = needs_df.head(preview_max)
            pids = shown["place_id"].tolist()
            callable_now = int(shown["Call Window"].str.startswith("✅").sum())
            n_wa = int((shown["WhatsApp Link"] != "").sum())
            n_mail = int((shown["Manual Email"].str.strip() != "").sum())

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("🎯 Leads to contact", f"{len(needs_df):,}")
            k2.metric("📞 Good time to call now", f"{callable_now:,}",
                      help="Business hours right now where the lead is (✅ in the Local time column).")
            k3.metric("💬 Can use WhatsApp", f"{n_wa:,}", help="Mobile / international numbers only — landlines can't use WhatsApp.")
            k4.metric("✉️ With an email", f"{n_mail:,}")
            if len(needs_df) > preview_max:
                st.info(f"Showing the best {preview_max} of {len(needs_df):,} leads (sorted by score). "
                        "All of them are in the CSV on the Downloads tab.")

            st.markdown("#### 1 · Pick a lead")
            st.caption("Click a row. Sorted by lead score · ✅ good time to call · 💤 outside business hours there.")
            table = pd.DataFrame({
                "Name": shown["Name"], "Town": shown["Town"], "Score": shown["Lead Score"],
                "Website": shown["Website Status"].str.title(),
                "Phone": shown["Phone"], "Type": shown["Phone Type"],
                "Local time": (shown["Local Time"] + " " + shown["Call Window"].str[:1]).str.strip(),
                "Status": shown["Contacted"],
            })
            sel = st.dataframe(
                table, hide_index=True, width="stretch", height=min(35 * len(table) + 40, 340),
                on_select="rerun", selection_mode="single-row", key="needs_table",
                column_config={
                    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                    "Name": st.column_config.TextColumn("Name", width="medium"),
                },
            )
            picked = list(sel.selection.rows) if sel is not None and sel.selection else []
            if picked and picked != st.session_state.get("last_sel_rows") and picked[0] < len(pids):
                st.session_state["focus_pid"] = pids[picked[0]]
            st.session_state["last_sel_rows"] = picked
            if st.session_state.get("focus_pid") not in pids:
                st.session_state["focus_pid"] = pids[0]
            pos = pids.index(st.session_state["focus_pid"])
            row = shown.iloc[pos]
            pid = row["place_id"]

            st.markdown("#### 2 · Contact them")
            with st.container(border=True, key="leadcard"):
                hl, hr_ = st.columns([5, 2], vertical_alignment="center")
                badges = [
                    _badge(row["Website Status"].title(), "red" if row["Website Status"] == "NO WEBSITE" else "amber"),
                    _badge(f"Score {row['Lead Score']}", "green" if row["Lead Score"] >= 70 else ""),
                ]
                if row["Phone Type"]:
                    badges.append(_badge(row["Phone Type"].title(), "gray"))
                if row["Local Time"]:
                    badges.append(_badge(f"{row['Local Time']} {row['Call Window']}".strip(), "green" if row["Call Window"].startswith("✅") else "gray"))
                hl.markdown(
                    f'<div class="ds-lead"><h2>{html.escape(row["Name"])}</h2>'
                    f'<p>{html.escape(row["Address"] or row["Town"])}</p>{"".join(badges)}</div>',
                    unsafe_allow_html=True,
                )
                with hr_:
                    nv1, nv2 = st.columns(2)
                    nv1.button("◀ Prev", key="nav_prev", width="stretch", disabled=pos == 0,
                               on_click=_step_focus, args=(pids, -1))
                    nv2.button("Next ▶", key="nav_next", width="stretch", disabled=pos == len(pids) - 1,
                               on_click=_step_focus, args=(pids, 1))
                    st.caption(f"Lead {pos + 1} of {len(pids)}")

                phone_digits = re.sub(r"[^\d+]", "", row["Phone"])
                actions = [
                    ("💬 WhatsApp", row["WhatsApp Link"]),
                    ("📞 Call", f"tel:{phone_digits}" if phone_digits else ""),
                    ("✉️ Email", row["Mail Link"]),
                    ("📍 Map", row["Google Maps"]),
                    ("🔍 Google", row["Google Search"]),
                    ("📘 Facebook", row["Facebook Search"]),
                ]
                actions = [a for a in actions if a[1]]
                for col, (label, url) in zip(st.columns(len(actions)), actions):
                    col.link_button(label, url, width="stretch")
                st.caption(
                    f"Best channel: **{row['Best Channel']}**. Open the Map and Google links first to confirm "
                    "they really have no website."
                )

                s1, s2 = st.columns(2)
                skey, ekey = f"stat_{pid}_{ver}", f"mail_{pid}_{ver}"
                cur = row["Contacted"] if row["Contacted"] in CONTACTED_OPTIONS else CONTACTED_OPTIONS[0]
                s1.selectbox("Status — update after you contact them", CONTACTED_OPTIONS,
                             index=CONTACTED_OPTIONS.index(cur), key=skey,
                             on_change=_set_lead_field, args=(pid, "Contacted", skey))
                s2.text_input("Email (add one if you find it — the Email button appears)", value=row["Manual Email"],
                              key=ekey, placeholder="name@business.com",
                              on_change=_set_lead_field, args=(pid, "Manual Email", ekey))

                sender, contact = outreach_settings["sender_name"], outreach_settings["sender_phone"]
                t_msg, t_site, t_prompt, t_info = st.tabs(
                    ["💬 Messages", "🎨 Sample website", "🧠 Prompts for ChatGPT / Claude", "📇 Details"]
                )

                with t_msg:
                    pc1, pc2 = st.columns(2)
                    with pc1:
                        st.markdown("**✉️ Email**")
                        st.code(row["Email Subject"], language=None, wrap_lines=True)
                        st.code(row["Email Body"], language=None, wrap_lines=True)
                    with pc2:
                        st.markdown("**💬 WhatsApp / message**")
                        st.code(row["WhatsApp Message"], language=None, wrap_lines=True)
                        st.caption("Use the copy icon on each box. Edit the wording in the sidebar → Your details & message templates.")

                with t_site:
                    st.markdown("##### ⚡ Instant template (always works, no key)")
                    st.caption(
                        "A one-page sample built from this lead's real name, town, address and phone. "
                        "Services and opening hours are marked as examples."
                    )
                    mock_html = render_mockup(row.to_dict(), sender, contact)
                    mk1, mk2 = st.columns(2)
                    mk1.download_button(
                        "📥 Download this mockup (.html)", mock_html.encode("utf-8"),
                        file_name=f"{slug(row['Name'])}.html", mime="text/html", width="stretch",
                    )
                    zip_sig = (len(needs_df), needs_df["place_id"].iloc[0], needs_df["place_id"].iloc[-1], sender, contact)
                    if mk2.button(f"📦 Prepare ZIP of all {len(needs_df):,} mockups", width="stretch"):
                        with st.spinner("Building mockups…"):
                            st.session_state["mock_zip"] = (zip_sig, build_zip(needs_df, sender, contact))
                    ready = st.session_state.get("mock_zip")
                    if ready and ready[0] == zip_sig:
                        mk2.download_button(
                            f"⬇️ Download mockups.zip ({len(ready[1]) / 1024:,.0f} KB)", ready[1],
                            file_name="mockups.zip", mime="application/zip", width="stretch",
                        )
                    with st.expander("👁️ Preview template"):
                        _show_html(mock_html)

                    st.divider()
                    st.markdown("##### 🤖 AI-designed page (free API)")
                    st.caption(
                        "Writes a custom page with Groq / Gemini / OpenRouter. It only gets the real facts and must not "
                        "invent reviews, prices or hours — still read the warnings. For a more polished result use the "
                        "**Prompts** tab and let ChatGPT / Claude build it."
                    )
                    ai1, ai2 = st.columns(2)
                    _ai_names = list(AI_PROVIDERS)
                    _ai_default = next((i for i, n in enumerate(_ai_names) if _has_key(AI_PROVIDERS[n]["env"])), 0)
                    ai_provider = ai1.selectbox("AI provider", _ai_names, index=_ai_default, key="ai_provider")
                    ai_cfg = AI_PROVIDERS[ai_provider]
                    ai_model = ai2.text_input("Model", value=ai_cfg["model"], key=f"ai_model_{ai_provider}",
                                              help="Change this if the provider renamed or retired the model.")
                    ai_key = os.getenv(ai_cfg["env"], "") if _has_key(ai_cfg["env"]) else ""
                    if not ai_key:
                        ai_key = st.text_input(
                            f"{ai_provider} API key", type="password", key=f"ai_key_{ai_provider}",
                            help=f"Free key: {ai_cfg['signup']}  ·  or add {ai_cfg['env']}=… to your .env file.",
                        )
                    ai3, ai4 = st.columns(2)
                    ai_style = ai3.selectbox("Style", list(AI_STYLES), key="ai_style")
                    ai_extra = ai4.text_input("Extra wishes (optional)", key="ai_extra",
                                              placeholder="e.g. add a booking section, use green colours")
                    if st.button("✨ Generate website with AI", key="ai_go", type="primary"):
                        with st.spinner("The AI is designing the page… (10–60 seconds)"):
                            try:
                                page, warns = generate_site(
                                    row.to_dict(), provider=ai_provider, api_key=ai_key, model=ai_model,
                                    style=ai_style, extra=ai_extra, sender_name=sender,
                                )
                                st.session_state["ai_sites"][pid] = (page, warns, ai_provider)
                            except AIError as e:
                                st.error(str(e))
                    made = st.session_state["ai_sites"].get(pid)
                    if made:
                        ai_html, ai_warns, ai_by = made
                        st.success(f"AI page for **{row['Name']}** is ready (made with {ai_by}).")
                        for w in ai_warns:
                            st.warning(w)
                        st.download_button(
                            "📥 Download AI website (.html)", ai_html.encode("utf-8"),
                            file_name=f"{slug(row['Name'])}-ai.html", mime="text/html", width="stretch",
                        )
                        with st.expander("👁️ Preview AI website", expanded=True):
                            _show_html(ai_html, height=720)

                with t_prompt:
                    st.markdown("##### 🎨 Professional website prompt")
                    st.caption(
                        "Copy this into **ChatGPT, Claude or Gemini** (a paid / strong model gives the best result). "
                        "It already contains this lead's real facts, a premium design brief and the honesty rules."
                    )
                    pr1, pr2 = st.columns(2)
                    pr_style = pr1.selectbox("Design style", list(AI_STYLES), key="pr_style")
                    pr_extra = pr2.text_input("Extra wishes (optional)", key="pr_extra",
                                              placeholder="e.g. add a booking section, green colours")
                    site_prompt = website_prompt(row.to_dict(), sender, pr_style, pr_extra)
                    st.code(site_prompt, language=None, wrap_lines=True)
                    st.download_button(
                        "📥 Download prompt (.txt)", site_prompt.encode("utf-8"),
                        file_name=f"{slug(row['Name'])}-website-prompt.txt", mime="text/plain",
                    )
                    st.markdown(
                        "**How to get a great result**\n"
                        "1. Paste the prompt, send it, then save the code block as `index.html` and open it in your browser.\n"
                        "2. Ask for changes one at a time: *“make the hero bolder”*, *“use a darker palette”*, *“add a gallery section”*.\n"
                        "3. Add the owner's real photos where it says `[PHOTO: …]` once they reply.\n"
                        "4. Send a screenshot (not the file) in your first message — the file only after they answer."
                    )
                    st.divider()
                    st.markdown("##### ✉️ Email prompt (ChatGPT writes the email)")
                    st.code(chatgpt_prompt(row.to_dict(), outreach_settings), language=None, wrap_lines=True)

                with t_info:
                    facts = [
                        ("Address", row["Address"]), ("Town", row["Town"]), ("Phone", row["Phone"]),
                        ("International phone", row["Intl Phone"]), ("Website status", row["Website Status"].title()),
                        ("Social page", row["Social Link"]), ("Director", row["Director Name"]),
                        ("Company number", str(row.get("Company Number", "") or "")),
                        ("Incorporated", str(row.get("Incorporated", "") or "")),
                        ("Source", row.get("Source", "")), ("First seen", str(row.get("First Seen", "") or "")),
                    ]
                    if pd.notna(row.get("Rating")):
                        facts.insert(5, ("Rating", f"{row['Rating']:.1f} ({int(row['Reviews']) if pd.notna(row.get('Reviews')) else 0} reviews)"))
                    cells = "".join(
                        f"<div>{html.escape(k)}</div><div>{html.escape(str(v))}</div>"
                        for k, v in facts if str(v or "").strip() and str(v) != "nan"
                    )
                    st.markdown(f'<div class="ds-kv">{cells}</div>', unsafe_allow_html=True)

            with st.expander(f"📝 Edit statuses & emails in a table ({len(shown):,} leads)"):
                edit_cols = [
                    "Name", "Town", "Website Status", "Lead Score",
                    "Phone", "Phone Type", "Best Channel", "Director Name", "Manual Email", "Contacted",
                ]
                edit_cols = [c for c in edit_cols if c in shown.columns]
                st.data_editor(
                    shown[edit_cols],
                    column_config={
                        "Name": st.column_config.TextColumn("Name", width="medium"),
                        "Town": st.column_config.TextColumn("Town"),
                        "Website Status": st.column_config.TextColumn("Status"),
                        "Lead Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                        "Phone": st.column_config.TextColumn("Phone"),
                        "Phone Type": st.column_config.TextColumn("Type"),
                        "Best Channel": st.column_config.TextColumn("Best channel"),
                        "Director Name": st.column_config.TextColumn("Director"),
                        "Manual Email": st.column_config.TextColumn("Manual Email", width="medium"),
                        "Contacted": st.column_config.SelectboxColumn("Contacted", options=CONTACTED_OPTIONS, width="medium"),
                    },
                    disabled=[c for c in edit_cols if c not in EDITABLE_DEFAULTS],
                    width="stretch",
                    num_rows="fixed",
                    hide_index=True,
                    key=f"editor_needs_{ver}",
                    on_change=_on_edit,
                    args=(f"editor_needs_{ver}", "needs"),
                )


# ============================================================
# TAB 3 — FOLLOW-UPS & STATS (works on ALL saved leads, not just the current search)
# ============================================================

with tab_follow:
    counts = status_counts(cache)
    contacted_total = sum(counts.values())
    rate = reply_rate(counts)

    st.subheader("📈 Outreach stats")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Leads saved", f"{lead_store.count():,}")
    m2.metric("Contacted", contacted_total)
    m3.metric("Replied", counts.get("Replied", 0))
    m4.metric("Won (clients)", counts.get("Won", 0))
    m5.metric("Reply rate", f"{rate:.0%}" if rate is not None else "–",
              help="(Replied + Won) ÷ everyone you contacted")

    if contacted_total:
        ch1, ch2 = st.columns(2)
        with ch1:
            st.caption("Leads by status")
            st.bar_chart(pd.Series(counts, name="Leads"), horizontal=True)
        with ch2:
            st.caption("Status changes in the last 14 days")
            st.bar_chart(contacts_per_day(cache))
    else:
        st.info("Set a lead's **Contacted** status (Called / Messaged…) to start tracking your outreach.")

    st.divider()
    st.subheader("📅 Follow-ups due")
    fu_days = st.number_input(
        "Follow up leads who haven't answered after (days)", min_value=1, max_value=30, value=4,
        key="followup_days",
        help="Lists leads marked Called or Messaged that long ago. After you follow up, mark them "
             "'Followed up' (once is enough), or 'Replied' / 'Not interested' / 'Won'.",
    )
    due = add_outreach(_followup_df(int(fu_days)), outreach_settings, "", default_cc)
    if due.empty:
        st.success("🎉 No follow-ups due right now.")
    else:
        st.caption(f"**{len(due):,}** leads are waiting for a reply. WhatsApp / Email open with the follow-up already written.")
        due_view = due.head(250)
        rows = []
        for r in due_view.to_dict("records"):
            days_since = r["Days Since"]
            rows.append(
                "<tr>"
                f"<td>{html.escape(r['Name'])}</td>"
                f"<td>{html.escape(r['Town'])}</td>"
                f"<td>{html.escape(r['Contacted'])}</td>"
                f"<td>{'unknown' if pd.isna(days_since) else f'{int(days_since)} days ago'}</td>"
                f"<td>{html.escape(r['Phone'])}</td>"
                f"<td>{html.escape(r['Phone Type'])}</td>"
                f"<td style='white-space:nowrap' title='{html.escape(r['Call Window'], quote=True)}'>"
                f"{html.escape(r['Local Time'])} {html.escape(r['Call Window'][:1])}</td>"
                f"<td>{_link(r['Follow-up WhatsApp Link'], 'WhatsApp')}</td>"
                f"<td>{_link(r['Follow-up Mail Link'], 'Email ✉️', False)}</td>"
                f"<td>{_link(r['Google Maps'], '📍 Map')}</td>"
                f"<td>{_link(r['Facebook Search'], 'Facebook 🔍')}</td>"
                "</tr>"
            )
        st.html(
            LEADS_TABLE_CSS
            + '<table class="leads-table"><thead><tr><th>Name</th><th>Town</th><th>Status</th>'
              "<th>Contacted</th><th>Phone</th><th>Type</th><th>Local time</th><th>WhatsApp</th><th>Email</th>"
              "<th>Map</th><th>Facebook</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )

        pick_fu = st.selectbox(
            "Preview follow-up for", options=range(len(due_view)),
            format_func=lambda i: due_view.iloc[i]["Name"], key="followup_pick",
        )
        st.code(due_view.iloc[pick_fu]["Follow-up Message"], language=None, wrap_lines=True)

        st.markdown("### ✏️ Update status")
        fu_cols = ["Name", "Contacted", "Contacted On", "Manual Email"]
        st.data_editor(
            due_view[fu_cols],
            column_config={
                "Contacted": st.column_config.SelectboxColumn("Status", options=CONTACTED_OPTIONS, width="medium"),
                "Contacted On": st.column_config.TextColumn("Last change"),
                "Manual Email": st.column_config.TextColumn("Manual Email", width="medium"),
            },
            disabled=["Name", "Contacted On"],
            width="stretch",
            num_rows="fixed",
            hide_index=True,
            key=f"editor_follow_{ver}",
            on_change=_on_edit,
            args=(f"editor_follow_{ver}", "followups"),
        )


# ============================================================
# TAB 4 — CLIENTS (leads marked Won)
# ============================================================

with tab_clients:
    clients_df = _clients_view()
    st.subheader("💼 Won clients")
    if clients_df.empty:
        st.info(
            "When a lead says yes, set its **Contacted** status to **Won** (any table or the Follow-ups tab). "
            "It appears here so you can track price, payments and deadline."
        )
    else:
        totals = (
            clients_df.groupby("Currency")
            .agg(Projects=("place_id", "count"), Total=("Price", "sum"), Received=("Paid", "sum"),
                 Outstanding=("Outstanding", "sum"))
            .reset_index()
        )
        st.dataframe(totals, hide_index=True, width="stretch")
        st.caption("Tip: take 50% before you start and 50% before the site goes live. Domain and hosting stay in the client's name.")
        st.data_editor(
            clients_df[["Name", "Town", "Package", "Price", "Currency", "Paid", "Outstanding", "Deadline", "Notes"]],
            column_config={
                "Package": st.column_config.TextColumn("Package", help="e.g. Basic / Standard / Plus"),
                "Price": st.column_config.NumberColumn("Price", min_value=0.0, step=50.0, format="%.0f"),
                "Currency": st.column_config.SelectboxColumn("Currency", options=client_store.CURRENCIES),
                "Paid": st.column_config.NumberColumn("Paid so far", min_value=0.0, step=50.0, format="%.0f"),
                "Outstanding": st.column_config.NumberColumn("Outstanding", format="%.0f"),
                "Deadline": st.column_config.TextColumn("Deadline", help="e.g. 2026-11-15"),
                "Notes": st.column_config.TextColumn("Notes", width="large"),
            },
            disabled=["Name", "Town", "Outstanding"],
            width="stretch",
            num_rows="fixed",
            hide_index=True,
            key=f"editor_clients_{ver}",
            on_change=_on_client_edit,
            args=(f"editor_clients_{ver}",),
        )


# ============================================================
# TAB 5 — DOWNLOADS
# ============================================================

with tab_downloads:
    if df is None or df.empty:
        st.info("Run a search first to enable downloads.")
    else:
        st.subheader("⬇️ Export Data")

        st.markdown("#### All Results")
        st.download_button(
            f"📥 Download All_Results.csv ({len(df):,} rows)",
            data=_csv(df.drop(columns=["place_id", "WhatsApp Digits", "Mail Link"], errors="ignore")),
            file_name="All_Results.csv",
            mime="text/csv",
            width="stretch",
        )
        st.caption(f"{len(df):,} rows · All businesses from search/file")

        st.divider()

        st.markdown("#### Needs Website Leads")
        needs_dl = _needs_view(df)
        has_phone_count = (needs_dl["Phone"].str.strip().ne("")).sum()
        filter_phone = st.checkbox(
            f"Only include leads that have a phone number ({has_phone_count:,} available)",
            value=bool(has_phone_count > 0),
            help="Uncheck if your uploaded file doesn't have phone numbers yet, so all 5,000 leads are exported!",
        )
        if filter_phone:
            needs_dl = needs_dl[needs_dl["Phone"].str.strip().ne("")]

        csv_cols = [
            "Name", "Address", "Town", "Phone", "Phone Type", "Best Channel", "Intl Phone",
            "Website Status", "Social Link", "Rating", "Reviews", "Lead Score", "Director Name",
            "Company Number", "Incorporated", "Manual Email", "Email Subject", "Email Body",
            "WhatsApp Message", "WhatsApp Link", "Google Maps", "Google Search", "Facebook Search",
            "LinkedIn Search", "Contacted", "Source", "First Seen",
        ]
        st.download_button(
            f"📥 Download Needs_Website_Leads.csv ({len(needs_dl):,} leads)",
            data=_csv(needs_dl[[c for c in csv_cols if c in needs_dl.columns]]),
            file_name="Needs_Website_Leads.csv",
            mime="text/csv",
            width="stretch",
        )
        st.caption(f"{len(needs_dl):,} rows · No Website / Social Only · sorted by Lead Score")
        if needs_dl.empty:
            st.info("No 'Needs Website' leads found matching filter.")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    f"Data Scalper · Data via {SOURCE_LABELS[provider]} · "
    "No scraping — all search links are pre-generated URLs only."
)
