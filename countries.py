"""
countries.py
------------
Target countries for the search: ISO-3166 code (used to restrict geocoding and place
search) and the calling code (used to turn local phone numbers into WhatsApp numbers).
"""

from __future__ import annotations

# name -> (ISO 3166-1 alpha-2, calling code). "" = not restricted.
COUNTRIES: dict[str, tuple[str, str]] = {
    "United Kingdom": ("GB", "44"),
    "United States": ("US", "1"),
    "Canada": ("CA", "1"),
    "Australia": ("AU", "61"),
    "New Zealand": ("NZ", "64"),
    "Ireland": ("IE", "353"),
    "United Arab Emirates": ("AE", "971"),
    "Saudi Arabia": ("SA", "966"),
    "Qatar": ("QA", "974"),
    "Kuwait": ("KW", "965"),
    "Bahrain": ("BH", "973"),
    "Oman": ("OM", "968"),
    "Germany": ("DE", "49"),
    "France": ("FR", "33"),
    "Netherlands": ("NL", "31"),
    "Belgium": ("BE", "32"),
    "Spain": ("ES", "34"),
    "Italy": ("IT", "39"),
    "Portugal": ("PT", "351"),
    "Sweden": ("SE", "46"),
    "Norway": ("NO", "47"),
    "Denmark": ("DK", "45"),
    "Finland": ("FI", "358"),
    "Switzerland": ("CH", "41"),
    "Austria": ("AT", "43"),
    "Poland": ("PL", "48"),
    "Turkey": ("TR", "90"),
    "South Africa": ("ZA", "27"),
    "Singapore": ("SG", "65"),
    "Malaysia": ("MY", "60"),
    "India": ("IN", "91"),
    "Pakistan": ("PK", "92"),
    "Any country (no restriction)": ("", ""),
}

DEFAULT_COUNTRY = "United Kingdom"
