"""
outreach.py
-----------
Everything about *contacting* a lead:
  * phone_type()      — UK mobile vs landline (landlines can't use WhatsApp)
  * best_channel()    — which way to reach the lead
  * business_type()   — "barbers", "plumbers"… for the message text
  * add_outreach()    — per-lead email subject/body, WhatsApp message + links
  * load/save_settings() — sender details and templates, kept between runs

Templates use {placeholders}; unknown placeholders are left untouched.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

import pandas as pd
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
from phonenumbers import timezone as pn_timezone

SETTINGS_FILE = Path(__file__).parent / "outreach_settings.json"

PLACEHOLDERS = (
    "{greeting} {business_name} {business_type} {town} {first_name} "
    "{sender_name} {from_business} {signature} {days}"
)

DEFAULT_SETTINGS: dict[str, str] = {
    "sender_name": "",
    "sender_business": "",
    "sender_phone": "",
    "portfolio": "",
    "days": "7",
    "subject": "A website for {business_name}?",
    "email_body": (
        "{greeting}\n\n"
        "I'm {sender_name}{from_business}, a web designer. While looking for {business_type} "
        "in {town}, I came across {business_name}, but I couldn't find a website for you.\n\n"
        "A simple website lets new customers see your services, opening hours and location, "
        "and contact you straight from Google. Many people check online before choosing a "
        "local business.\n\n"
        "I build clean, mobile-friendly websites for small local businesses, usually ready in "
        "about {days} days. I'd be happy to create a free one-page mockup for {business_name} "
        "so you can see what it could look like, with no obligation.\n\n"
        "If you're interested, just reply \"yes\" and I'll send it over. If you'd rather not "
        "hear from me, let me know and I won't contact you again.\n\n"
        "Kind regards,\n{signature}"
    ),
    "followup": (
        "{greeting} just following up on my message about a free website mockup for "
        "{business_name}. Happy to send it over if you're interested. No worries at all if "
        "not, and just say STOP and I won't message you again!"
    ),
    "whatsapp": (
        "{greeting} I'm {sender_name}, a web designer. I noticed {business_name} doesn't have a "
        "website yet, so customers searching for {business_type} in {town} can't see your "
        "services or contact you online. Would you like me to send a free 1-page mockup? "
        "No obligation. Just reply YES (or STOP and I won't message you again)."
    ),
}


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def load_settings() -> dict[str, str]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            settings.update({k: str(v) for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict[str, str]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Phone numbers (any country, via libphonenumber)
# ---------------------------------------------------------------------------

_TYPE_NAMES = {
    PhoneNumberType.MOBILE: "Mobile",
    PhoneNumberType.FIXED_LINE: "Landline",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "Mobile/Landline",   # e.g. US/Canada: can't tell
}
_WHATSAPP_TYPES = ("Mobile", "Mobile/Landline")


def _parse(intl: str, local: str, default_cc: str):
    """phonenumbers object for a valid number, None if empty or invalid."""
    raw = (intl or local or "").strip()
    if not raw:
        return None
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    region = None
    if default_cc.isdigit():
        region = phonenumbers.region_code_for_country_code(int(default_cc))
        region = None if region in (None, "ZZ") else region
    try:
        number = phonenumbers.parse(raw, region)
    except NumberParseException:
        return None
    return number if phonenumbers.is_valid_number(number) else None


def phone_type(intl: str, local: str, default_cc: str = "44") -> str:
    """'Mobile' | 'Landline' | 'Mobile/Landline' | 'Other' (toll-free, VoIP…) | 'Unknown' | '' (no number)."""
    if not (intl or local or "").strip():
        return ""
    number = _parse(intl, local, default_cc)
    if number is None:
        return "Unknown"
    return _TYPE_NAMES.get(phonenumbers.number_type(number), "Other")


def whatsapp_digits(intl: str, local: str, default_cc: str = "44") -> str:
    """Digits (country code included) for wa.me — only for numbers that can have WhatsApp."""
    number = _parse(intl, local, default_cc)
    if number is None or _TYPE_NAMES.get(phonenumbers.number_type(number)) not in _WHATSAPP_TYPES:
        return ""
    return phonenumbers.format_number(number, PhoneNumberFormat.E164).lstrip("+")


# ---------------------------------------------------------------------------
# Local time / best time to call
# ---------------------------------------------------------------------------

_PREFERRED_ZONES = ("Europe/London", "Australia/Sydney", "America/New_York", "America/Toronto")
_SUN_THU_WEEK = {"SA", "KW", "QA", "BH", "OM"}        # Sunday-Thursday working week
CALL_FROM_HOUR, CALL_TO_HOUR = 9, 18


def local_time_info(intl: str, local: str, default_cc: str = "44", now_utc: datetime | None = None) -> tuple[str, str]:
    """('Tue 14:35', '✅ Good time to call' | '💤 Outside business hours'), or ('', '') if unknown."""
    number = _parse(intl, local, default_cc)
    if number is None:
        return "", ""
    zones = [z for z in pn_timezone.time_zones_for_number(number) if z != "Etc/Unknown"]
    pick = next((z for z in _PREFERRED_ZONES if z in zones), zones[0] if zones else "")
    try:
        zone = ZoneInfo(pick) if pick else None
    except ZoneInfoNotFoundError:
        zone = None
    if zone is None:
        return "", ""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(zone)
    workdays = {6, 0, 1, 2, 3} if phonenumbers.region_code_for_number(number) in _SUN_THU_WEEK else {0, 1, 2, 3, 4}
    open_now = now.weekday() in workdays and CALL_FROM_HOUR <= now.hour < CALL_TO_HOUR
    return now.strftime("%a %H:%M"), ("✅ Good time to call" if open_now else "💤 Outside business hours")


def best_channel(ptype: str, has_email: bool) -> str:
    if ptype in _WHATSAPP_TYPES:
        return "WhatsApp / Call"
    if ptype:       # landline, toll-free, or a number we couldn't classify
        return "Call + Email" if has_email else "Call"
    return "Email" if has_email else "Find contact online"


# ---------------------------------------------------------------------------
# Message text
# ---------------------------------------------------------------------------

_NAME_HINTS = (
    ("barber", "barbers"), ("nail", "nail salons"), ("beauty", "beauty salons"),
    ("hair", "hair salons"), ("salon", "salons"), ("plumb", "plumbers"),
    ("electric", "electricians"), ("roof", "roofers"), ("clean", "cleaning companies"),
    ("builder", "builders"), ("florist", "florists"), ("flower", "florists"),
    ("cafe", "cafes"), ("coffee", "cafes"), ("restaurant", "restaurants"),
    ("takeaway", "takeaways"), ("pizza", "takeaways"), ("garage", "garages"),
    ("dental", "dentists"), ("dentist", "dentists"), ("gym", "gyms"),
    ("fitness", "gyms"), ("account", "accountants"), ("solicitor", "solicitors"),
)
_CATEGORY_HINTS = (
    ("hairdresser", "hair salons"), ("beauty", "beauty salons"), ("fast_food", "takeaways"),
    ("restaurant", "restaurants"), ("cafe", "cafes"), ("catering.bar", "bars and pubs"),
    ("cleaning", "cleaning companies"), ("estate_agent", "estate agents"),
    ("dentist", "dentists"), ("fitness", "gyms"), ("lawyer", "solicitors"),
    ("clothing", "clothes shops"), ("hotel", "hotels"), ("pet", "pet shops"),
    ("florist", "florists"), ("chemist", "pharmacies"), ("vehicle", "garages"),
)


def business_type(name: str, types: str, fallback: str = "") -> str:
    """Plural noun for the message, guessed from the name, then types, then the search keyword."""
    text = f"{name} {types}".lower()
    for hint, noun in _NAME_HINTS:
        if hint in text:
            return noun
    for hint, noun in _CATEGORY_HINTS:
        if hint in types.lower():
            return noun
    return fallback.strip() or "local businesses"


def render(template: str, ctx: dict[str, str]) -> str:
    """Fill {placeholders}; leave unknown ones (and stray braces) untouched."""
    return re.sub(r"\{(\w+)\}", lambda m: ctx.get(m.group(1), m.group(0)), template)


def maps_link(name: str, address: str, town: str, place_id: str = "", source: str = "") -> str:
    """Google Maps link that opens the business (exact listing for Google Places leads)."""
    where = address or town
    query = urllib.parse.quote_plus(f"{name} {where}".strip())
    url = f"https://www.google.com/maps/search/?api=1&query={query}"
    if source.startswith("Google") and place_id:
        url += f"&query_place_id={urllib.parse.quote(place_id)}"
    return url


def chatgpt_prompt(lead: dict, settings: dict[str, str]) -> str:
    """A ready-to-paste ChatGPT prompt for one lead's first cold email (only real facts go in)."""
    status = str(lead.get("Website Status", ""))
    link = str(lead.get("Social Link", "") or "").strip()
    if status == "NO WEBSITE":
        situation = "has no website that I could find"
    elif status == "SOCIAL ONLY":
        situation = "only has a social media page" + (f" ({link})" if link else "") + ", no real website"
    else:
        situation = "has a website that looks outdated: [say what is wrong]"
    town = str(lead.get("Town", "") or "")
    noun = business_type(str(lead.get("Name", "")), str(lead.get("Types", "") or ""), "local business")
    first = str(lead.get("Director Name", "") or "").split()[0] if str(lead.get("Director Name", "") or "").strip() else "unknown"
    return f"""You are a friendly, professional freelance web designer writing a first cold email to a small local business owner. Write ONE email.

ABOUT ME
- Name: {settings['sender_name'] or '[your name]'}
- Business/brand: {settings['sender_business'] or 'freelance web designer'}
- What I offer: simple, mobile-friendly websites for small local businesses, ready in about {settings['days'] or '7'} days
- Portfolio link: {settings['portfolio'] or '[link or "none yet"]'}
- Contact: {settings['sender_phone'] or '[email / WhatsApp]'}

ABOUT THE LEAD (use only these facts, do not invent anything else)
- Business name: {lead.get('Name', '')}
- Type: {noun}
- Town and country: {town}
- Owner first name (if known): {first}
- Their situation: {situation}
- One real detail I noticed (Google Maps / Facebook): [add one true detail]

OFFER
- A free one-page sample website mockup for their business, no obligation.

RULES
- 90 to 120 words. Short paragraphs. Plain, warm, human English. No hype, no emojis, no exclamation marks.
- Start with the owner's first name if known, otherwise "Hi {lead.get('Name', '[Business]')} team,".
- Mention the real detail above and why a website helps THEM (customers searching "{noun} in {town}" cannot see services, hours or contact details in one place).
- Do NOT invent reviews, statistics, awards, prices, years in business, or claim I worked with them or their competitors.
- Do NOT use "I hope this email finds you well".
- End with one easy question (reply "yes" and I will send the sample), then this opt-out line: "If you'd rather not hear from me, just let me know and I won't contact you again."
- Sign off with my name, brand and contact.

OUTPUT
3 subject line options (under 50 characters, no clickbait), then the email body. Nothing else."""


def _signature(s: dict[str, str]) -> str:
    lines = [s["sender_name"] or "[Your Name]", s["sender_business"], s["sender_phone"], s["portfolio"]]
    return "\n".join(line for line in lines if line)


def _col(df: pd.DataFrame, name: str) -> list[str]:
    if name not in df.columns:
        return [""] * len(df)
    return df[name].fillna("").astype(str).tolist()


def add_outreach(
    df: pd.DataFrame, settings: dict[str, str], search_label: str = "", default_cc: str = "44"
) -> pd.DataFrame:
    """
    Return a copy of `df` with: Best Channel, Email Subject, Email Body, WhatsApp Message,
    WhatsApp Link (message pre-filled), Mail Link (mailto, only if Manual Email is set),
    plus Follow-up Message / Follow-up WhatsApp Link / Follow-up Mail Link and a Google Maps link.
    """
    out = df.copy()
    names, towns, types = _col(df, "Name"), _col(df, "Town"), _col(df, "Types")
    directors, emails = _col(df, "Director Name"), _col(df, "Manual Email")
    wa_digits, ptypes = _col(df, "WhatsApp Digits"), _col(df, "Phone Type")
    addresses, place_ids, sources = _col(df, "Address"), _col(df, "place_id"), _col(df, "Source")
    intl_phones, local_phones = _col(df, "Intl Phone"), _col(df, "Phone")

    base = {
        "sender_name": settings["sender_name"] or "[Your Name]",
        "from_business": f" from {settings['sender_business']}" if settings["sender_business"] else "",
        "signature": _signature(settings),
        "days": settings["days"] or "7",
    }
    subjects, bodies, wa_msgs, wa_links, mail_links, channels = [], [], [], [], [], []
    fu_msgs, fu_wa, fu_mail = [], [], []
    for name, town, typ, director, email, digits, ptype in zip(
        names, towns, types, directors, emails, wa_digits, ptypes
    ):
        first = director.split()[0] if director.strip() else ""
        ctx = {
            **base,
            "business_name": name,
            "town": town or "your area",
            "business_type": business_type(name, typ, search_label),
            "first_name": first,
            "greeting": f"Hi {first}," if first else f"Hi {name} team,",
        }
        subject = render(settings["subject"], ctx)
        body = render(settings["email_body"], ctx)
        wa_msg = render(settings["whatsapp"], ctx)
        subjects.append(subject)
        bodies.append(body)
        wa_msgs.append(wa_msg)
        wa_links.append(f"https://wa.me/{digits}?text={urllib.parse.quote(wa_msg)}" if digits else "")
        mail_links.append(
            f"mailto:{email}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
            if "@" in email else ""
        )
        channels.append(best_channel(ptype, "@" in email))

        fu_msg = render(settings["followup"], ctx)
        fu_subject = f"Following up: website for {name}"
        fu_msgs.append(fu_msg)
        fu_wa.append(f"https://wa.me/{digits}?text={urllib.parse.quote(fu_msg)}" if digits else "")
        fu_mail.append(
            f"mailto:{email}?subject={urllib.parse.quote(fu_subject)}"
            f"&body={urllib.parse.quote(fu_msg + chr(10) * 2 + 'Kind regards,' + chr(10) + base['signature'])}"
            if "@" in email else ""
        )

    times = [local_time_info(i, p, default_cc) for i, p in zip(intl_phones, local_phones)]
    out["Local Time"] = [t[0] for t in times]
    out["Call Window"] = [t[1] for t in times]
    out["Google Maps"] = [
        maps_link(n, a, t, pid, src) if n else ""
        for n, a, t, pid, src in zip(names, addresses, towns, place_ids, sources)
    ]
    out["Best Channel"] = channels
    out["Email Subject"] = subjects
    out["Email Body"] = bodies
    out["WhatsApp Message"] = wa_msgs
    out["WhatsApp Link"] = wa_links
    out["Mail Link"] = mail_links
    out["Follow-up Message"] = fu_msgs
    out["Follow-up WhatsApp Link"] = fu_wa
    out["Follow-up Mail Link"] = fu_mail
    return out
