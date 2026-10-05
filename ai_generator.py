"""
ai_generator.py
---------------
Writes a custom one-page SAMPLE website for a lead with a free LLM API.

Works with any OpenAI-compatible endpoint; three free options are preconfigured:
  * Google Gemini (AI Studio key, free tier)      https://aistudio.google.com/apikey
  * Groq (no card, generous free tier)            https://console.groq.com/keys
  * OpenRouter (models whose id ends in ":free")  https://openrouter.ai/keys

Free-tier limits change often — check the provider's console. A page costs roughly 3-6k
output tokens, so use it for leads that replied, not for every lead.

Safety / honesty:
  * the model only receives REAL facts (name, town, address, phone) and is told not to invent
    reviews, prices, years, awards, hours or emails;
  * its HTML is sanitised (no scripts, no external resources, no forms posting elsewhere);
  * a "SAMPLE DESIGN" ribbon is always present;
  * suspicious claims in the result are listed as warnings for you to check.
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse
from typing import Any

import requests

from outreach import business_type, maps_link

PROVIDERS: dict[str, dict[str, str]] = {
    "Google Gemini (free tier)": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env": "GEMINI_API_KEY", "model": "gemini-2.5-flash",
        "signup": "https://aistudio.google.com/apikey",
    },
    "Groq (free, no card)": {
        "base": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b",
        "signup": "https://console.groq.com/keys",
    },
    "OpenRouter (free models)": {
        "base": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY", "model": "openai/gpt-oss-120b:free",
        "signup": "https://openrouter.ai/keys",
    },
}

STYLES: dict[str, str] = {
    "Modern & clean": "modern, airy, lots of white space, one confident accent colour, rounded cards",
    "Bold & dark": "dark background, high contrast, one vivid accent colour, large confident headings",
    "Warm & friendly": "warm colours, soft rounded shapes, friendly and approachable, easy to read",
    "Elegant & premium": "elegant, refined, subtle gold or deep accent colour, generous spacing, serif headings",
}

SYSTEM_PROMPT = (
    "You are a senior web designer. You write one complete, beautiful, mobile-first one-page website "
    "as a single self-contained HTML5 file. You never invent facts about a business."
)


class AIError(RuntimeError):
    """Readable error for the UI."""


def build_prompt(lead: dict[str, Any], sender_name: str, style: str, extra: str = "") -> str:
    name = str(lead.get("Name", "") or "Your Business").strip()
    town = str(lead.get("Town", "") or "").strip()
    address = str(lead.get("Address", "") or "").strip()
    phone = str(lead.get("Phone", "") or "").strip()
    digits = re.sub(r"[^\d+]", "", phone)
    wa = str(lead.get("WhatsApp Digits", "") or "").strip()
    noun = business_type(name, str(lead.get("Types", "") or ""), "local business")
    maps = maps_link(name, address, town)
    links = [f"- Map link: {maps}"]
    if digits:
        links.insert(0, f"- Call link: tel:{digits}")
    if wa:
        links.insert(1 if digits else 0, f"- WhatsApp link: https://wa.me/{wa}")
    style_text = STYLES.get(style, STYLES["Modern & clean"])
    return f"""Design a sample one-page website for this local business.

REAL FACTS (the ONLY facts you may state as true)
- Business name: {name}
- Type of business: {noun}
- Town: {town or 'unknown'}
- Address: {address or 'unknown'}
- Phone: {phone or 'unknown'}
{chr(10).join(links)}

DESIGN
- Style: {style_text}.
- Sections, in this order: sticky top bar (business name + Call button); hero; "What we do" (6 service cards); "Why choose us" (3 generic example points, marked as examples); short "About"; "Visit us" (address + map link); "Opening hours"; a strong call-to-action band; footer.
- Look like a finished, premium agency-built website, never a wireframe:
  * hero: full-width, rich layered CSS gradient (radial + linear), a large decorative emoji or CSS-shape motif, a big headline (clamp(2.2rem, 6vw, 4rem), tight line-height, bold), a one-line tagline, a primary and a secondary button;
  * type: system font stack for body, an elegant stack for headings, a clear scale, max line length ~65ch;
  * layout: centred container (max-width 1100px), 96px section padding on desktop, CSS grid cards, consistent 16-24px radius, soft layered shadows, subtle borders;
  * colour: a 3-colour palette suited to a {noun} (one accent, one dark, one soft background), alternate section backgrounds, WCAG-contrast text;
  * polish: hover lift on cards and buttons (CSS transitions only), pill badges, thin dividers, smooth gradients, a decorative section label above each heading.
- Mobile-first and responsive (single column under 700px), accessible (real headings, focus states).

HARD RULES
- Output ONLY the HTML document, starting with <!doctype html>. No explanations, no markdown fences.
- All CSS inline in one <style> block. NO JavaScript, NO external fonts/images/scripts/stylesheets, NO <img> tags, NO forms. Use CSS shapes, gradients and emoji for decoration.
- Do NOT invent: reviews, testimonials, star ratings, prices, years in business, awards, staff names, opening hours, email addresses, phone numbers, statistics or brand claims.
- Services: give each of the 6 cards a different, typical service name for a {noun} (generic names only, with a one-line neutral description and a fitting emoji) and add a small muted "example" tag on every card. No prices.
- About and opening hours: write short, clearly marked example text, e.g. "Example text — your story goes here" and "Your opening hours go here", in a muted italic style. Never state specific facts about the business beyond the REAL FACTS.
- Only link to the call / WhatsApp / map links given above.
- Show a thin banner at the very top: "SAMPLE DESIGN — a free mockup for {name}. Not a live website."
- Footer: "Sample design prepared by {sender_name or 'your web designer'}".
{('- Extra wishes from me: ' + extra.strip()) if extra.strip() else ''}"""


def website_prompt(lead: dict[str, Any], sender_name: str = "", style: str = "Modern & clean", extra: str = "") -> str:
    """A complete brief to paste into ChatGPT / Claude / Gemini for a hand-finished, professional page.

    Unlike build_prompt (strict, no JS / no images, for the built-in generator) this one lets the
    chat model use Google Fonts, small JS (mobile menu) and photo placeholders — you review the result
    yourself before sending it. The honesty rules about facts stay.
    """
    name = str(lead.get("Name", "") or "Your Business").strip()
    town = str(lead.get("Town", "") or "").strip()
    address = str(lead.get("Address", "") or "").strip()
    phone = str(lead.get("Phone", "") or "").strip()
    digits = re.sub(r"[^\d+]", "", phone)
    wa = str(lead.get("WhatsApp Digits", "") or "").strip()
    noun = business_type(name, str(lead.get("Types", "") or ""), "local business")
    maps = maps_link(name, address, town)
    style_text = STYLES.get(style, STYLES["Modern & clean"])
    contact = [f"- Google Maps link: {maps}"]
    if digits:
        contact.insert(0, f"- Call link: tel:{digits}")
    if wa:
        contact.insert(1 if digits else 0, f"- WhatsApp link: https://wa.me/{wa}")
    return f"""You are an award-winning web designer and front-end developer. Build a complete, professional, conversion-focused one-page website for a local business (type: {noun}). Deliver a single self-contained index.html file (HTML + CSS + a little vanilla JS). Output only the code in one code block.

BUSINESS FACTS (the only facts you may state as true)
- Business name: {name}
- Type: {noun}
- Town: {town or 'unknown'}
- Address: {address or 'unknown'}
- Phone: {phone or 'unknown'}
{chr(10).join(contact)}

DESIGN DIRECTION
- Style: {style_text}.
- It must look like a premium agency-built site: confident, modern, polished. Think Stripe / Linear level craft, adapted to this kind of business.
- Palette: pick a refined 3-colour palette (one accent, one deep neutral, one soft background) that suits this kind of business. Define colours, spacing and radii as CSS variables.
- Typography: load one heading font and one body font from Google Fonts (e.g. Plus Jakarta Sans, Inter, DM Serif Display, Playfair Display, Poppins — choose what fits), a clear type scale, tight heading line-height, comfortable body line-height.
- Layout: container max-width 1140px, generous section padding (80-120px desktop), CSS grid/flex, consistent 16-24px radius, soft layered shadows, subtle borders.
- Hero: full-width with a rich layered gradient, a large headline, a short tagline, primary + secondary buttons (Call / WhatsApp / Get directions), and a visual panel built with CSS shapes or a clearly labelled photo placeholder.
- Motion: gentle hover lifts, smooth transitions, fade-in on scroll (IntersectionObserver), respect prefers-reduced-motion.
- Images: no stock photo URLs. Use elegant gradient / pattern blocks labelled like "[PHOTO: front of shop]" so the owner can drop real photos in later.

SECTIONS (in this order)
1. Sticky header: business name, anchor links, Call button; mobile hamburger menu (vanilla JS).
2. Hero.
3. Services: 6 cards with a different, typical service for this kind of business, an inline SVG icon and a one-line description. Mark each as an example service.
4. Why choose us: 3 generic example points (clearly marked as examples).
5. About: short example text.
6. How it works / booking steps: 3 steps (call → confirm → visit).
7. Visit us: address, map link, opening-hours block.
8. Contact: big Call and WhatsApp buttons (a mailto link only if an email is given).
9. Final call-to-action band and footer.

QUALITY CHECKLIST
- Mobile-first, fully responsive, 100/100 Lighthouse-style accessibility (semantic tags, alt/aria labels, visible focus, WCAG AA contrast).
- Add a proper <title>, meta description and Open Graph tags for {name} in {town or 'its town'}.
- Add LocalBusiness JSON-LD using ONLY the facts above.
- Clean, commented, well-structured code.

HONESTY RULES
- Do NOT invent: reviews, testimonials, star ratings, prices, years in business, awards, staff names, opening hours, email addresses, phone numbers, statistics or claims. Where a detail is unknown, use clearly marked placeholder text such as "Your opening hours go here" in a muted style.
- Add a slim top banner: "SAMPLE DESIGN — a free mockup for {name}. Not a live website."
- Footer: "Sample design prepared by {sender_name or 'your web designer'}".
{('EXTRA WISHES: ' + extra.strip()) if extra.strip() else ''}"""


def _request(provider: str, api_key: str, model: str, prompt: str, timeout: int) -> str:
    cfg = PROVIDERS[provider]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if "openrouter" in cfg["base"]:
        headers.update({"HTTP-Referer": "http://localhost", "X-Title": "Data Scalper"})
    body = {
        "model": model or cfg["model"],
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 7000,
    }
    try:
        resp = requests.post(cfg["base"] + "/chat/completions", headers=headers, json=body, timeout=timeout)
    except requests.RequestException as e:
        raise AIError(f"Could not reach {provider}: {e}") from e

    if resp.status_code in (401, 403):
        raise AIError(f"{provider} rejected the API key ({resp.status_code}). Check the key.")
    if resp.status_code == 429:
        raise AIError(
            f"{provider}: free-tier limit reached (too many requests or tokens today). "
            "Wait a little, pick another provider or another model."
        )
    if resp.status_code >= 400:
        try:
            msg = resp.json()
            msg = msg.get("error", msg)
            msg = msg.get("message", msg) if isinstance(msg, dict) else msg
        except ValueError:
            msg = resp.text[:200]
        raise AIError(f"{provider} error {resp.status_code}: {str(msg)[:300]} (check the model name)")
    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise AIError(f"{provider} returned an unexpected answer.") from e
    if not text or not text.strip():
        raise AIError(f"{provider} returned an empty answer. Try again or use another model.")
    return text


def extract_html(text: str) -> tuple[str, list[str]]:
    """Pull the HTML document out of the model's answer (fences / chatter removed)."""
    warnings: list[str] = []
    fenced = re.search(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    candidate = fenced.group(1) if fenced and "<" in fenced.group(1) else text
    start = re.search(r"<!doctype html|<html", candidate, re.I)
    if not start:
        raise AIError("The model did not return a web page. Try again or use another model.")
    page = candidate[start.start():]
    end = re.search(r"</html\s*>", page, re.I)
    if end:
        page = page[: end.end()]
    else:
        page += "\n</body></html>"
        warnings.append("The model's answer was cut off (token limit); the page was closed automatically. Check the bottom.")
    return page.strip(), warnings


_REMOVE_BLOCKS = re.compile(r"<(script|iframe|object|embed|applet|noscript)\b.*?</\1\s*>", re.I | re.S)
_REMOVE_TAGS = re.compile(r"<(script|iframe|object|embed|applet|link|base|form|input|button\s+type=['\"]?submit)\b[^>]*>|</form\s*>", re.I)
_EXT_IMG = re.compile(r"<img\b[^>]*>", re.I)


def sanitize_html(page: str) -> str:
    """Remove anything active or external: scripts, frames, event handlers, remote resources."""
    page = _REMOVE_BLOCKS.sub("", page)
    page = _REMOVE_TAGS.sub("", page)
    page = _EXT_IMG.sub("", page)
    page = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", page, flags=re.I)
    page = re.sub(r"javascript\s*:", "#", page, flags=re.I)
    page = re.sub(r"<meta[^>]+http-equiv\s*=\s*['\"]?refresh[^>]*>", "", page, flags=re.I)
    page = re.sub(r"@import[^;]+;", "", page, flags=re.I)
    page = re.sub(r"url\(\s*['\"]?(?:https?:)?//[^)]*\)", "none", page, flags=re.I)
    if "SAMPLE DESIGN" not in page:
        ribbon = (
            '<div style="background:#fff3bf;color:#5f3dc4;text-align:center;font:600 13px system-ui;'
            'padding:8px 12px">SAMPLE DESIGN — a free mockup. Not a live website.</div>'
        )
        if re.search(r"<body\b[^>]*>", page, re.I):
            page = re.sub(r"(<body\b[^>]*>)", r"\1" + ribbon, page, count=1, flags=re.I)
        else:
            page = ribbon + page
    return page


_CLAIM_PATTERNS = (
    (r"\b\d+\+?\s*(?:years?|yrs)\b", "a number of years in business"),
    (r"\bsince\s+(?:19|20)\d\d\b", "a founding year"),
    (r"[★⭐]|\b[1-5](?:\.\d)?\s*/\s*5\b|\b(?:five|5)[- ]star", "star ratings"),
    (r"\bawards?\b|\baward-winning\b", "awards"),
    (r"\btestimonials?\b|\bwhat our (?:clients|customers) say\b", "testimonials"),
    (r"\b\d{2,}\+?\s*(?:happy|satisfied)\s+(?:clients|customers)\b", "customer counts"),
    (r"[$£€]\s?\d", "prices"),
    (r"\b\d{1,3}\s?%", "percentages"),
)


def claim_warnings(page: str, lead: dict[str, Any]) -> list[str]:
    """Things in the visible text that are not in the real facts and must be checked."""
    text = html_lib.unescape(re.sub(r"<style\b.*?</style>|<[^>]+>", " ", page, flags=re.S | re.I))
    out = []
    for pattern, label in _CLAIM_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            out.append(f"Mentions {label} (“{m.group(0).strip()}”) — remove it unless it is true.")
    real_digits = re.sub(r"\D", "", str(lead.get("Phone", "") or ""))
    for number in re.findall(r"\+?\d[\d\s().-]{7,}\d", text):
        digits = re.sub(r"\D", "", number)
        if real_digits and (digits.endswith(real_digits[-8:]) or real_digits.endswith(digits[-8:])):
            continue
        out.append(f"Shows a phone-like number “{number.strip()}” that is not the lead's — remove it.")
        break
    known_email = str(lead.get("Email", "") or lead.get("Manual Email", "") or "").lower()
    for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        email = email.rstrip(".,;:")
        if email.lower() != known_email:
            out.append(f"Shows the email “{email}” which is not from the lead's data — remove it.")
            break
    return out


def generate_site(
    lead: dict[str, Any],
    *,
    provider: str,
    api_key: str,
    model: str = "",
    style: str = "Modern & clean",
    extra: str = "",
    sender_name: str = "",
    timeout: int = 150,
) -> tuple[str, list[str]]:
    """Returns (sanitised html, warnings). Raises AIError with a readable message."""
    if provider not in PROVIDERS:
        raise AIError("Unknown provider.")
    if not api_key.strip():
        raise AIError(f"Add your {provider} API key first.")
    raw = _request(provider, api_key.strip(), model.strip(), build_prompt(lead, sender_name, style, extra), timeout)
    page, warnings = extract_html(raw)
    page = sanitize_html(page)
    warnings += claim_warnings(page, lead)
    return page, warnings
