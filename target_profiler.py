"""
Target profiler — reads the user's dossier and works out WHO to email.

Given the dossier text, the AI returns:
  - An Ideal Customer Profile (industry, sub-categories, company size, region)
  - The pain points the user's offer solves (for personalisation)
  - Competitor / social-proof examples to reference
  - A set of Google search queries Apify can run to FIND those brands

This replaces the old fixed MARKET_CONFIG queries with queries tailored to
whatever the user actually sells. Reuses the OpenAI key already in Settings.
"""
import json

PROFILE_PROMPT = """You are a B2B lead-generation strategist. Read this freelancer/agency
dossier and work out exactly which businesses they should cold-email to win clients.

DOSSIER:
{dossier}

Return a STRICT JSON object (no markdown, no commentary) with these keys:

{{
  "ideal_customer": {{
    "who": "one sentence describing the ideal client to email",
    "industries": ["list", "of", "industries/categories", "to", "target"],
    "company_size": "the size/revenue band that fits best",
    "region": "primary geography (e.g. India, Kerala, USA, UK, Global)",
    "decision_maker": "the job title to address (Founder, Marketing Head, etc.)"
  }},
  "pain_points": [
    "3-5 specific problems the dossier's offer solves, phrased as the client would feel them"
  ],
  "competitor_examples": [
    "1-3 types of brands or named brands to use as social proof / FOMO references"
  ],
  "search_queries": [
    "8-12 Google search queries that surface the OFFICIAL WEBSITES of the ACTUAL TARGET CLIENTS above — the businesses that would BUY this service (their own brand site / online store). NOT agencies, NOT other service providers, NOT SaaS/software tools, NOT directories or listicles. End EVERY query with these negative operators verbatim: -agency -\"marketing agency\" -services -consulting -saas -software -hiring -jobs -site:indiamart.com -site:justdial.com -site:linkedin.com -site:facebook.com -site:amazon.in -site:rocketreach.co -site:zoominfo.com -wikipedia. Include words like \"official\", \"shop\", \"store\", \"about us\", the specific product category, and the region. Vary the angle (category terms, 'buy <product> online', 'shop now', 'powered by Shopify')."
  ],
  "audit": {{
    "auditable_online": true,
    "audit_focus": "what publicly-visible thing to check on the prospect (e.g. their Instagram/social presence, website content quality, blog/SEO). Phrase as the service area.",
    "reason": "one line on why it is or is not publicly visible"
  }}
}}

Rules:
- Base everything on the dossier — do not invent an unrelated audience.
- search_queries must be realistic Google queries (include words like
  "founder", "contact", "about us", "email", the industry, and the region).
- audit.auditable_online = true ONLY if the offer is about something visible on
  the public web (social media management, content/copywriting, SEO, web design,
  branding, ads). Set it FALSE for offers that are NOT publicly visible
  (virtual assistant, inbox/calendar management, bookkeeping, data entry,
  customer support, back-office) — there is nothing online to audit for those.
- Output ONLY the JSON object."""


def _call_ai(prompt, provider, api_key):
    if provider == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=900,
            response_format={"type": "json_object"},
        )
        return r.choices[0].message.content.strip()
    elif provider == "claude":
        import anthropic
        r = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text.strip()
    raise ValueError(f"Unknown provider: {provider}")


def _coerce_json(text):
    """Best-effort parse of an AI JSON response."""
    text = text.strip()
    # strip ```json fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    # grab the outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


def build_profile(dossier, provider="openai", api_key=None):
    """
    Build the ideal-customer profile + search queries from the dossier.
    Returns the parsed dict, or a safe fallback on failure.
    """
    fallback = {
        "ideal_customer": {
            "who": "D2C brand founders with underperforming marketing",
            "industries": ["Skincare", "Fashion", "Food & Beverage", "Wellness"],
            "company_size": "small to mid-size D2C brands",
            "region": "India",
            "decision_maker": "Founder / Marketing Head",
        },
        "pain_points": [
            "marketing not converting despite good products",
            "no consistent content or social strategy",
            "spending on ads with falling returns",
        ],
        "competitor_examples": ["similar D2C brands in the same category"],
        "search_queries": [
            "Indian D2C brand founder contact about us skincare OR fashion OR food",
            "\"made in India\" D2C brand Shopify store founder email contact",
            "Indian D2C startup our story founder website contact",
            "Indian small D2C brand founder email skincare OR wellness OR food",
        ],
        "audit": {
            "auditable_online": True,
            "audit_focus": "their website content and social media presence",
            "reason": "marketing/content presence is publicly visible",
        },
        "_fallback": True,
    }

    if not api_key or not dossier:
        return fallback

    try:
        raw = _call_ai(PROFILE_PROMPT.format(dossier=dossier), provider, api_key)
        data = _coerce_json(raw)
        # minimal validation
        if not data.get("search_queries"):
            data["search_queries"] = fallback["search_queries"]
        data.setdefault("ideal_customer", fallback["ideal_customer"])
        data.setdefault("pain_points", fallback["pain_points"])
        data.setdefault("competitor_examples", fallback["competitor_examples"])
        data.setdefault("audit", fallback["audit"])
        data["_fallback"] = False
        return data
    except Exception as e:
        print(f"[target_profiler] {e}")
        fallback["_error"] = str(e)
        return fallback
