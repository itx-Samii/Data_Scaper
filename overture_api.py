"""
overture_api.py
---------------
Searches the Overture Maps "places" dataset (open data from Meta, Microsoft and others):
free, no API key, worldwide. Unlike Google/Geoapify it often includes the business's
public EMAIL and Facebook page, plus phone and website.

Data is read straight from Overture's public S3 bucket with DuckDB (only the rows
inside the search area are downloaded; a search takes roughly 5-40 seconds).
Licence: open (CDLA-Permissive) — crediting "Overture Maps Foundation" is good practice.
"""

from __future__ import annotations

import math
import re
from typing import Any

import requests

from geoapify_api import clean_phone
from website_classifier import classify_website

FALLBACK_RELEASE = "2026-09-23.1"
STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "DataScalper/1.0 (local lead research tool)"
MAX_OVERTURE_RESULTS = 1000
MIN_CONFIDENCE = 0.4

# Label -> Overture `taxonomy.primary` values; a trailing/leading % means SQL LIKE.
OVERTURE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Hair & beauty (salons, barbers, nails)": (
        "hair_salon", "barber", "beauty_salon", "nail_salon", "hair_stylist",
        "kids_hair_salon", "personal_or_beauty_service"),
    "Spas & massage": ("spa", "day_spa", "health_spa", "medical_spa", "massage_therapy"),
    "Tattoo & piercing": ("tattoo_and_piercing", "tattoo"),
    "Restaurants & takeaways": ("%restaurant", "pizza_delivery_service"),
    "Cafes & bakeries": ("cafe", "coffee_shop", "bakery", "coffee_roastery"),
    "Pubs & bars": ("pub", "bar", "irish_pub", "gastropub", "beer_garden"),
    "Plumbers": ("plumbing",),
    "Electricians": ("electrician",),
    "Builders & contractors": (
        "contractor", "building_contractor", "builder", "building_or_construction_service",
        "flooring_contractor", "paving_contractor", "masonry_contractor",
        "altering_and_remodeling_contractor", "handyman", "home_service"),
    "Roofing": ("roofing",),
    "Painters & decorators": ("painting",),
    "Carpenters & joiners": ("carpenter", "carpet_installation"),
    "Locksmiths": ("key_and_locksmith",),
    "Cleaning services": (
        "home_cleaning", "cleaning_service", "carpet_cleaning", "office_cleaning",
        "industrial_cleaning_service", "pool_cleaning"),
    "Landscaping & gardening": ("gardener", "landscaping", "landscape_architect"),
    "Car repair & garages": (
        "automotive_repair", "automotive_service", "auto_body_shop", "auto_electrical_repair",
        "auto_detailing", "car_wash", "auto_glass_service", "auto_customization"),
    "Car dealers": ("auto_dealer", "used_auto_dealer"),
    "Taxis & driving schools": ("taxi_service", "driving_school", "town_car_service"),
    "Dentists": ("dental_clinic", "general_dentistry", "cosmetic_dentistry", "pediatric_dentistry"),
    "Gyms & fitness": ("gym", "fitness_trainer", "yoga_studio", "sport_or_fitness_facility"),
    "Accountants": ("accountant",),
    "Lawyers & solicitors": ("%lawyer",),
    "Estate agents": ("real_estate_agent", "real_estate_service"),
    "Florists": ("florist",),
    "Photographers": ("photography_service", "event_photography_service", "session_photography_service"),
    "Pet services & vets": (
        "pet_groomer", "pet_store", "veterinarian", "pet_boarding", "pet_sitting", "animal_or_pet_service"),
    "Clothing & boutiques": (
        "clothing_store", "womens_clothing_store", "mens_clothing_store",
        "childrens_clothing_store", "fashion_boutique"),
    "Hotels & guest houses": ("hotel", "guest_house"),
    "Tutoring & music schools": ("tutoring_service", "private_tutor", "music_school", "language_school"),
    "Printing": ("printing_service", "t_shirt_printing_service", "commercial_printer"),
    "Funeral services": ("funeral_service",),
}

# Keyword stems -> category label (first match wins). Short words are matched as whole words.
_STEMS: tuple[tuple[str, str], ...] = (
    ("barber", "Hair & beauty (salons, barbers, nails)"), ("hairdress", "Hair & beauty (salons, barbers, nails)"),
    ("salon", "Hair & beauty (salons, barbers, nails)"), ("beaut", "Hair & beauty (salons, barbers, nails)"),
    ("massage", "Spas & massage"), ("tattoo", "Tattoo & piercing"),
    ("restaurant", "Restaurants & takeaways"), ("takeaway", "Restaurants & takeaways"),
    ("pizza", "Restaurants & takeaways"), ("kebab", "Restaurants & takeaways"),
    ("bakery", "Cafes & bakeries"), ("plumb", "Plumbers"), ("electric", "Electricians"),
    ("roof", "Roofing"), ("builder", "Builders & contractors"), ("contractor", "Builders & contractors"),
    ("construct", "Builders & contractors"), ("handyman", "Builders & contractors"),
    ("decorat", "Painters & decorators"), ("carpent", "Carpenters & joiners"), ("joiner", "Carpenters & joiners"),
    ("locksmith", "Locksmiths"), ("clean", "Cleaning services"), ("garden", "Landscaping & gardening"),
    ("landscap", "Landscaping & gardening"), ("mechanic", "Car repair & garages"), ("garage", "Car repair & garages"),
    ("dentist", "Dentists"), ("fitness", "Gyms & fitness"), ("yoga", "Gyms & fitness"),
    ("account", "Accountants"), ("solicitor", "Lawyers & solicitors"), ("lawyer", "Lawyers & solicitors"),
    ("estate", "Estate agents"), ("florist", "Florists"), ("flower", "Florists"),
    ("photograph", "Photographers"), ("groom", "Pet services & vets"), ("tutor", "Tutoring & music schools"),
    ("print", "Printing"), ("funeral", "Funeral services"), ("hotel", "Hotels & guest houses"),
    ("taxi", "Taxis & driving schools"),
)
_WORDS: dict[str, str] = {
    "hair": "Hair & beauty (salons, barbers, nails)", "nail": "Hair & beauty (salons, barbers, nails)",
    "spa": "Spas & massage", "food": "Restaurants & takeaways", "cafe": "Cafes & bakeries",
    "coffee": "Cafes & bakeries", "pub": "Pubs & bars", "bar": "Pubs & bars", "gym": "Gyms & fitness",
    "car": "Car repair & garages", "tyre": "Car repair & garages", "tire": "Car repair & garages",
    "pet": "Pet services & vets", "vet": "Pet services & vets", "paint": "Painters & decorators",
    "driving": "Taxis & driving schools", "shop": "Clothing & boutiques",
}

_geocode_cache: dict[tuple[str, str], tuple[float, float, str]] = {}
_release_cache: list[str] = []


def _words(text: str) -> list[str]:
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z]+", text.lower())]


def keyword_to_category(keyword: str) -> str:
    """Category label for a keyword ("" if none): 'barbers' → Hair & beauty."""
    for w in _words(keyword):
        if w in _WORDS:
            return _WORDS[w]
        for stem, label in _STEMS:
            if w.startswith(stem):
                return label
    return ""


def latest_release() -> str:
    """Newest Overture release id (cached); falls back to a known release if offline."""
    if not _release_cache:
        try:
            resp = requests.get(STAC_CATALOG, timeout=10, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            _release_cache.append(str(resp.json()["latest"]))
        except (requests.RequestException, KeyError, ValueError):
            return FALLBACK_RELEASE
    return _release_cache[0]


def geocode(query: str, country: str = "") -> tuple[float, float, str]:
    """City / town / postcode → (lat, lon, name) with OpenStreetMap Nominatim (free, no key)."""
    query = (query or "").strip()
    if not query:
        raise RuntimeError("Please enter a city or postcode.")
    key = (query.lower(), country.lower())
    if key in _geocode_cache:
        return _geocode_cache[key]
    params: dict[str, Any] = {"q": query, "format": "jsonv2", "limit": 1}
    if country:
        params["countrycodes"] = country.lower()
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        hits = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise RuntimeError(f"Could not look up '{query}': {e}") from e
    if not hits:
        where = f" in {country.upper()}" if country else ""
        raise RuntimeError(f"Location '{query}' was not found{where}. Check the spelling.")
    result = (float(hits[0]["lat"]), float(hits[0]["lon"]), hits[0].get("display_name", query))
    _geocode_cache[key] = result
    return result


def _haversine_km(lat1: float, lon1: float, lat2, lon2):
    p = math.pi / 180
    a = (
        0.5 - (lat2 * p - lat1 * p).apply(math.cos) / 2
        + math.cos(lat1 * p) * (lat2 * p).apply(math.cos) * (1 - ((lon2 - lon1) * p).apply(math.cos)) / 2
    )
    return 2 * 6371 * a.clip(0, 1).apply(math.sqrt).apply(math.asin)


def _category_sql(labels: list[str]) -> str:
    """SQL predicate on taxonomy.primary for category labels (values come from our own table)."""
    values = [v for label in labels for v in OVERTURE_CATEGORIES[label]]
    exact = [v for v in values if "%" not in v]
    likes = [v for v in values if "%" in v]
    parts = []
    if exact:
        parts.append("taxonomy.primary IN (" + ", ".join(f"'{v}'" for v in exact) + ")")
    parts += [f"taxonomy.primary LIKE '{v}'" for v in likes]
    return "(" + " OR ".join(parts) + ")"


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


CHAIN_MIN_REPEATS = 3      # same name this many times in the area = chain / franchise


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(values) -> list:
    """Overture list columns arrive as lists/arrays, or as NA/None when empty."""
    return list(values) if values is not None and hasattr(values, "__len__") else []


def _first(values) -> str:
    items = _as_list(values)
    return str(items[0]).strip() if items else ""


def search_overture(
    *,
    keyword: str = "",
    category_key: str = "",
    city: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 10.0,
    max_results: int = 100,
    country: str = "",
    notes: list[str] | None = None,
    exclude_chains: bool = True,
) -> list[dict[str, Any]]:
    """
    Places inside `radius_km` of a city (or lat/lon), as lead dicts, most reliable first.

    `category_key` may hold several category labels separated by "|". Category selection
    mirrors the other providers: chosen categories win; otherwise a keyword naming a known
    business type picks one; any other keyword filters by name/type.

    exclude_chains drops well-known brands (Wikidata-tagged) and any name that appears
    CHAIN_MIN_REPEATS+ times in the area. (Overture's plain `brand` tag is too noisy to use:
    it is also set on many independents and missing on many chains.)
    """
    import duckdb          # imported here so the rest of the app works without it

    if lat is not None and lon is not None:
        centre_lat, centre_lon, town = lat, lon, city
    else:
        centre_lat, centre_lon, town = geocode(city, country)
        town = (town or city).split(",")[0].strip()

    labels = [c for c in category_key.split("|") if c in OVERTURE_CATEGORIES]
    tokens: list[str] = []
    if keyword.strip():
        mapped = "" if labels else keyword_to_category(keyword)
        if mapped:
            labels = [mapped]
        else:
            tokens = _words(keyword)
    if not labels and not tokens:
        raise RuntimeError("Choose a category or enter a keyword.")

    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(centre_lat)), 0.01))
    where = [
        "bbox.xmin BETWEEN ? AND ?", "bbox.ymin BETWEEN ? AND ?",
        "names.primary IS NOT NULL", "confidence >= ?",
    ]
    params: list[Any] = [centre_lon - dlon, centre_lon + dlon, centre_lat - dlat, centre_lat + dlat, MIN_CONFIDENCE]
    if labels:
        where.append(_category_sql(labels))
    for tok in tokens:
        where.append("(lower(names.primary) LIKE ? OR lower(coalesce(taxonomy.primary, '')) LIKE ?)")
        params += [f"%{tok}%", f"%{tok}%"]

    release = latest_release()
    sql = f"""
        SELECT id, names.primary AS name, taxonomy.primary AS cat, phones, websites, emails, socials,
               addresses[1].freeform AS street, addresses[1].locality AS locality,
               addresses[1].region AS region, addresses[1].postcode AS postcode,
               addresses[1].country AS country, confidence, operating_status, brand.wikidata AS brand_wd,
               bbox.xmin AS x, bbox.ymin AS y
        FROM read_parquet('s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*',
                          hive_partitioning=1)
        WHERE {' AND '.join(where)}
    """
    try:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
        df = con.execute(sql, params).df()
    except Exception as e:      # network / S3 / extension download problems
        raise RuntimeError(f"Overture Maps data could not be read: {e}") from e

    if df.empty:
        if notes is not None:
            notes.append("No places found. Try a bigger radius, another category, or another provider.")
        return []

    df["km"] = _haversine_km(centre_lat, centre_lon, df["y"], df["x"])
    df = df[df["km"] <= radius_km]
    n_before = len(df)
    if exclude_chains and not df.empty:
        key = df["name"].map(_name_key)
        repeated = key.map(key.value_counts()) >= CHAIN_MIN_REPEATS
        df = df[~(repeated | df["brand_wd"].notna())]
        if notes is not None and n_before > len(df):
            notes.append(f"Skipped {n_before - len(df)} chain / franchise places (untick 'Skip big chains' to keep them).")
    df["has_site"] = df["websites"].apply(
        lambda ws: any(classify_website(w)[0] == "HAS WEBSITE" for w in _as_list(ws))
    )
    # Leads without a real website first (that is what we are looking for), then most reliable
    df = df.sort_values(["has_site", "confidence", "km"], ascending=[True, False, True])
    df = df.head(min(max_results, MAX_OVERTURE_RESULTS))

    leads: list[dict[str, Any]] = []
    for r in df.to_dict("records"):
        websites = _as_list(r["websites"])
        website = next((w for w in websites if classify_website(w)[0] == "HAS WEBSITE"), "")
        social = _first(r["socials"]) or next(
            (w for w in websites if classify_website(w)[0] == "SOCIAL ONLY"), "")
        phone_display, phone_digits = clean_phone(_first(r["phones"]))
        address = ", ".join(str(p).strip() for p in (r["street"], r["locality"], r["postcode"], r["country"])
                            if isinstance(p, str) and p.strip())
        closed = str(r["operating_status"] or "").lower() in ("closed", "permanently_closed")
        leads.append(
            {
                "place_id": f"ov_{r['id']}",
                "Name": str(r["name"]).strip(),
                "Address": address,
                "Town": _text(r["locality"]) or _text(r["region"]) or town,
                "Phone": phone_display,
                "Intl Phone": phone_digits,
                "Email": _first(r["emails"]),
                "Website": website or social,      # only a social page → shows up as SOCIAL ONLY
                "Rating": None,
                "Reviews": None,
                "Business Status": "CLOSED_PERMANENTLY" if closed else "OPERATIONAL",
                "Types": str(r["cat"] or ""),
            }
        )
    if notes is not None:
        notes.append(
            "Overture Maps data: phone, email and Facebook page come from public business listings "
            "and can be outdated — check before contacting."
        )
    return leads
