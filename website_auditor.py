"""
Website / online-presence auditor.

After emails are found, this checks what is VISIBLE online about each brand in
the channel the user actually serves — so Email 1 can reference real gaps.

Key idea (from the user's brief):
  - Some services are visible online (social media, website content, blog, SEO)
    → audit them, personalise the pitch with what's missing.
  - Some services are NOT visible online (virtual assistant, inbox/calendar,
    bookkeeping) → skip the audit, there's nothing to see.

Whether a dossier is auditable-online is decided by target_profiler (the
`audit` block). This module runs only when that says auditable_online = true.

Flow:
  1. Batch-scrape every brand homepage via Apify (one run) → signals
     (which social channels they link, blog presence, meta description).
  2. Per brand, ask OpenAI to turn those signals + the audit focus into
     2-3 concrete, evidence-based observations (no invented metrics).
These observations are merged into the email's personalisation facts.
"""
import lead_finder   # reuse _apify_run + extract_domain

# cheerio pageFunction: collect presence signals from a homepage
_AUDIT_PAGE_FN = (
    "async function pageFunction(context){"
    " const { $, request } = context;"
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
    " return { url: request.url, title: $('title').text().slice(0,200),"
    "  description: ($('meta[name=description]').attr('content')||'').slice(0,300),"
    "  social: social, hasBlog: hasBlog,"
    "  textLength: $('body').text().replace(/\\s+/g,' ').length };"
    "}"
)

AUDIT_PROMPT = """You are auditing a brand's PUBLIC online presence to personalise a cold email.

MY SERVICE FOCUS (what I help with): {audit_focus}
BRAND: {brand_name}
WHAT I CAN SEE ON THEIR SITE (evidence only — do not assume beyond this):
- Homepage title: {title}
- Meta description: {description}
- Social channels linked: {social}
- Has a blog: {has_blog}

Give 2-3 SHORT, specific observations relevant to my service focus, based ONLY on
the evidence above. Rules:
- Do NOT invent metrics (no "posts 2x a month", no engagement numbers) — you cannot see those.
- If a relevant channel is MISSING or thin, say so plainly (that's the opening).
- If they already do it well, say that too (so I don't pitch the wrong thing).
- Each observation is one line, factual, useful for a pitch.

Then add a final line exactly:
OPPORTUNITY: high | medium | low
(high = clear gap I can fill, low = they already handle this well)

Return as:
- observation 1
- observation 2
OPPORTUNITY: <level>"""


def _call_ai(prompt, provider, api_key):
    if provider == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=200,
        )
        return r.choices[0].message.content.strip()
    import anthropic
    r = anthropic.Anthropic(api_key=api_key).messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=200,
        messages=[{"role": "user", "content": prompt}])
    return r.content[0].text.strip()


def gather_signals_batch(apify_key, websites, on_progress=None):
    """Scrape all homepages in one Apify run → {domain: signals}."""
    if not apify_key or not websites:
        return {}
    start_urls = []
    seen = set()
    for w in websites:
        d = lead_finder.extract_domain(w)
        if not d or d in seen:
            continue
        seen.add(d)
        base = (w if w.startswith("http") else f"https://{d}").rstrip("/")
        start_urls.append({"url": base})
    if not start_urls:
        return {}
    if on_progress:
        on_progress(f"Auditing {len(start_urls)} brand sites via Apify…", 0)
    try:
        items = lead_finder._apify_run(
            apify_key, "apify~cheerio-scraper",
            {"startUrls": start_urls, "pageFunction": _AUDIT_PAGE_FN,
             "maxConcurrency": 10, "maxRequestsPerCrawl": len(start_urls) + 5,
             "ignoreSslErrors": True,
             "proxyConfiguration": {"useApifyProxy": True}},
            timeout=300)
    except Exception as e:
        if on_progress:
            on_progress(f"Audit scrape error: {e}", 0)
        return {}
    out = {}
    for it in items or []:
        d = lead_finder.extract_domain(it.get("url", ""))
        if d:
            out[d] = it
    return out


def audit_brand(signals, audit_focus, brand_name, provider="openai", api_key=None):
    """Turn raw signals into findings. Returns {'findings': [...], 'opportunity': str}."""
    social = signals.get("social") or {}
    social_str = ", ".join(social.keys()) if social else "none found"
    prompt = AUDIT_PROMPT.format(
        audit_focus=audit_focus, brand_name=brand_name,
        title=signals.get("title", "")[:200],
        description=signals.get("description", "")[:300],
        social=social_str, has_blog="yes" if signals.get("hasBlog") else "no")
    findings, opportunity = [], "medium"
    if not api_key:
        # No AI — at least report channel presence factually
        if social:
            findings.append(f"Links these channels: {social_str}")
        else:
            findings.append("No social channels linked on the homepage")
        return {"findings": findings, "opportunity": "high" if not social else "medium"}
    try:
        text = _call_ai(prompt, provider, api_key)
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("OPPORTUNITY:"):
                opportunity = line.split(":", 1)[1].strip().lower().split()[0]
            elif line.startswith("- ") and len(line) > 4:
                findings.append(line[2:].strip())
    except Exception:
        if social:
            findings.append(f"Links these channels: {social_str}")
    return {"findings": findings[:3], "opportunity": opportunity}


def audit_batch(apify_key, leads, audit_focus, provider="openai", api_key=None,
                on_progress=None):
    """
    Audit a list of leads. Returns {email: {"findings": [...], "opportunity": str,
    "social": {...}}}.
    """
    websites = [l.get("website", "") for l in leads]
    signals_by_domain = gather_signals_batch(apify_key, websites, on_progress)

    out = {}
    total = len(leads)
    for i, lead in enumerate(leads):
        d = lead_finder.extract_domain(lead.get("website", ""))
        sig = signals_by_domain.get(d, {})
        res = audit_brand(sig, audit_focus, lead.get("brand_name", ""), provider, api_key)
        res["social"] = sig.get("social") or {}
        out[lead["email"]] = res
        if on_progress:
            on_progress(f"Audited {i+1}/{total}…", i + 1)
    return out
