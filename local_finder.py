"""
Local finder: small businesses from Google Maps.

Why this exists: web search ranks big brands first, and the founder-only rule
throws away small shops whose owner reads info@ or a Gmail inbox. Maps lists
local businesses with a review count, which is a decent size signal (a shop
with 40 reviews is not a national chain).

Pipeline:
  1. Google Maps search per city (Apify compass~crawler-google-places)
  2. Keep small, real businesses: own website, under N reviews, not a chain
  3. Scrape their site for a published email (free, direct fetch)
  4. One AI call checks fit (own brand? small enough?) and pulls an owner
     first name when the business is named after a person
"""
import json
from concurrent.futures import ThreadPoolExecutor

import lead_finder as lf

MAPS_ACTOR = "compass~crawler-google-places"
COST_PER_PLACE = 0.005          # place + "has website" filter, USD, rough

# Website hosts that are not a business's own site (nothing to scrape, or not theirs)
NON_SITE_HOSTS = ("instagram.", "facebook.", "linktr.ee", "wa.me", "whatsapp.",
                  "grexa.site", "sites.google", "business.site", "blogspot.",
                  "youtube.", "justdial", "indiamart", "dotpe.in", "mydukaan",
                  "bit.ly", "goo.gl", "wixsite.com")

# Inboxes that never reach an owner
DEAD_INBOXES = ("accounts", "account", "billing", "hr", "careers", "jobs", "career",
                "noreply", "no-reply", "donotreply", "orders", "order", "returns",
                "privacy", "legal", "abuse", "webmaster", "postmaster")
# Shared inboxes a small-business owner usually reads, best first
OWNER_READ_INBOXES = ("founder", "owner", "hello", "hi", "info", "contact", "team",
                      "care", "support", "enquiry", "enquiries", "sales", "feedback")


def maps_search(apify_key, queries, cities, per_query=20, on_progress=None):
    """One Maps run per city, in parallel. Returns raw place dicts."""
    def run(city):
        if on_progress:
            on_progress(f"Searching Google Maps in {city}…", 0)
        try:
            items = lf._apify_run(apify_key, MAPS_ACTOR, {
                "searchStringsArray": queries,
                "locationQuery": city,
                "maxCrawledPlacesPerSearch": per_query,
                "language": "en",
                "website": "withWebsite",
            }, timeout=900)
        except Exception as e:
            print(f"[maps] {city}: {e}")
            items = []
        for it in items:
            it["_city"] = city
        return items

    with ThreadPoolExecutor(max_workers=3) as ex:
        return [p for batch in ex.map(run, cities) for p in batch]


def filter_small(places, max_reviews=300):
    """Own website, small, not a chain, not a big brand. Dedupes by domain."""
    by_domain = {}
    for p in places:
        site = p.get("website") or ""
        d = lf.extract_domain(site)
        if not d or any(h in site.lower() for h in NON_SITE_HOSTS):
            continue
        if p.get("permanentlyClosed") or p.get("temporarilyClosed"):
            continue
        by_domain.setdefault(d, []).append(p)

    out = []
    for d, ps in by_domain.items():
        # 3+ separate outlets on one website = a chain
        if len({p.get("address") for p in ps}) >= 3:
            continue
        if not lf.is_brand_domain(d):
            continue
        p = max(ps, key=lambda x: x.get("reviewsCount") or 0)
        if (p.get("reviewsCount") or 0) > max_reviews:
            continue
        out.append({
            "brand_name": (p.get("title") or "").split("|")[0].split(" - ")[0].strip()[:60]
                          or d.split(".")[0].title(),
            "website": p.get("website"),
            "domain": d,
            "phone": p.get("phone") or "",
            "reviews": p.get("reviewsCount") or 0,
            "rating": p.get("totalScore"),
            "maps_category": p.get("categoryName") or "",
            "address": p.get("address") or "",
            "city": p.get("_city") or p.get("city") or "",
            "maps_url": p.get("url") or "",
        })
    return out


def pick_contact_email(emails, domain):
    """Best inbox an owner will read. Returns (email, quality) or ("", "")."""
    good = []
    for e in emails or []:
        e = e.lower().strip(".")
        if lf._is_placeholder_email(e):
            continue
        local, _, dom = e.partition("@")
        if any(local == r or local.startswith(r + ".") for r in DEAD_INBOXES):
            continue
        good.append((local, dom, e))
    if not good:
        return "", ""

    own = [g for g in good if domain in g[1]]
    free = [g for g in good if g[1] in lf.FREE_MAIL]

    # 1. a named person or founder@ on their own domain
    for local, dom, e in own:
        if any(k in local for k in lf.CSUITE_LOCALS) or lf._looks_like_person(local):
            return e, "owner"
    # 2. a non-role address on their own domain (priya@brand.in)
    roles = tuple(lf.ROLE_LOCALS) + OWNER_READ_INBOXES
    for local, dom, e in own:
        if not any(local.startswith(r) for r in roles):
            return e, "owner"
    # 3. a Gmail-style inbox: small Indian brands often run on the owner's Gmail
    if free:
        return free[0][2], "owner_gmail"
    # 4. shared inboxes the owner reads, best first
    for r in OWNER_READ_INBOXES:
        for local, dom, e in own:
            if local == r or local.startswith(r):
                return e, "business_inbox"
    return (own[0][2], "business_inbox") if own else ("", "")


FIT_PROMPT = """You screen cold-email leads for a freelancer.

FREELANCER OFFER: {offer}
IDEAL CLIENT: {who}

For each business below decide:
- fit: true only if it is a business that sells its OWN products or designs
  (a brand, designer, maker, boutique label) and could plausibly hire this
  freelancer. false for resellers of other brands, wholesalers, distributors,
  manufacturers-for-hire, salons/clinics, agencies, marketplaces, chains.
- size: "micro" (owner-run), "small", "medium", or "large" (national chain or
  well-known brand a new freelancer would not win).
- owner_first_name: if the business is named after a person, their first name
  (e.g. "Neha Lulla Jewellery" -> "Neha", "Vinanti Manji Designer Jewellery" ->
  "Vinanti", "Doodles By Purvi" -> "Purvi"), else "".
- reason: max 12 words.

Judge from the name, site title and site description. A small skincare,
jewellery, fashion, food or decor label selling its own range is a fit even if it
also runs a shop. When unsure, set fit to true. Always fill size.

BUSINESSES (JSON):
{rows}

Return JSON: {{"results": [{{"id": 0, "fit": true, "size": "small",
"owner_first_name": "", "reason": "..."}}]}} with one entry per id."""


def fit_check(leads, profile, ai_key, provider="openai"):
    """Batch AI screen. Adds fit/size/owner_first_name/fit_reason to each lead."""
    import target_profiler
    ic = (profile or {}).get("ideal_customer", {})
    offer = ", ".join((profile or {}).get("pain_points", [])[:2]) or "content and marketing"
    for start in range(0, len(leads), 30):
        chunk = leads[start:start + 30]
        # maps_category left out on purpose: it mislabels brands as "supplier"/"shop"
        rows = [{"id": i, "name": l["brand_name"],
                 "website": l.get("website", ""), "reviews": l.get("reviews", 0),
                 "site_title": (l.get("signals") or {}).get("title", ""),
                 "site_description": (l.get("signals") or {}).get("description", "")}
                for i, l in enumerate(chunk)]
        try:
            raw = target_profiler._call_ai(
                FIT_PROMPT.format(offer=offer, who=ic.get("who", ""),
                                  rows=json.dumps(rows, ensure_ascii=False)),
                provider, ai_key, max_tokens=2500)
            res = {r.get("id"): r for r in target_profiler._coerce_json(raw).get("results", [])}
        except Exception as e:
            print(f"[fit_check] {e}")
            res = {}
        for i, l in enumerate(chunk):
            r = res.get(i, {})
            l["fit"] = bool(r.get("fit", True))      # keep on AI failure
            l["size"] = r.get("size", "")
            l["owner_first_name"] = (r.get("owner_first_name") or "").strip()
            l["fit_reason"] = r.get("reason", "")
    return leads


def find_local_leads(apify_key, ai_key, profile, cities, target=20, per_query=20,
                     max_reviews=300, market="India", on_progress=None):
    """Full local pipeline. Returns leads shaped like lead_finder's."""
    def emit(msg, n=0):
        if on_progress:
            on_progress(msg, n)

    queries = (profile or {}).get("maps_queries") or []
    if not queries:
        emit("No Maps search terms in the profile.", 0)
        return []

    places = maps_search(apify_key, queries, cities, per_query, on_progress)
    emit(f"Google Maps: {len(places)} places found.", 0)
    cands = filter_small(places, max_reviews)
    emit(f"{len(cands)} small businesses with their own website "
         f"(under {max_reviews} reviews, chains removed).", 0)
    if not cands:
        return []

    site_data = lf.enrich_emails_via_apify(None, [c["website"] for c in cands], on_progress)
    leads = []
    for c in cands:
        data = site_data.get(c["domain"]) or {}
        email, quality = pick_contact_email(data.get("all_emails", []), c["domain"])
        if not email:
            continue
        c.update(email=email, email_quality=quality, signals=data.get("signals", {}))
        leads.append(c)
    emit(f"{len(leads)} of {len(cands)} publish an email on their site.", 0)

    if ai_key and leads:
        emit("Checking each business is a real fit (own brand, small enough)…", 0)
        fit_check(leads, profile, ai_key)
        before = len(leads)
        leads = [l for l in leads if l["fit"] and l.get("size") != "large"]
        emit(f"{len(leads)} of {before} pass the fit check.", 0)

    rank = {"owner": 0, "owner_gmail": 1, "business_inbox": 2}
    leads.sort(key=lambda l: (rank.get(l["email_quality"], 3), l.get("reviews", 0)))
    out = []
    for l in leads[:target]:
        out.append({
            "brand_name": l["brand_name"],
            "email": l["email"],
            "contact_name": l.get("owner_first_name", ""),
            "contact_role": "Owner" if l.get("owner_first_name") else "",
            "website": l["website"],
            "category": lf._guess_category(l["brand_name"] + " " + l.get("maps_category", ""))
                        or "D2C",
            "market": market,
            "source": "google_maps",
            "email_quality": l["email_quality"],
            "signals": l.get("signals", {}),
            "phone": l.get("phone", ""),
            "reviews": l.get("reviews", 0),
            "rating": l.get("rating"),
            "city": l.get("city", ""),
            "address": l.get("address", ""),
            "fit_reason": l.get("fit_reason", ""),
            "size": l.get("size", ""),
        })
    emit(f"Done — {len(out)} local leads.", len(out))
    return out
