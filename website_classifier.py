"""
website_classifier.py
---------------------
Classifies a business website URL into one of three categories:
  - "NO WEBSITE"    : empty / null
  - "SOCIAL ONLY"   : social profile, free site-builder subdomain, or a
                      directory / booking page (not a site the business owns)
  - "HAS WEBSITE"   : a real business website

Returns (classification, social_link | None).
Matching is done on the URL's hostname (exact or subdomain), not substrings.
"""

from __future__ import annotations

from urllib.parse import urlparse

SOCIAL_DOMAINS = frozenset(
    {
        # social / link-in-bio
        "facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee",
        "linkin.bio", "wa.me", "whatsapp.com", "tiktok.com", "twitter.com",
        "x.com", "linkedin.com", "youtube.com", "pinterest.com",
        # free site builders
        "wixsite.com", "business.site", "sites.google.com", "godaddysites.com",
        "weebly.com", "blogspot.com", "wordpress.com", "carrd.co", "square.site",
        # maps / directories / booking / delivery pages
        "g.page", "goo.gl", "maps.app.goo.gl", "google.com", "yell.com",
        "checkatrade.com", "trustpilot.com", "yelp.com", "tripadvisor.com",
        "tripadvisor.co.uk", "freeindex.co.uk", "bark.com", "mybuilder.com",
        "ratedpeople.com", "thomsonlocal.com", "fresha.com", "treatwell.co.uk",
        "booksy.com", "opentable.com", "ubereats.com", "just-eat.co.uk",
        "deliveroo.co.uk", "uber.com",
    }
)


def _hostname(url: str) -> str:
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    try:
        host = urlparse(u).hostname or ""
    except ValueError:
        return ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _is_listed(host: str) -> bool:
    parts = host.split(".")
    # Check host and every parent domain: a.b.facebook.com → b.facebook.com → facebook.com
    return any(".".join(parts[i:]) in SOCIAL_DOMAINS for i in range(len(parts) - 1))


def classify_website(url: str | None) -> tuple[str, str | None]:
    """
    Classify a website URL.

    Returns
    -------
    (classification, social_link)
        classification : "NO WEBSITE" | "SOCIAL ONLY" | "HAS WEBSITE"
        social_link    : the URL if SOCIAL ONLY, else None
    """
    if not isinstance(url, str) or not url.strip():
        return "NO WEBSITE", None

    if _is_listed(_hostname(url)):
        return "SOCIAL ONLY", url.strip()

    return "HAS WEBSITE", None


def needs_website(classification: str) -> bool:
    """Return True if the lead is a 'Needs Website' prospect."""
    return classification in ("NO WEBSITE", "SOCIAL ONLY")
