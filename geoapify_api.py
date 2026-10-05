"""
geoapify_api.py
---------------
Wrapper around Geoapify Places and Geocoding APIs (free tier, 3000 req/day).
Docs: https://apidocs.geoapify.com/docs/places/
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests

GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
PLACES_URL = "https://api.geoapify.com/v2/places"

ALL_BUSINESS_CATS = "commercial,catering,service,healthcare,office"

GEOAPIFY_CATEGORIES = {
    "All Businesses": ALL_BUSINESS_CATS,
    "Hair & Beauty Salons": "service.beauty,service.beauty.hairdresser,commercial.health_and_beauty",
    "Restaurants & Food": "catering.restaurant,catering.fast_food",
    "Cafes": "catering.cafe",
    "Bars & Pubs": "catering.bar",
    "Cleaning Services": "service.cleaning",
    "Estate / Property Agents": "office.estate_agent",
    "Car Repair & Auto": "service.vehicle,commercial.vehicle",
    "Hardware & Trade Supplies": "commercial.houseware_and_hardware",
    "Dentists & Clinics": "healthcare.dentist,healthcare",
    "Gyms & Fitness": "sport.fitness",
    "Lawyers & Legal": "office.lawyer,office.financial",
    "Supermarkets & Stores": "commercial.supermarket",
    "Clothing & Fashion": "commercial.clothing",
    "Hotels & Lodging": "accommodation.hotel",
    "Pet Stores & Vets": "commercial.pet",
    "Florists": "commercial.florist",
    "Pharmacies": "commercial.chemist",
}

_TRADE = "service,commercial.houseware_and_hardware"   # generic bucket, used for the word "trade" only
_BEAUTY = "service.beauty,service.beauty.hairdresser,commercial.health_and_beauty"
_AUTO = "service.vehicle,commercial.vehicle"

# Long words are matched as word *prefixes* ("plumb" → plumber, plumbing, plumbers)
STEM_CATEGORIES: dict[str, str] = {
        "hairdress": _BEAUTY, "barber": "service.beauty,service.beauty.hairdresser",
    "salon": _BEAUTY, "beaut": "service.beauty,commercial.health_and_beauty",
    "clean": "service.cleaning", "mechanic": "service.vehicle", "garage": "service.vehicle",
    "restaurant": "catering.restaurant", "takeaway": "catering.fast_food,catering.restaurant",
    "pizza": "catering.restaurant,catering.fast_food",
    "estate": "office.estate_agent", "dentist": "healthcare.dentist",
    "fitness": "sport.fitness", "supermarket": "commercial.supermarket",
    "cloth": "commercial.clothing", "hotel": "accommodation.hotel",
    "flower": "commercial.florist", "florist": "commercial.florist",
    "pharmac": "commercial.chemist", "chemist": "commercial.chemist",
    "lawyer": "office.lawyer", "solicitor": "office.lawyer", "account": "office.financial",
}

# Short words must match a whole word (or its plural) — "car" must not match "carpet"
WORD_CATEGORIES: dict[str, str] = {
    "hair": _BEAUTY, "nail": "service.beauty", "trade": _TRADE,
    "car": _AUTO, "auto": _AUTO, "tyre": "service.vehicle", "tire": "service.vehicle",
    "food": "catering.restaurant,catering.fast_food", "cafe": "catering.cafe",
    "coffee": "catering.cafe", "bar": "catering.bar", "pub": "catering.bar",
    "property": "office.estate_agent", "gym": "sport.fitness",
    "shop": "commercial,commercial.supermarket", "store": "commercial,commercial.supermarket",
    "pet": "commercial.pet", "vet": "commercial.pet",
}

MAX_PAGES = 5          # when filtering client-side, scan at most 5 x 100 places
PAGE_SIZE = 100

_geocode_cache: dict[tuple[str, str], tuple[float, float, str]] = {}


def _words(text: str) -> list[str]:
    """Lowercase alphabetic words, with a trailing plural 's' removed."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in re.findall(r"[a-z]+", text.lower())]


def keyword_to_categories(keyword: str) -> str:
    """Map a free-text keyword to Geoapify categories ("" if no known trade/shop type)."""
    for w in _words(keyword):
        if w in WORD_CATEGORIES:
            return WORD_CATEGORIES[w]
        for stem, cats in STEM_CATEGORIES.items():
            if w.startswith(stem):
                return cats
    return ""


def geocode_location(query: str, api_key: str, country: str = "") -> tuple[float, float, str]:
    """
    Geocode a city, town or postcode to (lat, lon, formatted_name).
    Successful lookups are cached; failures raise RuntimeError (and are not cached).
    """
    query = (query or "").strip()
    if not query:
        raise RuntimeError("Please enter a city or postcode.")
    cache_key = (f"{query.lower()}|{country.lower()}", api_key)
    cached = _geocode_cache.get(cache_key)
    if cached:
        return cached

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.get(
                GEOCODE_URL,
                params={
                    "text": query, "apiKey": api_key, "limit": 1,
                    **({"filter": f"countrycode:{country.lower()}"} if country else {}),
                },
                headers={"Accept": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
            if not features:
                where = f" in {country.upper()}" if country else ""
                raise RuntimeError(f"Location '{query}' was not found{where}. Check the spelling.")
            props = features[0].get("properties", {})
            result = (float(props["lat"]), float(props["lon"]), props.get("formatted", query))
            _geocode_cache[cache_key] = result
            return result
        except RuntimeError:
            raise
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                raise RuntimeError("Geoapify rejected the API key (401/403).") from e
            last_error = e
        except (requests.RequestException, KeyError, ValueError) as e:
            last_error = e
        if attempt == 0:
            time.sleep(1)
    raise RuntimeError(f"Could not geocode '{query}': {last_error}")


def clean_phone(raw: Any) -> tuple[str, str]:
    """
    Take the FIRST number of a possibly multi-number string.
    Returns (display_phone, digits_with_optional_leading_plus).
    """
    if not raw:
        return "", ""
    first = next((p.strip() for p in re.split(r"[;,/|]| or ", str(raw)) if p.strip()), "")
    digits = re.sub(r"[^\d+]", "", first)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    digits = digits[:1] + digits[1:].replace("+", "")   # '+' only allowed first
    return first, digits


def search_geoapify(
    api_key: str,
    *,
    keyword: str = "",
    category_key: str = "",
    city: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 10.0,
    max_results: int = 20,
    progress_callback=None,
    notes: list[str] | None = None,
    country: str = "",
) -> list[dict[str, Any]]:
    """
    Search businesses using Geoapify Places with retry and resilient timeouts.

    Category selection:
      * a chosen category always wins;
      * otherwise a keyword that names a known shop/service type picks the categories;
      * any other keyword (incl. trades like plumber/electrician, which have no
        Geoapify category) is applied as a name/category text filter.
    A keyword used together with a chosen category also acts as a text filter.
    """
    # 1. Resolve coordinates (no silent fallback — wrong place = wrong leads)
    if lat is not None and lon is not None:
        resolved_lat, resolved_lon, resolved_town = lat, lon, city
    else:
        resolved_lat, resolved_lon, resolved_town = geocode_location(city, api_key, country)

    # 2. Categories + optional text filter
    cats = GEOAPIFY_CATEGORIES.get(category_key, "")
    text_tokens: list[str] = []
    if keyword.strip():
        mapped = "" if cats else keyword_to_categories(keyword)
        if mapped:
            cats = mapped
        if not mapped:
            # e.g. plumber/electrician/builder: Geoapify has no such category, so scan
            # the broad business categories and require the keyword in the name/category.
            text_tokens = _words(keyword)
    cats = cats or ALL_BUSINESS_CATS

    def matches(name: str, categories: list[str]) -> bool:
        haystack = f"{name} {' '.join(categories)}".lower()
        return all(t in haystack for t in text_tokens)

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0
    radius_meters = int(radius_km * 1000)
    max_pages = MAX_PAGES if text_tokens else 1 + max_results // PAGE_SIZE

    for _ in range(max_pages):
        batch_limit = PAGE_SIZE if text_tokens else min(PAGE_SIZE, max_results - len(results))
        params: dict[str, Any] = {
            "categories": cats,
            "filter": f"circle:{resolved_lon},{resolved_lat},{radius_meters}",
            "bias": f"proximity:{resolved_lon},{resolved_lat}",
            "limit": batch_limit,
            "offset": offset,
            "apiKey": api_key,
        }

        data = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    PLACES_URL, params=params, headers={"Accept": "application/json"}, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.HTTPError as e:
                try:
                    msg = e.response.json().get("message", str(e))
                except Exception:
                    msg = str(e)
                raise RuntimeError(f"Geoapify API Error: {msg}") from e
            except requests.RequestException as e:   # timeouts / network glitches
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if results:
                    return results       # keep partial results
                raise RuntimeError(
                    "Geoapify is not responding. Search again or reduce the radius."
                ) from e

        features = (data or {}).get("features", [])
        if not features:
            break

        for feat in features:
            props = feat.get("properties", {})
            name = props.get("name") or ""
            if not name:
                continue   # unnamed POIs (benches, ATMs…) are useless as leads

            categories = props.get("categories", []) or []
            if text_tokens and not matches(name, categories):
                continue

            place_id = props.get("place_id") or f"geo_{props.get('lon')}_{props.get('lat')}_{name}"
            if place_id in seen_ids:
                continue
            seen_ids.add(place_id)

            contact = props.get("contact", {}) or {}
            phone_display, phone_digits = clean_phone(contact.get("phone") or props.get("phone"))
            email = contact.get("email") or props.get("email") or ""
            website = contact.get("website") or props.get("website") or props.get("url") or ""
            town = (
                props.get("city") or props.get("town") or props.get("village")
                or props.get("suburb") or props.get("county") or resolved_town
            )

            results.append(
                {
                    "place_id": place_id,
                    "Name": name,
                    "Address": props.get("formatted", props.get("address_line2", "")),
                    "Town": town,
                    "Phone": phone_display,
                    "Intl Phone": phone_digits,
                    "Email": str(email).strip(),
                    "Website": website,
                    "Rating": None,
                    "Reviews": None,
                    "Business Status": "OPERATIONAL",
                    "Types": ", ".join(categories[:3]),
                }
            )
            if len(results) >= max_results:
                break

        if progress_callback:
            progress_callback(len(results), max_results)
        if len(results) >= max_results or len(features) < batch_limit:
            break
        offset += len(features)

    if text_tokens and not results and notes is not None:
        notes.append(
            f"No places with '{keyword.strip()}' in their name/category were found among the first "
            f"{MAX_PAGES * PAGE_SIZE} businesses in this area. OpenStreetMap has little data for "
            "trades — try a bigger radius, a Category, or switch to Google Places."
        )
    return results
