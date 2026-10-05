"""
companies_house.py
------------------
Loads a Companies House bulk data CSV and provides fuzzy-matching
of company names to director/officer names.

Companies House bulk data: https://download.companieshouse.gov.uk/en_output.html

NOTE: the free BasicCompanyData file has NO officer names. Director lookup only
works with a CSV that also contains an officer/director column
(`has_directors` tells you which kind was loaded).
"""

from __future__ import annotations

import io
import re
from functools import lru_cache

import pandas as pd
from rapidfuzz import fuzz, process

# Minimum match confidence (0–100) for a fuzzy match
MIN_CONFIDENCE = 88
# Don't fuzzy-match very short names ("Smith", "A1") — too many false positives
MIN_FUZZY_LEN = 5

_NAME_COLS = ["CompanyName", "Company Name", "company_name"]
_DIRECTOR_COLS = [
    "OfficerName", "Officer Name", "officer_name",
    "DirectorName", "Director Name", "Name",
]

_NOISE_RE = re.compile(r"\b(LIMITED|LTD|LLP|PLC|INC|CO|COMPANY|THE|AND)\b")


def _normalise(name: str) -> str:
    """Uppercase, drop punctuation and legal-form noise ("& Sons Ltd" ≈ "and sons limited")."""
    s = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace("&", " AND "))
    return " ".join(_NOISE_RE.sub(" ", s).split())


def _first_match(columns: list[str], candidates: list[str]) -> str | None:
    return next((c for c in candidates if c in columns), None)


class CompaniesHouseDB:
    """In-memory index of company name → director, with exact + fuzzy lookup."""

    def __init__(self, csv_bytes: bytes):
        self._index: dict[str, str] = {}   # normalised name -> director
        self._names: list[str] = []
        self.has_directors = False
        self._load(csv_bytes)
        self._names = list(self._index)
        self._lookup = lru_cache(maxsize=4096)(self._lookup_uncached)

    def _load(self, csv_bytes: bytes) -> None:
        wanted = set(_NAME_COLS) | set(_DIRECTOR_COLS)
        kwargs = dict(
            dtype=str,
            on_bad_lines="skip",
            low_memory=False,
            usecols=lambda c: c.strip() in wanted,   # skip the ~50 columns we don't need
        )
        try:
            df = pd.read_csv(io.BytesIO(csv_bytes), encoding="utf-8", **kwargs)
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(csv_bytes), encoding="latin-1", **kwargs)

        df.columns = [c.strip() for c in df.columns]
        cols = list(df.columns)

        name_col = _first_match(cols, _NAME_COLS)
        if name_col is None:
            raise ValueError(
                "Could not find a 'CompanyName' column in the uploaded CSV. "
                "Please upload a Companies House BasicCompanyData or Officers CSV."
            )
        dir_col = _first_match([c for c in cols if c != name_col], _DIRECTOR_COLS)
        self.has_directors = dir_col is not None

        names = df[name_col].fillna("").astype(str)
        directors = (
            df[dir_col].fillna("").astype(str).str.strip() if dir_col
            else [""] * len(df)
        )
        index = self._index
        for cn, director in zip(names, directors):
            key = _normalise(cn)
            if key and key not in index:      # keep first officer per company
                index[key] = director

    def _lookup_uncached(self, company_name: str) -> str:
        query = _normalise(company_name)
        if not query:
            return ""
        if query in self._index:
            return self._index[query]
        if len(query) < MIN_FUZZY_LEN or not self._names:
            return ""
        match = process.extractOne(
            query, self._names, scorer=fuzz.token_sort_ratio, score_cutoff=MIN_CONFIDENCE
        )
        return self._index[match[0]] if match else ""

    def get_director(self, company_name: str) -> str:
        """Director/officer of the best-matching company, or "" if none matches."""
        if not self.has_directors or not company_name:
            return ""
        return self._lookup(company_name)

    def __len__(self) -> int:
        return len(self._index)


def extract_uk_town(address: str) -> str:
    """
    Extract the town/city name from a UK registered address.
    e.g. 'Lee House Manchester England M4 6AG' -> 'Manchester'
    """
    import re
    if not address:
        return ""
    addr = re.sub(r"[A-Z]{1,2}\d[A-Z0-9]?\s*\d[A-Z]{2}", "", address, flags=re.IGNORECASE).strip()
    addr = re.sub(r"\b(England|Scotland|Wales|Northern Ireland|United Kingdom|UK)\b", "", addr, flags=re.IGNORECASE).strip()
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if parts:
        last = parts[-1]
        words = last.split()
        return words[-1] if len(parts) == 1 and len(words) > 1 else last
    words = addr.split()
    return words[-1] if words else ""


def parse_uploaded_companies_file(
    csv_bytes: bytes,
    max_rows: int | None = None,
    progress_callback=None,
) -> list[dict[str, Any]]:
    """
    Parse an entire uploaded Companies House CSV file (up to 5,000+ rows)
    and turn every company into a rich 'Needs Website' lead.
    """
    import io
    import urllib.parse
    import pandas as pd

    df = None
    for encoding in ("utf-8", "latin-1", "cp1252"):
        for sep in (None, ",", "\t", ";"):
            try:
                buf = io.BytesIO(csv_bytes)
                test_df = pd.read_csv(
                    buf,
                    sep=sep,
                    engine="python" if sep is None else "c",
                    dtype=str,
                    on_bad_lines="skip",
                    encoding=encoding,
                    nrows=max_rows,
                )
                if test_df.shape[1] > 1:
                    df = test_df
                    break
            except Exception:
                continue
        if df is not None:
            break

    if df is None:
        raise ValueError("Could not parse the uploaded CSV file. Please verify file format.")

    df.columns = [str(c).strip() for c in df.columns]

    def _find(candidates: list[str]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    name_col = _find(["company_name", "CompanyName", "Company Name", "name", "Name"])
    if not name_col:
        raise ValueError("Could not find a company name column in the CSV.")

    addr_col = _find(["registered_office_address", "RegAddress.AddressLine1", "Address", "address", "registered_address"])
    num_col = _find(["company_number", "CompanyNumber", "number", "Company Number"])
    status_col = _find(["company_status", "CompanyStatus", "status", "Status"])
    nature_col = _find(["nature_of_business", "SICCodes", "SIC", "nature_of_business_description"])
    dir_col = _find(["OfficerName", "Officer Name", "DirectorName", "director_name", "Director Name"])

    leads: list[dict[str, Any]] = []
    total = len(df)

    for idx, row in df.iterrows():
        name = str(row[name_col] or "").strip()
        if not name or name.lower() == "nan":
            continue

        raw_addr = str(row[addr_col] or "").strip() if addr_col else ""
        if raw_addr.lower() == "nan":
            raw_addr = ""

        town = extract_uk_town(raw_addr)
        company_num = str(row[num_col] or "").strip() if num_col else str(idx + 1)
        status = str(row[status_col] or "").strip() if status_col else "active"
        nature = str(row[nature_col] or "").strip() if nature_col else ""
        director = str(row[dir_col] or "").strip() if dir_col else ""
        if director.lower() == "nan":
            director = ""

        fb_q = urllib.parse.urlencode({"q": f'"{name}" {town} facebook'})
        li_q = urllib.parse.urlencode({"q": f'"{name}" director site:linkedin.com'}) if not director else urllib.parse.urlencode({"q": f'"{director}" site:linkedin.com'})
        g_q = urllib.parse.urlencode({"q": f'"{name}" {town}'})

        leads.append(
            {
                "place_id": f"ch_{company_num}_{idx}",
                "Name": name,
                "Address": raw_addr,
                "Town": town,
                "Phone": "",
                "Intl Phone": "",
                "Email": "",
                "Website": "",
                "Website Status": "NO WEBSITE",
                "Social Link": "",
                "Rating": None,
                "Reviews": None,
                "Business Status": "OPERATIONAL" if status.lower() in ("active", "operational") else status,
                "Types": nature,
                "Director Name": director,
                "Company Number": company_num,
                "WhatsApp Link": "",
                "Facebook Search": f"https://www.google.com/search?{fb_q}",
                "LinkedIn Search": f"https://www.google.com/search?{li_q}",
                "Google Search": f"https://www.google.com/search?{g_q}",
            }
        )

        if progress_callback and (idx % 250 == 0 or idx == total - 1):
            progress_callback(len(leads), total)

    return leads

