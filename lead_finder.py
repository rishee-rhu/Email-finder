"""
Lead finder v2 — Multi-market D2C brand email discovery.

Logic per source:
  - Direct list available  → Scrape.do scrapes the page → extract brand domains
  - No direct list         → Apify Google queries → find domains
  - Email enrichment       → Scrape.do visits /contact /about (primary)
                           → Searlo.tech domain lookup (fallback)

Markets: India | USA | UK
Instagram scraper: REMOVED (unreliable, low email-in-bio rate)
"""
import re
import time
import requests
from urllib.parse import urlparse

# ── regex & filters ───────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')

SKIP_EMAIL_PREFIXES = (
    "noreply", "no-reply", "donotreply", "mailer", "bounce",
    "admin@", "test@", "example@", "privacy@", "support@",
    "hello@", "contact@", "care@", "help@", "info@",
)

# Domains we do NOT want in brand lists
SKIP_DOMAINS = [
    "google", "facebook", "instagram", "twitter", "linkedin", "youtube",
    "github", "notion", "medium", "substack", "apple", "microsoft",
    "amazonaws", "cloudflare", "shopify", "wordpress", "wix", "squarespace",
    "flipkart", "myntra", "nykaa", "meesho", "snapdeal", "amazon",
    "ycombinator", "techcrunch", "inc42", "yourstory", "entrackr",
    "firesideventures", "sequoiacap", "100x", "stellarisvp", "technation",
    "seedrs", "crowdcube", "producthunt", "builtwith",
    # ── data vendors / email-format sites (source of placeholder emails) ──
    "salezshark", "rocketreach", "lusha", "zoominfo", "signalhire", "apollo",
    "hunter.io", "snov", "leadsblue", "clearbit", "kaspr", "contactout",
    "adapt.io", "uplead", "slintel", "6sense", "leadiq", "getprospect",
    "findymail", "anymailfinder", "emailformat", "email-format", "neverbounce",
    "easyleadz", "leadzpipe", "ampliz", "saleshandy", "leadrop",
    # ── B2B directories / marketplaces / listicles ──
    "indiamart", "exportersindia", "tradeindia", "justdial", "sulekha",
    "yellowpages", "ambitionbox", "glassdoor", "indeed", "naukri", "yelp",
    "tofler", "zaubacorp", "crunchbase", "tracxn", "goodfirms", "clutch",
    "g2.com", "wikipedia", "quora", "reddit", "pinterest", "trustpilot",
    "mouthshut", "businessworld", "economictimes", "moneycontrol",
    # ── document-sharing / file-dump sites (not brands) ──
    "pdfcoffee", "scribd", "slideshare", "studocu", "coursehero", "academia",
    "researchgate", "yumpu", "calameo", "fliphtml5", "dokumen", "vdocument",
    "issuu", "4shared", "docplayer",
    # ── research / news / health-info / startup databases (not brands) ──
    "ncbi", "nih.gov", "frontiersin", "sciencedirect", "springer", "harvard",
    "fda.gov", "who.int", "fao.org", "dealroom", "pitchbook", "d2c.fyi",
    "lbb.in", "discoveringbrands", "indiatimes", "hindustantimes", "ndtv",
    "livemint", "thehindu", "news", "1mg.com", "netmeds", "pharmeasy",
    "ulprospector", "smartbiz", "blogspot", "mypminterview", "dronahq",
    "exei.ai", "flowqen",
]

# Domain suffixes that are never D2C brands
SKIP_SUFFIXES = (".gov", ".gov.in", ".nic.in", ".edu", ".ac.in", ".edu.in",
                 ".mil", ".org.in", ".org", ".int")

# Email local-parts that are placeholders, not real addresses
PLACEHOLDER_LOCALS = (
    "firstname", "first.last", "firstlast", "lastname", "name", "yourname",
    "your", "example", "sample", "email", "username", "user", "abc", "xyz",
    "test", "domain", "company", "yourcompany", "mail",
)

# Role inboxes (not a specific person / decision-maker)
ROLE_LOCALS = (
    "info", "contact", "support", "sales", "hello", "care", "help", "team",
    "admin", "office", "enquiry", "enquiries", "inquiry", "service", "services",
    "marketing", "hr", "careers", "jobs", "billing", "accounts", "orders",
    "noreply", "no-reply", "donotreply",
)

# Decision-maker signals in an email local-part
CSUITE_LOCALS = (
    "founder", "cofounder", "co-founder", "ceo", "md", "managingdirector",
    "director", "owner", "proprietor", "cmo", "coo", "cto", "partner",
)

FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
             "rediffmail.com", "icloud.com", "aol.com", "live.com", "ymail.com"}

# Title/snippet phrases that signal a SERVICE PROVIDER (agency/SaaS), not a brand
#  to pitch. We skip these so discovery returns actual client brands.
AGENCY_TERMS = (
    "agency", "consulting", "consultancy", "marketing services",
    "digital marketing", "performance marketing", "growth partner",
    "we help brands", "software company", "saas platform", "it services",
    "web development", "seo services", "lead generation", "outsourcing",
    "solutions pvt", "technologies pvt", "media private",
)


# Page-title phrases that are NOT brand names
GENERIC_TITLES = (
    "contact us", "contact", "about us", "about", "home", "homepage",
    "get in touch", "reach us", "our story", "privacy policy", "terms",
    "shipping", "returns", "faq", "blog", "shop", "store", "login",
    "manufacturers", "suppliers", "wholesalers", "distributors", "dealers",
    "email id format", "email format", "list of", "top 10", "best ", "buy ",
    "companies", "directory", "database", "name", ".xlsx", ".pdf", ".csv",
    ".doc", "list ", " list", "untitled", "document",
)


def extract_email(text):
    for m in EMAIL_RE.finditer(text or ""):
        e = m.group().lower()
        if not any(e.startswith(p) or p in e for p in SKIP_EMAIL_PREFIXES):
            return e
    return None


def _is_placeholder_email(email):
    """Reject placeholder/sample emails like firstname@brand.com."""
    if not email or "@" not in email:
        return True
    local = email.split("@")[0].lower()
    return any(local == p or local.startswith(p + ".") or local == p.replace(".", "")
               for p in PLACEHOLDER_LOCALS)


def _clean_brand_name(title, domain):
    """Use the page title only if it looks like a real brand, else derive from domain."""
    t = (title or "").strip()
    tl = t.lower()
    if not t or len(t) < 2 or any(g in tl for g in GENERIC_TITLES):
        return domain.split(".")[0].replace("-", " ").title()
    return t[:60]


def extract_domain(url):
    if not url:
        return ""
    try:
        url = url if url.startswith("http") else f"https://{url}"
        d = urlparse(url).netloc.lower().lstrip("www.")
        return d.split(":")[0]
    except Exception:
        return ""


def is_brand_domain(domain):
    if not domain or len(domain) < 5 or "." not in domain:
        return False
    if any(domain.endswith(suf) for suf in SKIP_SUFFIXES):
        return False
    return not any(s in domain for s in SKIP_DOMAINS)


# ── Scrape.do helpers ─────────────────────────────────────────────────────────

def _scrape(key, url, render=False):
    """Fetch URL via Scrape.do. Returns HTML string or ''."""
    try:
        r = requests.get(
            "https://api.scrape.do",
            params={"token": key, "url": url, "render": "true" if render else "false"},
            timeout=30,
        )
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def _extract_external_domains(html, exclude=""):
    """Pull brand-looking domains from href attributes in HTML."""
    urls = re.findall(r'href=["\']?(https?://[^\s"\'<>]{4,})', html)
    seen = set()
    results = []
    for url in urls:
        d = extract_domain(url)
        if d and d not in seen and is_brand_domain(d) and (not exclude or exclude not in d):
            seen.add(d)
            results.append(d)
    return results


# ── Apify helper ──────────────────────────────────────────────────────────────

def _req(method, url, retries=4, **kwargs):
    """HTTP request that survives transient DNS/connection blips (retries w/ backoff)."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            last = e
            time.sleep(2 * (attempt + 1))   # 2s, 4s, 6s, 8s
        except requests.exceptions.HTTPError:
            raise                            # real HTTP errors (4xx/5xx) — don't retry
    raise last if last else RuntimeError("request failed")


def _apify_run(api_key, actor_id, run_input, timeout=180):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = _req("POST", f"https://api.apify.com/v2/acts/{actor_id}/runs",
             json=run_input, headers=headers, timeout=30)
    run_id = r.json()["data"]["id"]

    deadline = time.time() + timeout
    status_r = None
    while time.time() < deadline:
        status_r = _req("GET", f"https://api.apify.com/v2/actor-runs/{run_id}",
                        headers=headers, timeout=15)
        status = status_r.json()["data"]["status"]
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(4)

    if not status_r or status_r.json()["data"]["status"] != "SUCCEEDED":
        return []

    dataset_id = status_r.json()["data"]["defaultDatasetId"]
    items_r = _req("GET", f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit=500",
                   headers=headers, timeout=30)
    return items_r.json()


# ── Direct list scrapers ──────────────────────────────────────────────────────

def scrape_portfolio_page(scrape_do_key, url, exclude_domain, source_name):
    """
    Scrape a VC/accelerator portfolio page.
    Finds all external links → extract brand domains.
    """
    html = _scrape(scrape_do_key, url, render=True)
    if not html:
        return []
    domains = _extract_external_domains(html, exclude=exclude_domain)
    return [
        {
            "brand_name": d.split(".")[0].replace("-", " ").title(),
            "website": f"https://{d}",
            "source": source_name,
            "email": "",
        }
        for d in domains
        if is_brand_domain(d)
    ]


def scrape_builtwith_shopify(scrape_do_key, country_code, market):
    """
    BuiltWith lists all Shopify stores by country — great source for D2C brands.
    URL pattern: builtwith.com/cms/shopify/{country_code}
    """
    url = f"https://www.builtwith.com/cms/shopify/{country_code}"
    html = _scrape(scrape_do_key, url, render=False)
    if not html:
        return []

    # BuiltWith renders domain names in table cells and list items
    domains = re.findall(
        r'(?:href=["\']https?://(?:www\.)?|>)([a-z0-9][a-z0-9\-]{1,50}\.[a-z]{2,}(?:\.[a-z]{2})?)<',
        html,
    )
    seen = set()
    brands = []
    for d in domains:
        if d not in seen and is_brand_domain(d):
            seen.add(d)
            brands.append({
                "brand_name": d.split(".")[0].replace("-", " ").title(),
                "website": f"https://{d}",
                "source": f"shopify_{market.lower()}",
                "email": "",
            })
    return brands[:300]


def scrape_article_page(scrape_do_key, url, source_name):
    """
    Scrape a media article (Inc42, YourStory, Tracxn) for brand website links.
    """
    html = _scrape(scrape_do_key, url, render=False)
    if not html:
        return []
    domains = _extract_external_domains(html, exclude="")
    return [
        {
            "brand_name": d.split(".")[0].replace("-", " ").title(),
            "website": f"https://{d}",
            "source": source_name,
            "email": "",
        }
        for d in domains[:60]
        if is_brand_domain(d)
    ]


# ── Google domain discovery ───────────────────────────────────────────────────

def find_domains_via_google(apify_key, queries, max_domains=300):
    """
    Run Google queries → extract brand website URLs from organic results.
    Returns list of {brand_name, website, email, source} dicts.
    Email is set if it appears in the snippet (bonus); otherwise empty.
    """
    results = []
    seen = set()

    try:
        items = _apify_run(
            apify_key,
            "apify~google-search-scraper",
            {
                "queries": "\n".join(queries),
                "resultsPerPage": 10,
                "maxPagesPerQuery": 2,   # 2 pages = lower Apify cost per run
            },
            timeout=300,
        )

        for page in items:
            for r in page.get("organicResults") or []:
                url  = r.get("url", "")
                d    = extract_domain(url)
                full_title = (r.get("title") or "")
                title = full_title.split("|")[0].split("–")[0].split("-")[0].strip()
                snip = r.get("description", "")
                snip_email = extract_email(snip) or ""
                if _is_placeholder_email(snip_email):
                    snip_email = ""

                # Skip service-providers (agencies/SaaS) — we want client brands
                hay = (full_title + " " + snip).lower()
                if any(t in hay for t in AGENCY_TERMS):
                    continue

                if d and is_brand_domain(d) and d not in seen:
                    seen.add(d)
                    results.append({
                        "brand_name": _clean_brand_name(title, d),
                        "website": f"https://{d}",
                        "email": snip_email,
                        "source": "google_search",
                    })

                if len(results) >= max_domains:
                    return results

    except Exception as e:
        print(f"[Google] error: {e}")

    return results


# ── Email enrichment ──────────────────────────────────────────────────────────

def enrich_with_email(website, scrape_do_key=None, searlo_key=None):
    """
    Given a brand website, find the founder / marketing email.
    1. Scrape.do: visit /contact, /about pages (primary — works for small brands)
    2. Searlo.tech: domain lookup (works for medium brands already indexed)
    """
    if not website:
        return None

    domain = extract_domain(website)

    # 1 — Scrape.do
    if scrape_do_key:
        base = website.rstrip("/")
        for path in ["/contact", "/contact-us", "/about", "/about-us", "/team", ""]:
            try:
                html = _scrape(scrape_do_key, f"{base}{path}")
                email = extract_email(html)
                if email:
                    return email
            except Exception:
                pass

    # 2 — Searlo
    if searlo_key and domain:
        try:
            r = requests.get(
                "https://api.searlo.tech/email-finder",
                params={"domain": domain, "apiKey": searlo_key},
                timeout=15,
            )
            if r.status_code == 200:
                data   = r.json()
                emails = data.get("emails") or data.get("data", {}).get("emails", [])
                if emails:
                    priority = ["founder", "ceo", "co-founder", "owner",
                                "marketing", "brand", "growth"]
                    for p in priority:
                        for e in emails:
                            pos = (e.get("position") or e.get("role") or "").lower()
                            if p in pos:
                                return e.get("email") or e.get("value")
                    first = emails[0]
                    return first.get("email") or first.get("value")
        except Exception as e:
            print(f"[Searlo] {domain}: {e}")

    return None


# ── Apify-only email enrichment (no Scrape.do) ────────────────────────────────

# Local-part priority when a page exposes several addresses
_EMAIL_PRIORITY = ["founder", "ceo", "co-founder", "cofounder", "owner",
                   "hello", "marketing", "brand", "growth", "team", "contact",
                   "info", "sales", "care", "support"]

# cheerio-scraper page function: pull emails AND presence signals in one pass
# (so we never scrape a brand's site twice — saves Apify credits).
_PAGE_FUNCTION = (
    "async function pageFunction(context) {"
    " const { $, request, body } = context;"
    " const text = (body || '') + ' ' + ($('a[href^=\"mailto:\"]').map(function(i,el){"
    " return $(el).attr('href');}).get().join(' '));"
    " const re = /[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/g;"
    " const emails = Array.from(new Set((text.match(re) || []).map(function(e){return e.toLowerCase();})));"
    " const links = $('a[href]').map(function(i,el){return $(el).attr('href');}).get();"
    " const social = {};"
    " links.forEach(function(h){ var u=(h||'').toLowerCase();"
    "  if(u.indexOf('instagram.com')>-1) social.instagram=h;"
    "  else if(u.indexOf('facebook.com')>-1) social.facebook=h;"
    "  else if(u.indexOf('youtube.com')>-1) social.youtube=h;"
    "  else if(u.indexOf('tiktok.com')>-1) social.tiktok=h;"
    "  else if(u.indexOf('twitter.com')>-1||u.indexOf('x.com')>-1) social.twitter=h;"
    "  else if(u.indexOf('linkedin.com')>-1) social.linkedin=h; });"
    " var hasBlog = links.some(function(h){return (h||'').toLowerCase().indexOf('/blog')>-1;});"
    " return { url: request.url, emails: emails, social: social, hasBlog: hasBlog,"
    "  title: $('title').text().slice(0,160),"
    "  description: ($('meta[name=description]').attr('content')||'').slice(0,250) };"
    "}"
)

# Homepage ("") gives signals; about/team are the highest hit-rate for a real
# founder email. Kept to 5 paths to control Apify page-load cost.
_ENRICH_PATHS = ["", "/about", "/about-us", "/team", "/contact"]


def _looks_like_person(local):
    """firstname.lastname / firstnamelastname style, not a role inbox."""
    local = local.lower()
    if any(local.startswith(r) for r in ROLE_LOCALS):
        return False
    # has a dot separating two name-ish parts, e.g. rajesh.jasani
    if "." in local:
        parts = [p for p in local.split(".") if p]
        if len(parts) >= 2 and all(p.isalpha() and len(p) >= 2 for p in parts):
            return True
    return False


def _pick_best_email(emails, domain):
    """
    Pick the most decision-maker-like email.
    Priority: C-suite role > person name on brand domain > other brand-domain >
    person name on free-mail. Rejects placeholders. Returns (email, quality) or (None, None).
    quality in {"csuite","person","brand","generic"}.
    """
    cands = [e.lower() for e in emails if e and "@" in e and not _is_placeholder_email(e)]
    if not cands:
        return None, None

    brand_dom = [e for e in cands if domain and domain in e.split("@")[1]]
    pool = brand_dom or cands

    # 1 — explicit C-suite local part on the brand's own domain
    for e in pool:
        if any(k in e.split("@")[0] for k in CSUITE_LOCALS):
            return e, "csuite"
    # 2 — person name (firstname.lastname) on brand domain
    for e in pool:
        d = e.split("@")[1]
        if d not in FREE_MAIL and _looks_like_person(e.split("@")[0]):
            return e, "person"
    # 3 — any non-role email on the brand's own domain
    for e in pool:
        d = e.split("@")[1]
        if d not in FREE_MAIL and not any(e.split("@")[0].startswith(r) for r in ROLE_LOCALS):
            return e, "brand"
    # 4 — person name on a free mailbox (small brands often use gmail)
    for e in cands:
        if _looks_like_person(e.split("@")[0]):
            return e, "person"
    return None, None


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch_page(url):
    """Plain HTTPS GET of a public page. Free — no Apify needed for this."""
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=12,
                         allow_redirects=True)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    return ""


def _parse_page(html):
    """Pull emails + presence signals from a page's HTML (regex, no extra deps)."""
    emails = set(m.group().lower() for m in EMAIL_RE.finditer(html))
    for m in re.findall(r'mailto:([^"\'>?\s]+)', html, re.I):
        e = m.strip().lower()
        if "@" in e:
            emails.add(e)
    social = {}
    for h in re.findall(r'href=["\']?(https?://[^"\'>\s]+)', html, re.I):
        u = h.lower()
        if "instagram.com" in u:
            social.setdefault("instagram", h)
        elif "facebook.com" in u:
            social.setdefault("facebook", h)
        elif "youtube.com" in u:
            social.setdefault("youtube", h)
        elif "tiktok.com" in u:
            social.setdefault("tiktok", h)
        elif "twitter.com" in u or "x.com" in u:
            social.setdefault("twitter", h)
        elif "linkedin.com" in u:
            social.setdefault("linkedin", h)
    has_blog = "/blog" in html.lower()
    title = ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if mt:
        title = re.sub(r"\s+", " ", mt.group(1)).strip()[:160]
    desc = ""
    md = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)',
                   html, re.I)
    if md:
        desc = md.group(1).strip()[:250]
    return emails, {"social": social, "hasBlog": has_blog, "title": title,
                    "description": desc}


def enrich_emails_via_apify(apify_key, websites, on_progress=None):
    """
    Scrape each brand's about/team/contact pages by fetching them DIRECTLY (free —
    no Apify needed for public pages). Returns
    {domain: {email, quality, signals, all_emails}}.
    (Name kept for compatibility; apify_key is unused.)
    """
    import concurrent.futures

    targets = []
    seen = set()
    for w in websites or []:
        d = extract_domain(w)
        if not d or d in seen:
            continue
        seen.add(d)
        base = (w if w.startswith("http") else f"https://{d}").rstrip("/")
        targets.append((d, base))

    if not targets:
        return {}
    if on_progress:
        on_progress(f"Scraping {len(targets)} brand sites for founder emails…", 0)

    def work(item):
        d, base = item
        all_emails, sig = set(), {}
        for path in _ENRICH_PATHS:
            html = _fetch_page(f"{base}{path}")
            if not html:
                continue
            em, s = _parse_page(html)
            all_emails.update(em)
            if s.get("social"):
                sig.setdefault("social", {}).update(s["social"])
            if s.get("hasBlog"):
                sig["hasBlog"] = True
            elif "hasBlog" not in sig:
                sig["hasBlog"] = False
            if s.get("title") and not sig.get("title"):
                sig["title"] = s["title"]
            if s.get("description") and not sig.get("description"):
                sig["description"] = s["description"]
        best, quality = _pick_best_email(list(all_emails), d)
        return d, {"email": best or "", "quality": quality or "",
                   "signals": sig, "all_emails": list(all_emails)}

    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for d, data in ex.map(work, targets):
            result[d] = data
    return result


def find_leads_from_queries(apify_key, queries, target=100, market="India",
                            category_hint="", on_progress=None):
    """
    Dossier-driven finder (Apify only):
      1. Run the profiler's Google queries → discover brand domains
      2. Batch-scrape contact/about pages → emails
      3. Return lead dicts (unverified — caller runs email_verifier)

    Each lead: brand_name, email, website, category, market, source
    """
    def emit(msg, n=0):
        if on_progress:
            on_progress(msg, n)

    if not apify_key:
        emit("No Apify key — cannot search.", 0)
        return []

    # 1 — discover lots of candidate domains (quality filtering drops many, so
    #     cast a wide net to still hit `target` good leads)
    emit(f"Searching for matching brands ({len(queries)} queries)…", 0)
    raw = find_domains_via_google(apify_key, queries, max_domains=min(target * 4, 100))
    emit(f"Found {len(raw)} candidate brand sites — finding decision-maker emails…", 0)

    # de-dupe by domain
    seen, candidates = set(), []
    for r in raw:
        d = extract_domain(r.get("website", ""))
        if d and d not in seen:
            seen.add(d)
            candidates.append(r)

    # 2 — batch-scrape contact/about pages for emails
    need_email = [c["website"] for c in candidates if not c.get("email")]
    domain_email = enrich_emails_via_apify(apify_key, need_email, on_progress) if need_email else {}

    # 3 — assemble leads, keeping only quality (decision-maker-ish) emails
    leads = []
    seen_emails = set()
    for c in candidates:
        d = extract_domain(c.get("website", ""))
        enr = domain_email.get(d) or {}
        # Prefer a properly enriched (quality-filtered) email. Only use a
        # snippet email if it passes the SAME quality gate (no generic gmail).
        email, quality = enr.get("email", ""), enr.get("quality", "")
        if not email:
            snippet_email = c.get("email", "")
            if snippet_email and not _is_placeholder_email(snippet_email):
                se, sq = _pick_best_email([snippet_email], d)
                if se:
                    email, quality = se, sq
        if not email or email in seen_emails or _is_placeholder_email(email):
            continue
        seen_emails.add(email)
        leads.append({
            "brand_name": _clean_brand_name(c.get("brand_name", ""), d),
            "email": email,
            "website": c.get("website", f"https://{d}"),
            "category": _guess_category(c.get("brand_name", "")) or (category_hint or "D2C"),
            "market": market,
            "source": "dossier_search",
            "email_quality": quality,          # csuite / person / brand
            "signals": enr.get("signals", {}),  # scraped audit signals for personalisation
        })
        emit(f"{len(leads)} quality leads found…", len(leads))
        if len(leads) >= target:
            break

    # Sort best-first: C-suite, then person-named, then other brand-domain
    rank = {"csuite": 0, "person": 1, "brand": 2, "": 3}
    leads.sort(key=lambda l: rank.get(l.get("email_quality", ""), 3))
    emit(f"Done — {len(leads)} quality leads (pre-verification)", len(leads))
    return leads


# ── Real brand-domain directories (Shopify lists, accelerator portfolios,
#    curated D2C lists). These give REAL brands — the fix for junk discovery. ────
DIRECTORY_SOURCES = {
    "India": [
        "https://www.builtwith.com/cms/shopify/in",
        "https://yourstory.com/tag/d2c",
        "https://surge.sequoiacap.com/companies/",
        "https://www.firesideventures.com/portfolio",
        "https://100x.vc/portfolio",
    ],
    "USA": [
        "https://www.builtwith.com/cms/shopify/us",
        "https://www.lererhippeau.com/portfolio",
        "https://www.forerunnerventures.com/companies",
    ],
    "UK": [
        "https://www.builtwith.com/cms/shopify/gb",
        "https://technation.io/companies/",
    ],
}

_DIRECTORY_PAGE_FN = (
    "async function pageFunction(context){"
    " const {$, request} = context;"
    " const links = $('a[href]').map(function(i,el){return $(el).attr('href');}).get();"
    " return { url: request.url, links: links };"
    "}"
)


def discover_brand_domains_from_directories(apify_key, market="India", limit=200,
                                            on_progress=None):
    """
    Scrape curated directory/portfolio pages and pull out REAL brand domains
    (their outbound links). Returns [{brand_name, website}].
    """
    def emit(m, n=0):
        if on_progress:
            on_progress(m, n)

    sources = DIRECTORY_SOURCES.get(market, DIRECTORY_SOURCES["India"])
    emit(f"Reading {len(sources)} brand directories for {market}…", 0)
    try:
        items = _apify_run(
            apify_key, "apify~cheerio-scraper",
            {"startUrls": [{"url": u} for u in sources],
             "pageFunction": _DIRECTORY_PAGE_FN,
             "maxConcurrency": 5, "maxRequestsPerCrawl": len(sources) + 2,
             "ignoreSslErrors": True,
             "proxyConfiguration": {"useApifyProxy": True}},
            timeout=300)
    except Exception as e:
        emit(f"Directory read failed: {e}", 0)
        return []

    seen, out = set(), []
    for it in items or []:
        src = extract_domain(it.get("url", ""))
        for href in it.get("links") or []:
            d = extract_domain(href)
            if d and d not in seen and d != src and is_brand_domain(d):
                seen.add(d)
                out.append({"brand_name": d.split(".")[0].replace("-", " ").title(),
                            "website": f"https://{d}"})
                if len(out) >= limit:
                    break
        if len(out) >= limit:
            break
    emit(f"Found {len(out)} real brand domains", len(out))
    return out


def find_founder_leads(apify_key, candidates, target=100, market="India",
                       category_hint="", on_progress=None):
    """
    Founder-targeted finder (Apify + OpenAI only), over a list of REAL brand
    domains (from directories). For each brand:
      1. Scrape its site for signals + emails (one pass)
      2. Find its founder's NAME from LinkedIn titles — validated to the brand
      3. Use a real published founder email if present, else permutation+SMTP-verify
      4. Keep ONLY founder emails — skip the brand otherwise (never business)
    candidates: list of {brand_name, website}.
    """
    import founder_finder
    import email_verifier

    def emit(msg, n=0):
        if on_progress:
            on_progress(msg, n)

    if not apify_key:
        emit("No Apify key — cannot search.", 0)
        return []

    # de-dupe incoming candidates by domain
    seen, cands = set(), []
    for r in candidates or []:
        d = extract_domain(r.get("website", ""))
        if d and d not in seen:
            seen.add(d)
            cands.append(r)
    candidates = cands
    if not candidates:
        emit("No brand domains to process.", 0)
        return []
    # Cap how many brands enter the COSTLY stages. Page scraping is free (direct
    # fetch), but each founder lookup is a paid Google search and verification costs
    # too — so we only spend on roughly what we need to hit the target.
    cap = min(max(target * 2, 25), 50)
    candidates = candidates[:cap]

    # 2 — scrape sites (emails + signals)
    emit(f"Found {len(candidates)} brand sites — scraping…", 0)
    domain_data = enrich_emails_via_apify(apify_key, [c["website"] for c in candidates],
                                          on_progress)

    # 3 — founder names from LinkedIn result titles
    brand_domain = [(c.get("brand_name") or extract_domain(c["website"]).split(".")[0],
                     extract_domain(c["website"])) for c in candidates]
    founders = founder_finder.find_founder_names(apify_key, brand_domain, on_progress)
    emit(f"Identified a founder for {len(founders)} of {len(candidates)} brands.", 0)

    # 4 — for each brand WITH a known founder, first try to MATCH a real scraped
    #     email to the founder's name; only guess+verify if no real one exists.
    per_domain_real, per_domain_cands, all_candidates = {}, {}, []
    for c in candidates:
        d = extract_domain(c["website"])
        fn = founders.get(d)
        if not fn:
            continue   # no founder identified → this brand will be skipped
        all_emails = (domain_data.get(d) or {}).get("all_emails", [])
        real = founder_finder.match_founder_email(fn["name"], all_emails, d)
        if real:
            per_domain_real[d] = real
        else:
            cands = founder_finder.candidate_emails(fn["name"], d)
            per_domain_cands[d] = cands
            all_candidates.extend(cands)

    verified = {}
    if all_candidates:
        emit(f"Verifying {len(all_candidates)} founder-email guesses via Apify SMTP…", 0)
        # strict: if the SMTP actor fails, drop the guesses (never send unverified)
        verified = email_verifier.verify_via_apify(
            apify_key, all_candidates, on_progress, strict=True)

    # 5 — assemble. ONLY founder emails. No business/role fallback — skip otherwise.
    leads, seen_emails = [], set()
    for c in candidates:
        d = extract_domain(c["website"])
        fn = founders.get(d)
        if not fn:
            continue                     # no founder name → skip

        email, quality = "", ""
        if per_domain_real.get(d):
            email, quality = per_domain_real[d], "founder_real"      # real published email
        else:
            for cand in per_domain_cands.get(d, []):
                v = verified.get(cand)
                if v and v.get("valid"):
                    email, quality = cand, "founder_verified"        # verified guess
                    break

        if not email or email in seen_emails or _is_placeholder_email(email):
            continue                     # no founder email → SKIP (never business)
        seen_emails.add(email)
        enr = domain_data.get(d) or {}
        leads.append({
            "brand_name": _clean_brand_name(c.get("brand_name", ""), d),
            "email": email,
            "contact_name": fn["name"],
            "contact_role": fn.get("role", ""),
            "website": c.get("website", f"https://{d}"),
            "category": _guess_category(c.get("brand_name", "")) or (category_hint or "D2C"),
            "market": market,
            "source": "founder_finder",
            "email_quality": quality,
            "signals": enr.get("signals", {}),
        })
        emit(f"{len(leads)} founder emails ready…", len(leads))
        if len(leads) >= target:
            break

    rank = {"founder_real": 0, "founder_verified": 1}
    leads.sort(key=lambda l: rank.get(l.get("email_quality", ""), 2))
    n_real = sum(1 for l in leads if l["email_quality"] == "founder_real")
    emit(f"Done — {len(leads)} founder emails ({n_real} real, "
         f"{len(leads) - n_real} verified-guess)", len(leads))
    return leads


# ── Category guesser ──────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Skincare":          ["skincare", "skin care", "serum", "moisturiser", "beauty",
                          "glow", "cream", "cosmetic", "derma", "sunscreen"],
    "Fashion":           ["fashion", "clothing", "apparel", "wear", "dress", "saree",
                          "kurta", "handloom", "streetwear", "jeans", "shirts"],
    "Jewellery":         ["jewellery", "jewelry", "necklace", "earring", "ring",
                          "bracelet", "gem", "diamond", "gold"],
    "Health & Wellness": ["supplement", "protein", "nutrition", "wellness", "ayurved",
                          "vitamin", "health", "fitness", "gym", "nutraceutical"],
    "Food & Beverage":   ["food", "snack", "chocolate", "tea", "coffee", "organic",
                          "spice", "beverage", "drink", "biscuit", "cookie"],
    "Home & Living":     ["home", "decor", "candle", "lamp", "furniture", "interior",
                          "artisan", "craft", "kitchen"],
    "Pet Care":          ["pet", "dog", "cat", "animal", "paw", "vet"],
    "Baby & Kids":       ["baby", "kids", "children", "toddler", "infant", "parenting"],
    "Hair Care":         ["hair", "shampoo", "conditioner", "scalp", "haircare"],
}


def _guess_category(text):
    t = (text or "").lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return cat
    return "D2C"


# ── Market config ─────────────────────────────────────────────────────────────

MARKET_CONFIG = {
    "India": {
        "direct_sources": [
            # VC / Accelerator portfolios (D2C focused)
            {
                "name": "Sequoia Surge",
                "url":  "https://surge.sequoiacap.com/companies/",
                "exclude": "sequoiacap.com",
                "type": "portfolio",
            },
            {
                "name": "Fireside Ventures",
                "url":  "https://www.firesideventures.com/portfolio",
                "exclude": "firesideventures.com",
                "type": "portfolio",
            },
            {
                "name": "100x.vc",
                "url":  "https://100x.vc/portfolio",
                "exclude": "100x.vc",
                "type": "portfolio",
            },
            {
                "name": "Stellaris VP",
                "url":  "https://www.stellarisvp.com/portfolio/",
                "exclude": "stellarisvp.com",
                "type": "portfolio",
            },
            {
                "name": "Orios VP",
                "url":  "https://www.oriosvp.com/portfolio/",
                "exclude": "oriosvp.com",
                "type": "portfolio",
            },
            # Media / list pages
            {
                "name": "Inc42 D2C brands",
                "url":  "https://inc42.com/features/india-d2c-brands/",
                "exclude": "inc42.com",
                "type": "article",
            },
            {
                "name": "Inc42 D2C 30",
                "url":  "https://inc42.com/features/d2c-startup-of-the-year/",
                "exclude": "inc42.com",
                "type": "article",
            },
            {
                "name": "YourStory D2C",
                "url":  "https://yourstory.com/tag/direct-to-consumer",
                "exclude": "yourstory.com",
                "type": "article",
            },
            # Shopify stores in India — bulk source
            {
                "name": "Shopify India stores",
                "type": "builtwith",
                "country": "in",
                "market": "India",
            },
        ],
        "google_queries": [
            "Indian D2C brand official website founder contact skincare OR haircare OR fashion",
            "\"made in India\" D2C brand Shopify store \"about us\" founder email",
            "site:yourstory.com Indian D2C consumer brand founder website 2024",
            "site:inc42.com \"D2C brand\" India \"founded\" website",
            "site:entrackr.com Indian startup D2C brand website 2024",
            "Indian D2C startup \"our story\" founder CEO website contact",
            "Shark Tank India brand website founder contact email",
            "DPIIT recognised startup India consumer brand website founder",
            "\"Indian brand\" skincare OR wellness OR food OR fashion founder email website",
            "Indian D2C Kolkata OR Mumbai OR Bengaluru brand founder website contact",
            "site:crunchbase.com Indian consumer startup D2C brand 2022 2023 2024",
            "Indian D2C brand Shopify \"visit store\" OR \"shop now\" founder contact",
            "\"Rs crore\" OR \"lakh revenue\" Indian D2C brand founder website",
            "site:tracxn.com Indian D2C consumer brand website",
        ],
    },

    "USA": {
        "direct_sources": [
            {
                "name": "YC Consumer USA",
                "url":  "https://www.ycombinator.com/companies?industry=Consumer+Products&regions=United+States",
                "exclude": "ycombinator.com",
                "type": "portfolio",
            },
            {
                "name": "Techstars Portfolio",
                "url":  "https://www.techstars.com/portfolio",
                "exclude": "techstars.com",
                "type": "portfolio",
            },
            {
                "name": "Lerer Hippeau",
                "url":  "https://www.lererhippeau.com/portfolio",
                "exclude": "lererhippeau.com",
                "type": "portfolio",
            },
            {
                "name": "Forerunner Ventures",
                "url":  "https://www.forerunnerventures.com/companies",
                "exclude": "forerunnerventures.com",
                "type": "portfolio",
            },
            {
                "name": "Shopify USA stores",
                "type": "builtwith",
                "country": "us",
                "market": "USA",
            },
        ],
        "google_queries": [
            "DTC brand USA founder email contact \"about us\" Shopify 2023 2024",
            "\"direct to consumer\" brand USA startup founder CEO email website",
            "DTC startup USA consumer products founder email contact official website",
            "US ecommerce brand founder email skincare OR wellness OR food OR apparel",
            "site:producthunt.com consumer brand USA founder website 2024",
            "\"American brand\" DTC founder email contact ecommerce Shopify",
            "US D2C startup \"our story\" founder email website",
            "site:techcrunch.com DTC brand USA founded 2022 2023 2024 website",
            "US consumer brand CPG startup founder CEO contact website 2024",
            "\"founded in\" USA DTC brand ecommerce founder email official website",
            "DTC health OR wellness OR beauty brand USA founder contact email website",
            "site:crunchbase.com US consumer DTC brand startup 2023 2024",
            "US Shopify brand founder email \"about\" OR \"contact\" small business",
            "site:businessinsider.com DTC brand USA founder 2023 2024",
        ],
    },

    "UK": {
        "direct_sources": [
            {
                "name": "Tech Nation",
                "url":  "https://technation.io/portfolio/",
                "exclude": "technation.io",
                "type": "portfolio",
            },
            {
                "name": "Seedrs Consumer",
                "url":  "https://www.seedrs.com/discover?categories=consumer",
                "exclude": "seedrs.com",
                "type": "portfolio",
            },
            {
                "name": "Backed VC",
                "url":  "https://backed.vc/portfolio",
                "exclude": "backed.vc",
                "type": "portfolio",
            },
            {
                "name": "Shopify UK stores",
                "type": "builtwith",
                "country": "gb",
                "market": "UK",
            },
        ],
        "google_queries": [
            "UK DTC brand founder email contact \"about us\" 2023 2024",
            "\"direct to consumer\" brand UK startup founder email website",
            "British brand DTC ecommerce founder CEO email contact official website",
            "UK consumer brand startup \"our story\" founder email website",
            "site:startups.co.uk DTC brand UK founder website 2024",
            "UK D2C brand Shopify store founder email contact",
            "\"British brand\" founder email skincare OR wellness OR food OR fashion",
            "UK ecommerce brand founder email small business D2C website",
            "site:techcrunch.com UK DTC brand founded 2022 2023 website",
            "UK consumer startup founder email contact brand official website",
            "site:crunchbase.com UK consumer DTC brand 2023 2024",
            "UK Shopify brand \"about\" OR \"contact\" founder email website",
        ],
    },
}


# ── Main entry point ──────────────────────────────────────────────────────────

def find_leads(
    apify_key=None,
    scrape_do_key=None,
    searlo_key=None,
    target=100,
    markets=None,
    on_progress=None,
):
    """
    Find up to `target` verified leads across specified markets.

    markets: list of "India", "USA", "UK" — defaults to ["India"]
    Each lead dict: brand_name, email, website, category, market, source
    """
    if markets is None:
        markets = ["India"]

    leads = []
    seen_emails  = set()
    seen_domains = set()

    def emit(msg):
        if on_progress:
            on_progress(msg, len(leads))

    def add(lead_dict):
        email  = (lead_dict.get("email") or "").strip().lower()
        domain = extract_domain(lead_dict.get("website", ""))
        if not email or "@" not in email or email in seen_emails:
            return False
        if domain and domain in seen_domains:
            return False
        seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        lead_dict["email"] = email
        leads.append(lead_dict)
        return True

    for market in markets:
        config = MARKET_CONFIG.get(market)
        if not config:
            continue

        market_target = max(1, target // len(markets))
        emit(f"[{market}] Starting — need ~{market_target} leads")

        # ── Step 1: Direct list sources ───────────────────────────────────────
        if scrape_do_key:
            for source in config.get("direct_sources", []):
                if len(leads) >= target:
                    break

                emit(f"[{market}] Scraping {source['name']}…")
                raw = []

                try:
                    if source["type"] == "builtwith":
                        raw = scrape_builtwith_shopify(
                            scrape_do_key, source["country"], source["market"]
                        )
                    elif source["type"] == "portfolio":
                        raw = scrape_portfolio_page(
                            scrape_do_key, source["url"],
                            source.get("exclude", ""), source["name"]
                        )
                    elif source["type"] == "article":
                        raw = scrape_article_page(
                            scrape_do_key, source["url"], source["name"]
                        )
                except Exception as e:
                    emit(f"[{market}] {source['name']} failed: {e}")
                    continue

                enriched = 0
                for r in raw[:80]:
                    if len(leads) >= target:
                        break
                    # Skip if we already have this domain
                    d = extract_domain(r.get("website", ""))
                    if d and d in seen_domains:
                        continue
                    # Get email if not already present
                    if not r.get("email"):
                        r["email"] = enrich_with_email(
                            r["website"], scrape_do_key, searlo_key
                        ) or ""
                    r["category"] = _guess_category(r.get("brand_name", ""))
                    r["market"]   = market
                    if add(r):
                        enriched += 1

                emit(f"[{market}] {source['name']} → +{enriched} leads ({len(leads)} total)")

        # ── Step 2: Google domain discovery ──────────────────────────────────
        if apify_key and len(leads) < target:
            queries = config.get("google_queries", [])
            needed  = (target - len(leads)) * 4   # fetch more domains than needed
            emit(f"[{market}] Google search ({len(queries)} queries, need ~{target - len(leads)} more)…")

            raw = find_domains_via_google(apify_key, queries, max_domains=min(needed, 500))
            emit(f"[{market}] Google found {len(raw)} domains — enriching emails…")

            enriched = 0
            for r in raw:
                if len(leads) >= target:
                    break
                d = extract_domain(r.get("website", ""))
                if d and d in seen_domains:
                    continue
                if not r.get("email"):
                    r["email"] = enrich_with_email(
                        r["website"], scrape_do_key, searlo_key
                    ) or ""
                r["category"] = _guess_category(r.get("brand_name", ""))
                r["market"]   = market
                if add(r):
                    enriched += 1

            emit(f"[{market}] Google enrichment done → +{enriched} leads ({len(leads)} total)")

        emit(f"[{market}] Complete — {len([l for l in leads if l.get('market') == market])} leads from {market}")

    emit(f"All markets done — {len(leads)} verified leads found")
    return leads[:target]
