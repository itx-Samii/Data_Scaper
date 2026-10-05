# Data Scalper

Finds local businesses that have **no real website** (or only a Facebook page), anywhere in the
world, and helps you contact them: phone type, local time, ready-to-send email / WhatsApp
messages, a free sample-website mockup, follow-up reminders and a client tracker.

## Start
1. First time only: double-click **Install requirements.bat**.
2. Double-click **Start Data Scalper.bat** → the app opens at <http://localhost:8501>.
   (Or run `python -m streamlit run app.py`.)

## API keys (all optional, put them in `.env`)
| Key | For | Cost |
|---|---|---|
| *(none)* | **Overture Maps** (default, worldwide, phone + email + Facebook) | free |
| `GEOAPIFY_API_KEY` | Geoapify | free tier |
| `COMPANIES_HOUSE_API_KEY` | new UK companies + directors | free |
| `GOOGLE_PLACES_API_KEY` | Google Places (ratings) | free quota, then paid — set a quota cap first |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` | **AI website generator** (use any one) | free tiers (limits change — check the provider console) |

Copy `.env.example` to `.env` and fill in what you use. Never share `.env`.

## Daily workflow
1. **Search card (top of the page)** → pick the data source (*Overture Maps* is free), type a **Keyword**
   and/or choose **Categories**, pick the **Target country**, a city (several: `Leeds; Bradford`) → **Search**.
   Filters (radius, max results, skip chains…) are under **Search options**.
2. **🎯 Leads to contact** tab → **1 · Pick a lead**: click a row in the table (sorted by score, ✅ = good time
   to call). **2 · Contact them**: one card with buttons for WhatsApp / Call / Email / Map / Google / Facebook.
   Open the **Map** and **Google** buttons first to confirm the business really has no website.
   Use **Prev / Next** to move through the list.
3. Inside the card:
   * **💬 Messages** – email + WhatsApp text, ready to copy.
   * **🎨 Sample website** – instant template mockup (download / ZIP of all) and the **AI-designed page**
     (Groq / Gemini / OpenRouter, free tiers; best for leads who replied).
   * **🧠 Prompts for ChatGPT / Claude** – a full *professional website prompt* with this lead's real facts
     (paste it into ChatGPT / Claude for a polished page) and the email prompt.
   * **📇 Details** – everything known about the lead.
4. Set the **Status** (Called / Messaged …) right in the card after you contact them.
5. **📅 Follow-ups & stats**: leads waiting for a reply (default after 4 days) with a follow-up message.
6. When someone agrees set **Won** → **💼 Clients**: package, price, paid, deadline.

The **sidebar** holds your saved leads (open / backup / delete), **Your details & message templates**
(name, brand, WhatsApp/email, portfolio link — fill in once), the Companies House CSV and the API-key status.

## Your data (back it up!)
| File | What |
|---|---|
| `leads.db` | every lead you ever found |
| `cache.json` | your edits: Contacted status, Manual Email |
| `clients.json` | won projects |
| `outreach_settings.json` | your details and templates |

Sidebar → **💾 Prepare backup (.zip)** downloads all four. To restore, copy them back into this folder.

## Good to know
- "No website" comes from open data (OpenStreetMap / Overture / Facebook) and can simply be *missing*
  data — always check with the Map / Google link before contacting.
- Phones, emails and Facebook pages are public listings and may be outdated.
- Cold-contact rules differ by country (UK/EU GDPR + PECR, Canada CASL, Australia Spam Act, US
  CAN-SPAM). Sole traders are the riskiest to email — call or WhatsApp first. Always include an
  opt-out line and stop when someone asks.
- Overture searches take ~30–50 s the first time (identical searches are cached for one hour).
