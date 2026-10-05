"""
places_api.py
-------------
Wrapper around the Google Places API (New) — Text Search endpoint.
POST https://places.googleapis.com/v1/places:searchText

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields we request (billed per field mask — keep minimal).
# NOTE: nextPageToken is a top-level response field, NOT a place field.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.types",
        "nextPageToken",
    ]
)

# Text Search returns at most 3 pages x 20 results per query
MAX_PLACES_RESULTS = 60
PAGE_SIZE = 20

_session = requests.Session()

# Google Places (New) supported category types (subset of common ones)
CATEGORY_TYPES: list[str] = [
    "accounting",
    "airport",
    "amusement_park",
    "aquarium",
    "art_gallery",
    "atm",
    "bakery",
    "bank",
    "bar",
    "beauty_salon",
    "bicycle_store",
    "book_store",
    "bowling_alley",
    "bus_station",
    "cafe",
    "campground",
    "car_dealer",
    "car_rental",
    "car_repair",
    "car_wash",
    "casino",
    "cemetery",
    "church",
    "city_hall",
    "clothing_store",
    "convenience_store",
    "courthouse",
    "dentist",
    "department_store",
    "doctor",
    "drugstore",
    "electrician",
    "electronics_store",
    "embassy",
    "fire_station",
    "florist",
    "funeral_home",
    "furniture_store",
    "gas_station",
    "gym",
    "hair_care",
    "hardware_store",
    "hindu_temple",
    "home_goods_store",
    "hospital",
    "insurance_agency",
    "jewelry_store",
    "laundry",
    "lawyer",
    "library",
    "light_rail_station",
    "liquor_store",
    "local_government_office",
    "locksmith",
    "lodging",
    "meal_delivery",
    "meal_takeaway",
    "mosque",
    "movie_rental",
    "movie_theater",
    "moving_company",
    "museum",
    "night_club",
    "painter",
    "park",
    "parking",
    "pet_store",
    "pharmacy",
    "physiotherapist",
    "plumber",
    "police",
    "post_office",
    "real_estate_agency",
    "restaurant",
    "roofing_contractor",
    "rv_park",
    "school",
    "secondary_school",
    "shoe_store",
    "shopping_mall",
    "spa",
    "stadium",
    "storage",
    "store",
    "subway_station",
    "supermarket",
    "synagogue",
    "taxi_stand",
    "tourist_attraction",
    "train_station",
    "transit_station",
    "travel_agency",
    "university",
    "veterinary_care",
    "zoo",
]


# ---------------------------------------------------------------------------
# Geocoding helper (city name → lat/lng)
# ---------------------------------------------------------------------------

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode_city(city: str, api_key: str, country: str = "") -> tuple[float, float]:
    """
    Convert a city/postcode name to (lat, lng) using the Geocoding API.
    Raises RuntimeError with the real reason on failure (API not enabled,
    bad key, unknown place, network error).
    """
    try:
        resp = _session.get(
            GEOCODE_URL,
            params={"address": city, "key": api_key, **({"components": f"country:{country}"} if country else {})},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Geocoding network error: {e}") from e

    status = data.get("status")
    if status == "OK" and data.get("results"):
        loc = data["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    if status == "ZERO_RESULTS":
        raise RuntimeError(f"Location '{city}' was not found.")
    raise RuntimeError(
        f"Geocoding API error ({status}): "
        f"{data.get('error_message', 'enable the Geocoding API for this key')}"
    )


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search_places(
    api_key: str,
    *,
    keyword: str = "",
    category: str = "",
    city: str = "",
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 10.0,
    max_results: int = 20,
    progress_callback=None,
    notes: list[str] | None = None,
    country: str = "",
) -> list[dict[str, Any]]:
    """
    Search Google Places (New) Text Search API.

    Parameters
    ----------
    api_key       : Google Places API key
    keyword       : free-text keyword (e.g. "plumbers")
    category      : Places API type (e.g. "plumber")
    city          : city/postcode name (geocoded for the radius bias)
    lat, lng      : explicit coordinates (override city geocoding)
    radius_km     : search radius in km (location *bias*, not a hard limit)
    max_results   : number of results wanted (capped at MAX_PLACES_RESULTS)
    progress_callback : optional callable(current, total)
    notes         : optional list; non-fatal warnings are appended to it

    Returns
    -------
    list of dicts with normalised place fields
    """
    max_results = min(max_results, MAX_PLACES_RESULTS)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    # Resolve location bias. The city is already in the text query, so a
    # geocoding failure is non-fatal: we fall back to text-only matching.
    resolved_lat, resolved_lng = lat, lng
    if (resolved_lat is None or resolved_lng is None) and city:
        try:
            resolved_lat, resolved_lng = geocode_city(city, api_key, country)
        except RuntimeError as e:
            resolved_lat = resolved_lng = None
            if notes is not None:
                notes.append(f"Radius ignored — {e} Searching by place name only.")

    # Build text query
    place_term = keyword or category.replace("_", " ")
    if place_term and city:
        text_query = f"{place_term} in {city}"
    else:
        text_query = place_term or city or "businesses"

    base_payload: dict[str, Any] = {"textQuery": text_query, "languageCode": "en"}
    if country:
        base_payload["regionCode"] = country.lower()
    if category:
        base_payload["includedType"] = category
    if resolved_lat is not None and resolved_lng is not None:
        base_payload["locationBias"] = {
            "circle": {
                "center": {"latitude": resolved_lat, "longitude": resolved_lng},
                "radius": min(radius_km * 1000, 50000.0),  # API max is 50 km
            }
        }

    results: list[dict] = []
    seen: set[str] = set()
    page_token: str | None = None

    while len(results) < max_results:
        payload = {**base_payload, "pageSize": min(PAGE_SIZE, max_results - len(results))}
        if page_token:
            payload["pageToken"] = page_token

        try:
            resp = _session.post(
                PLACES_TEXT_SEARCH_URL, json=payload, headers=headers, timeout=15
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            try:
                error_body = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                error_body = str(e)
            raise RuntimeError(f"Places API error: {error_body}") from e
        except requests.RequestException as e:
            raise RuntimeError(f"Network error: {e}") from e

        data = resp.json()
        places = data.get("places", [])

        for place in places:
            pid = place.get("id", "")
            if pid in seen:
                continue
            seen.add(pid)
            results.append(_normalise(place))
            if len(results) >= max_results:
                break
        if progress_callback:
            progress_callback(len(results), max_results)

        page_token = data.get("nextPageToken")
        if not page_token or not places:
            break

    return results


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalise(place: dict) -> dict[str, Any]:
    """Flatten a Places API place object into a simple dict."""
    name = place.get("displayName", {}).get("text", "")
    address = place.get("formattedAddress", "")
    town = _extract_town(address)

    return {
        "place_id": place.get("id", ""),
        "Name": name,
        "Address": address,
        "Town": town,
        "Phone": place.get("nationalPhoneNumber", ""),
        "Intl Phone": place.get("internationalPhoneNumber", ""),
        "Website": place.get("websiteUri", ""),
        "Rating": place.get("rating"),
        "Reviews": place.get("userRatingCount"),
        "Business Status": place.get("businessStatus", ""),
        "Types": ", ".join(place.get("types", [])),
    }


def _extract_town(address: str) -> str:
    """
    Best-effort extraction of town/city from a formatted address.
    Formatted addresses are typically: "Street, Town, County, Postcode, Country"
    We return the second-to-last comma-separated component (before country).
    """
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 3:
        # Skip last part (country), try second-to-last or third-to-last
        # Look for a part that isn't a postcode (UK postcodes match \w\d pattern)
        for part in reversed(parts[:-1]):
            if not re.match(r"^[A-Z]{1,2}\d", part, re.IGNORECASE):
                return part
    if len(parts) >= 2:
        return parts[-2]
    return parts[-1] if parts else ""
