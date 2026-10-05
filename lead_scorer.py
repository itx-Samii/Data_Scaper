"""
lead_scorer.py
--------------
Computes a Lead Score (0–100) for each business based on:
  - Rating           : 0–5 stars → up to 20 pts
  - Review count     : log-scaled → up to 30 pts
  - Website status   : NO WEBSITE = 30 pts, SOCIAL ONLY = 20 pts, HAS WEBSITE = 0 pts
  - Contactable      : has a phone number = 20 pts

Providers without reputation data (e.g. Geoapify has no ratings/reviews) are
scored on website status + contactability only, rescaled to 0–100.
Permanently closed businesses always score 0.

Higher score = better prospect for selling a website.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Score weights (must sum to 100)
# ---------------------------------------------------------------------------
W_RATING = 20      # max points from star rating
W_REVIEWS = 30     # max points from review count
W_WEBSITE = 30     # max points from website status
W_CONTACT = 20     # points for having a phone number
W_EMAIL = 10       # extra points for a public email (sources without ratings only)

SCORE_WEIGHTS = {
    "Rating": W_RATING,
    "Reviews (log-scaled)": W_REVIEWS,
    "No website (social only = ⅔)": W_WEBSITE,
    "Has phone number": W_CONTACT,
    "Has email (when there are no ratings)": W_EMAIL,
}

# Review count at which a business earns the full review points
REVIEWS_SCALE = 200.0

_WEBSITE_FACTOR = {"NO WEBSITE": 1.0, "SOCIAL ONLY": 2 / 3}


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    """Column as float with NaN for missing/invalid values."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").astype("float64")


def score_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add / overwrite an integer 'Lead Score' column (vectorised, NaN-safe).
    Uses columns: Rating, Reviews, Website Status, Phone, Business Status.
    """
    if df.empty:
        df["Lead Score"] = pd.Series(dtype="int64")
        return df

    rating = _numeric(df, "Rating")
    reviews = _numeric(df, "Reviews")
    # Reputation data exists per *source* (Google has ratings, Geoapify/Companies House don't),
    # so judge each source separately — important when saved leads from several sources are mixed.
    has_data = rating.notna() | reviews.notna()
    if "Source" in df.columns:
        has_reputation = has_data.groupby(df["Source"].fillna("")).transform("any")
    else:
        has_reputation = pd.Series(bool(has_data.any()), index=df.index)

    rating_pts = rating.fillna(0).clip(0, 5) / 5.0 * W_RATING
    review_pts = (
        np.minimum(np.log1p(reviews.fillna(0).clip(lower=0)) / math.log(REVIEWS_SCALE + 1), 1.0)
        * W_REVIEWS
    )

    status = df["Website Status"] if "Website Status" in df.columns else pd.Series("", index=df.index)
    website_pts = status.map(_WEBSITE_FACTOR).fillna(0.0) * W_WEBSITE

    phone = df["Phone"] if "Phone" in df.columns else pd.Series("", index=df.index)
    contact_pts = phone.fillna("").astype(str).str.strip().ne("") * float(W_CONTACT)

    email = (
        df["Email"].fillna("").astype(str).str.contains("@")
        if "Email" in df.columns else pd.Series(False, index=df.index)
    )
    email_pts = email * float(W_EMAIL)

    full = rating_pts + review_pts + website_pts + contact_pts
    rescaled = (website_pts + contact_pts + email_pts) / (W_WEBSITE + W_CONTACT + W_EMAIL) * 100.0
    total = full.where(has_reputation, rescaled)

    if "Business Status" in df.columns:
        closed = df["Business Status"].fillna("").astype(str).str.upper().str.startswith("CLOSED")
        total = total.mask(closed, 0.0)

    df["Lead Score"] = total.round().astype("int64")
    return df
