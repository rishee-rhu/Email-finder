"""
Founder finder — gets the founder/CEO's email using only Apify + OpenAI.

How (the same approach Hunter/Apollo use under the hood):
  1. Find the founder's NAME by reading LinkedIn result titles from a Google
     search via Apify (no LinkedIn login — Google indexes the profile titles).
  2. Generate candidate email permutations (priya@, priya.sharma@, psharma@…).
  3. Verify the candidates with an Apify SMTP actor (see email_verifier) and keep
     the one that is actually deliverable.

This module only does steps 1 + 2 (name + candidates). Verification + selection
happens in lead_finder using email_verifier.verify_via_apify.
"""
import re
import lead_finder

_ROLE_WORDS = ("founder", "co-founder", "cofounder", "ceo", "chief executive",
               "owner", "managing director", " md ", "director", "proprietor",
               "co founder", "chief")

# Common corporate email permutations, most-likely first
_PATTERNS = ["{first}", "{first}.{last}", "{f}{last}", "{first}{last}",
             "{first}_{last}", "{f}.{last}", "{last}", "{last}.{first}"]


def _is_name(s):
    words = [w for w in s.split() if w]
    if not (1 <= len(words) <= 4):
        return False
    cleaned = s.replace(" ", "").replace(".", "").replace("-", "").replace("'", "")
    return cleaned.isalpha() and all(w[:1].isupper() for w in words)


def _parse_person(title):
    """'Priya Sharma - Founder & CEO - BrandName | LinkedIn' -> ('Priya Sharma','Founder & CEO')."""
    t = re.sub(r"\s*\|\s*LinkedIn.*$", "", title or "", flags=re.I).strip()
    parts = re.split(r"\s[-–—]\s", t)
    if len(parts) >= 2:
        name = parts[0].strip()
        rest = " ".join(parts[1:]).lower()
        if _is_name(name) and any(w in rest for w in _ROLE_WORDS):
            return name, parts[1].strip()
    return None, None


def find_founder_names(apify_key, brands, on_progress=None):
    """
    brands: list of (brand_name, domain).
    Returns {domain: {"name": str, "role": str}} for the ones we could identify.
    One batched Apify Google run for all brands.
    """
    brands = [(b, d) for b, d in brands if b and d]
    if not apify_key or not brands:
        return {}

    queries = [f'"{b}" (founder OR CEO OR "co-founder") site:linkedin.com/in'
               for b, d in brands]
    if on_progress:
        on_progress(f"Looking up founders for {len(brands)} brands…", 0)

    try:
        items = lead_finder._apify_run(
            apify_key, "apify~google-search-scraper",
            {"queries": "\n".join(queries), "resultsPerPage": 5, "maxPagesPerQuery": 1},
            timeout=300)
    except Exception as e:
        if on_progress:
            on_progress(f"Founder lookup failed: {e}", 0)
        return {}

    out = {}
    for page in items or []:
        term = (page.get("searchQuery") or {}).get("term", "") or page.get("query", "")
        # match this result page back to its brand
        domain = None
        for b, d in brands:
            if f'"{b}"' in term:
                domain = d
                break
        if not domain or domain in out:
            continue
        # the brand's identifying token (domain core), e.g. sleepyowl
        token = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
        # strip a trailing generic word so "thewholetruthfoods" matches "the whole truth"
        core = token
        for suf in ("foods", "food", "india", "official", "store", "shop",
                    "online", "brand", "company", "labs", "world"):
            if core.endswith(suf) and len(core) - len(suf) >= 4:
                core = core[:-len(suf)]
                break
        for r in page.get("organicResults") or []:
            title = r.get("title", "")
            name, role = _parse_person(title)
            if not name:
                continue
            # VALIDATE strictly: the brand must be the person's ACTUAL COMPANY
            # (in the role/company part of the title), not merely mentioned in
            # their profile text. This rejects "founded X, but mentions Brand".
            role_clean = re.sub(r"[^a-z0-9]", "", (role or "").lower())
            if len(core) >= 4 and core not in role_clean:
                continue
            out[domain] = {"name": name, "role": role}
            break
    return out


def match_founder_email(name, emails, domain):
    """
    If a REAL email already scraped from the site belongs to the founder
    (its local-part contains the founder's first or last name), return it.
    This is the highest-confidence result — a real, published founder email.
    """
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in (name or "").split()]
    parts = [p for p in parts if len(p) >= 3]
    if not parts:
        return None
    for e in emails or []:
        local, _, d = e.lower().partition("@")
        if d != domain:
            continue
        if any(p in local for p in parts):
            return e
    return None


def candidate_emails(name, domain):
    """Generate likely email permutations for a person at a domain (most-likely first)."""
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in (name or "").split()]
    parts = [p for p in parts if p]
    if not parts or not domain:
        return []
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""
    f, l = first[:1], last[:1]
    out, seen = [], set()
    for pat in _PATTERNS:
        try:
            local = pat.format(first=first, last=last, f=f, l=l).strip("._")
        except Exception:
            continue
        if not local or (("{last}" in pat or "{l}" in pat) and not last):
            continue
        email = f"{local}@{domain}"
        if email not in seen:
            seen.add(email)
            out.append(email)
    return out
