"""
mockup.py
---------
Builds a one-page SAMPLE website for a lead, as a single self-contained HTML file
(no external fonts/scripts), to send as a "free mockup".

Honesty rules, so the mockup never misleads the business owner:
  * only real data is used as fact: name, town, address, phone;
  * services / hours / prices are clearly marked as examples to be replaced;
  * no invented reviews, years in business, awards or prices;
  * a "SAMPLE DESIGN" ribbon is always shown.
"""

from __future__ import annotations

import html
import io
import re
import urllib.parse
import zipfile
from typing import Any

import pandas as pd

from outreach import business_type

# group -> (accent colour, dark colour, tagline, example services, call-to-action)
_GROUPS: dict[str, dict[str, Any]] = {
    "grooming": {
        "accent": "#c9a227", "dark": "#14110f",
        "tagline": "Sharp cuts. Fresh looks.",
        "services": ["Haircuts & styling", "Beard trims", "Colour & treatments", "Walk-ins welcome"],
        "cta": "Book your visit",
    },
    "trades": {
        "accent": "#e8590c", "dark": "#10243b",
        "tagline": "Reliable local service you can trust.",
        "services": ["Free, no-obligation quotes", "Emergency call-outs", "Repairs & installations", "Clean, tidy work"],
        "cta": "Get a free quote",
    },
    "food": {
        "accent": "#d9480f", "dark": "#2b1810",
        "tagline": "Good food, made fresh.",
        "services": ["Eat in", "Takeaway", "Menu & prices", "Opening hours"],
        "cta": "Order or reserve",
    },
    "professional": {
        "accent": "#1c7ed6", "dark": "#0b1f33",
        "tagline": "Clear, friendly professional advice.",
        "services": ["Free initial conversation", "Personal service", "Clear pricing", "Local and approachable"],
        "cta": "Get in touch",
    },
    "general": {
        "accent": "#0ca678", "dark": "#0f2a24",
        "tagline": "Proudly serving the local community.",
        "services": ["What we do", "Why choose us", "Opening hours", "Find us"],
        "cta": "Get in touch",
    },
}

_GROUP_BY_NOUN = (
    (("barber", "hair", "beauty", "nail", "salon"), "grooming"),
    (("plumb", "electric", "roof", "builder", "joiner", "decorat", "landscap", "clean", "garage", "taxi", "driving"), "trades"),
    (("cafe", "restaurant", "takeaway", "pub", "bar", "florist"), "food"),
    (("account", "solicitor", "dental", "dentist", "estate", "photograph"), "professional"),
)


def group_for(noun: str) -> str:
    noun = noun.lower()
    for keys, group in _GROUP_BY_NOUN:
        if any(k in noun for k in keys):
            return group
    return "general"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "business"


def render_mockup(lead: dict[str, Any], sender_name: str = "", sender_contact: str = "") -> str:
    """One self-contained HTML page for one lead (all text HTML-escaped)."""
    e = html.escape
    name = str(lead.get("Name", "") or "Your Business").strip()
    town = str(lead.get("Town", "") or "").strip()
    address = str(lead.get("Address", "") or "").strip()
    phone = str(lead.get("Phone", "") or "").strip()
    digits = re.sub(r"[^\d+]", "", phone)
    wa_digits = str(lead.get("WhatsApp Digits", "") or "").strip()
    noun = business_type(name, str(lead.get("Types", "") or ""), "local business")
    g = _GROUPS[group_for(noun)]

    maps_url = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(f"{name} {address or town}")
    buttons = []
    if digits:
        buttons.append(f'<a class="btn" href="tel:{e(digits, quote=True)}">Call {e(phone)}</a>')
    if wa_digits:
        buttons.append(f'<a class="btn ghost" href="https://wa.me/{e(wa_digits, quote=True)}">WhatsApp us</a>')
    buttons.append(f'<a class="btn ghost" href="{e(maps_url, quote=True)}">Find us</a>')

    services = "".join(f"<li>{e(s)}</li>" for s in g["services"])
    where = e(address or town or "Your address here")
    credit = e(sender_name) if sender_name else "your web designer"
    contact_line = f" · {e(sender_contact)}" if sender_contact else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(name)} — sample website design</title>
<style>
:root {{ --accent: {g['accent']}; --dark: {g['dark']}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: #1c1c1c; line-height: 1.55; }}
.ribbon {{ background: #fff3bf; color: #5f3dc4; text-align: center; font-size: 13px; padding: 8px 12px; border-bottom: 1px solid #ffe066; }}
header {{ background: var(--dark); color: #fff; padding: 72px 20px 80px; text-align: center; }}
header h1 {{ margin: 0 0 8px; font-size: clamp(30px, 6vw, 52px); letter-spacing: .5px; }}
header p {{ margin: 0 auto 28px; max-width: 560px; font-size: 19px; opacity: .85; }}
.town {{ color: var(--accent); text-transform: uppercase; letter-spacing: 3px; font-size: 13px; margin-bottom: 14px; }}
.btn {{ display: inline-block; margin: 6px; padding: 11px 24px; border: 2px solid var(--accent); border-radius: 999px; background: var(--accent); color: #fff; font-weight: 600; text-decoration: none; }}
.btn.ghost {{ background: transparent; color: #fff; }}
section {{ max-width: 920px; margin: 0 auto; padding: 56px 20px; }}
h2 {{ margin: 0 0 6px; font-size: 28px; }}
.note {{ font-size: 13px; color: #868e96; margin: 0 0 22px; }}
ul.cards {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }}
ul.cards li {{ padding: 22px 18px; border: 1px solid #e9ecef; border-radius: 14px; border-top: 4px solid var(--accent); font-weight: 600; background: #fff; }}
.contact {{ background: #f8f9fa; }}
.contact .box {{ max-width: 920px; margin: 0 auto; padding: 56px 20px; display: grid; gap: 24px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
.contact h3 {{ margin: 0 0 6px; }}
.placeholder {{ color: #868e96; font-style: italic; }}
.contact a {{ color: var(--accent); font-weight: 600; }}
header, section, .contact .box {{ overflow-wrap: anywhere; }}
footer {{ background: var(--dark); color: #adb5bd; text-align: center; padding: 22px 16px; font-size: 13px; }}
</style></head>
<body>
<div class="ribbon"><strong>SAMPLE DESIGN</strong> — a free mockup for {e(name)}. Not a live website. Text marked as example will be replaced with your real details.</div>
<header>
  <div class="town">{e(town) if town else e(noun)}</div>
  <h1>{e(name)}</h1>
  <p>{e(g['tagline'])}</p>
  {''.join(buttons[:1])}{''.join(buttons[1:])}
</header>
<section>
  <h2>What we do</h2>
  <p class="note">Example content — we'll write this with you.</p>
  <ul class="cards">{services}</ul>
</section>
<div class="contact"><div class="box">
  <div><h3>Visit us</h3><p>{where}</p><p><a href="{e(maps_url, quote=True)}">Open in Google Maps</a></p></div>
  <div><h3>Opening hours</h3><p class="placeholder">Your opening hours go here</p></div>
  <div><h3>Contact</h3><p>{e(phone) if phone else '<span class="placeholder">Your phone number here</span>'}</p><p class="placeholder">Your email address here</p></div>
</div></div>
<footer>© {e(name)} · Sample design prepared by {credit}{contact_line}</footer>
</body></html>
"""


def build_zip(leads: pd.DataFrame, sender_name: str = "", sender_contact: str = "") -> bytes:
    """ZIP of one HTML mockup per lead (file names are unique even for duplicate names)."""
    buf = io.BytesIO()
    used: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for lead in leads.to_dict("records"):
            base = slug(str(lead.get("Name", "")))
            used[base] = used.get(base, 0) + 1
            fname = f"{base}.html" if used[base] == 1 else f"{base}-{used[base]}.html"
            zf.writestr(fname, render_mockup(lead, sender_name, sender_contact))
    return buf.getvalue()
