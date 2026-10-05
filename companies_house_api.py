"""
companies_house_api.py
----------------------
Finds UK companies through the official (free) Companies House REST API:
  * Advanced company search  — filter by SIC code, location, name, incorporation date
  * Officers endpoint        — first active director of each company

Free API key (600 requests / 5 min): https://developer.company-information.service.gov.uk/get-started
Docs: https://developer-specs.company-information.service.gov.uk/

Companies House has NO phone numbers or websites, so every lead returned here
still has to be checked (the 'Google Search' link is provided for that).
"""

from __future__ import annotations

import re
import string
import time
from datetime import date, timedelta
from typing import Any

import requests

BASE_URL = "https://api.company-information.service.gov.uk"
MAX_COMPANIES = 500
OFFICER_DELAY = 0.55        # seconds between officer calls → stays under 600 req / 5 min

# label -> (SIC codes, plural noun used in outreach messages)
SIC_PRESETS: dict[str, tuple[tuple[str, ...], str]] = {
    "Hair & beauty (barbers, salons)": (("96020",), "hair and beauty salons"),
    "Plumbing & heating": (("43220",), "plumbers"),
    "Electricians": (("43210",), "electricians"),
    "Roofing": (("43910",), "roofers"),
    "Builders & construction": (("41202", "43999"), "builders"),
    "Joinery & carpentry": (("43320",), "joiners"),
    "Painting & decorating": (("43341",), "decorators"),
    "Landscaping & gardening": (("81300",), "landscapers"),
    "Cleaning services": (("81210", "81299"), "cleaning companies"),
    "Restaurants & cafes": (("56101", "56102"), "restaurants and cafes"),
    "Takeaways": (("56103",), "takeaways"),
    "Pubs & bars": (("56302",), "pubs and bars"),
    "Car repair & garages": (("45200",), "garages"),
    "Taxi & private hire": (("49320",), "taxi firms"),
    "Driving schools": (("85530",), "driving schools"),
    "Gyms & fitness": (("93130",), "gyms"),
    "Dentists": (("86230",), "dental practices"),
    "Accountants & bookkeepers": (("69201", "69202"), "accountants"),
    "Solicitors": (("69102",), "solicitors"),
    "Estate agents": (("68310",), "estate agents"),
    "Florists": (("47760",), "florists"),
    "Photographers": (("74201",), "photographers"),
    "Pet grooming & other personal services": (("96090",), "pet and personal services"),
}

_SIC_NOUN = {code: noun for codes, noun in SIC_PRESETS.values() for code in codes}
_LEGAL_FORMS = {"Ltd": "Ltd", "Llp": "LLP", "Plc": "PLC", "Cic": "CIC", "Uk": "UK"}


def sic_codes_for(labels: list[str] | tuple[str, ...], extra: str = "") -> tuple[str, ...]:
    """Combine preset labels and free-typed codes ("96020, 43220") into unique 5-digit codes."""
    codes: list[str] = []
    for label in labels:
        codes.extend(SIC_PRESETS[label][0])
    codes.extend(re.findall(r"\b\d{5}\b", extra or ""))
    return tuple(dict.fromkeys(codes))


def _nice_company_name(name: str) -> str:
    words = string.capwords(name.lower()).split()
    return " ".join(_LEGAL_FORMS.get(w, w) for w in words)


def _nice_officer_name(raw: str) -> str:
    """'SMITH, John Michael' -> 'John Smith'; corporate names are title-cased."""
    if "," not in raw:
        return string.capwords(raw.lower())
    surname, forenames = (p.strip() for p in raw.split(",", 1))
    first = forenames.split()[0] if forenames else ""
    return f"{string.capwords(first.lower())} {string.capwords(surname.lower())}".strip()


class _ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Companies House API error {status}: {message}")
        self.status = status


class _Client:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.auth = (api_key, "")          # key as username, blank password

    def get(self, path: str, params: Any = None, *, retries: int = 2) -> dict[str, Any] | None:
        """GET → JSON. Returns None on 404. Raises RuntimeError on auth/other failures."""
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(BASE_URL + path, params=params, timeout=30)
            except requests.RequestException as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Companies House network error: {e}") from e
            if resp.status_code == 404:
                return None
            if resp.status_code in (401, 403):
                raise RuntimeError("Companies House rejected the API key (401/403). Check the key.")
            if resp.status_code == 429:
                if attempt < retries:
                    time.sleep(15)
                    continue
                raise RuntimeError("Companies House rate limit reached (600 requests / 5 min). Wait a few minutes.")
            if resp.status_code >= 400:
                raise _ApiError(resp.status_code, resp.text[:200])
            return resp.json()
        return None


def _address(addr: dict[str, Any]) -> str:
    keys = ("address_line_1", "address_line_2", "locality", "region", "postal_code")
    return ", ".join(str(addr[k]).strip() for k in keys if addr.get(k))


def _first_director(client: _Client, number: str) -> str:
    data = client.get(f"/company/{number}/officers", {"items_per_page": 35})
    for officer in (data or {}).get("items", []):
        if officer.get("officer_role") == "director" and not officer.get("resigned_on"):
            return _nice_officer_name(officer.get("name", ""))
    return ""


def search_companies(
    api_key: str,
    *,
    sic_codes: tuple[str, ...] = (),
    location: str = "",
    name_includes: str = "",
    months: int = 0,
    max_results: int = 100,
    fetch_directors: bool = False,
    notes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Active UK companies matching the filters, newest first, as lead dicts.

    months > 0 keeps only companies incorporated in the last `months` months —
    brand-new businesses are the likeliest to still need a website.
    """
    if not api_key:
        raise RuntimeError("Please enter your Companies House API key.")
    if not (sic_codes or location.strip() or name_includes.strip()):
        raise RuntimeError("Choose a business type (SIC code), a location, or a company-name keyword.")

    max_results = min(max_results, MAX_COMPANIES)
    client = _Client(api_key)
    fetch_size = min(5000, max(1000, max_results * 5))  # one request; newest are picked client-side

    params: dict[str, Any] = {
        "company_status": "active",
        "size": fetch_size,
        "start_index": 0,
    }
    if location.strip():
        params["location"] = location.strip()
    if name_includes.strip():
        params["company_name_includes"] = name_includes.strip()
    if months > 0:
        params["incorporated_from"] = (date.today() - timedelta(days=30 * months)).isoformat()

    data = None
    if sic_codes:
        try:   # documented as a list: try comma-separated first, then repeated parameters
            data = client.get("/advanced-search/companies", {**params, "sic_codes": ",".join(sic_codes)})
        except _ApiError as e:
            if e.status != 400:
                raise
            data = client.get("/advanced-search/companies", {**params, "sic_codes": list(sic_codes)})
    else:
        data = client.get("/advanced-search/companies", params)

    items = (data or {}).get("items", [])
    if not items:
        return []

    total = (data or {}).get("hits", len(items))
    if notes is not None and total and total > len(items):
        notes.append(f"{total:,} companies match; showing the newest {min(max_results, len(items))} of the first {len(items):,} returned.")

    items.sort(key=lambda it: it.get("date_of_creation") or "", reverse=True)

    leads: list[dict[str, Any]] = []
    for it in items[:max_results]:
        number = str(it.get("company_number", "")).strip()
        name = _nice_company_name(it.get("company_name", "").strip())
        if not number or not name:
            continue
        addr = it.get("registered_office_address") or {}
        sics = [str(c) for c in it.get("sic_codes", [])]
        noun = next((_SIC_NOUN[c] for c in sics if c in _SIC_NOUN), "")
        q = f'"{name}" {addr.get("locality", "")}'.strip()
        leads.append(
            {
                "place_id": f"ch_{number}",
                "Name": name,
                "Address": _address(addr),
                "Town": addr.get("locality") or addr.get("region") or location.strip(),
                "Phone": "",
                "Intl Phone": "",
                "Email": "",
                "Website": "",
                "Rating": None,
                "Reviews": None,
                "Business Status": "OPERATIONAL",
                "Types": noun or ", ".join(sics),
                "Director Name": "",
                "Company Number": number,
                "Incorporated": it.get("date_of_creation", ""),
                "Google Search": "https://www.google.com/search?q=" + requests.utils.quote(q),
            }
        )

    if fetch_directors and leads:
        for i, lead in enumerate(leads):
            try:
                lead["Director Name"] = _first_director(client, lead["Company Number"])
            except RuntimeError as e:      # rate limit / network: keep what we have
                if notes is not None:
                    notes.append(f"Stopped looking up directors after {i} companies — {e}")
                break
            time.sleep(OFFICER_DELAY)

    if notes is not None:
        notes.append(
            "Companies House has no phone numbers or websites — open the Google link to find "
            "a phone number and confirm the business really has no website."
        )
    return leads
