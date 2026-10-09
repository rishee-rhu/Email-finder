"""
Email verifier — free, no extra API keys.

Two checks:
  1. Syntax  — valid email format (regex, RFC-ish)
  2. Domain  — the domain has MX records (i.e. it can receive mail)

This catches obvious junk (typos, dead domains, role/no-reply addresses)
without a paid verification service. It does NOT confirm the specific
inbox exists — that needs SMTP probing or a service like NeverBounce.
Accuracy in practice: ~80-85%.

MX lookups use dnspython if available; if not installed it degrades to a
syntax + domain-shape check only (and says so in the reason).
"""
import re
import socket

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Addresses that are valid but useless for cold outreach
ROLE_PREFIXES = (
    "noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster",
    "abuse", "spam", "bounce", "notifications", "automated",
)

# free / disposable domains we still allow but flag as lower quality
FREE_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                "icloud.com", "aol.com", "proton.me", "protonmail.com"}

_MX_CACHE = {}


def _has_mx(domain):
    """Return (has_mx: bool, checked: bool). checked=False if dnspython missing."""
    if domain in _MX_CACHE:
        return _MX_CACHE[domain], True
    try:
        import dns.resolver  # dnspython
    except Exception:
        return True, False   # can't check — assume ok, mark as unchecked

    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5
        answers = resolver.resolve(domain, "MX")
        ok = len(answers) > 0
    except Exception:
        # No MX — try A record as a fallback (some domains receive mail on A)
        try:
            socket.gethostbyname(domain)
            ok = True
        except Exception:
            ok = False
    _MX_CACHE[domain] = ok
    return ok, True


def verify(email):
    """
    Verify a single email.
    Returns dict:
      {
        "email": str,
        "valid": bool,        # passes syntax + (MX if checkable)
        "quality": "good" | "free" | "role" | "invalid",
        "reason": str,
        "mx_checked": bool,
      }
    """
    email = (email or "").strip().lower()

    if not email or not EMAIL_RE.match(email):
        return {"email": email, "valid": False, "quality": "invalid",
                "reason": "bad email format", "mx_checked": False}

    local, _, domain = email.partition("@")

    # Role / no-reply addresses
    if any(local.startswith(p) for p in ROLE_PREFIXES):
        return {"email": email, "valid": False, "quality": "role",
                "reason": f"role address ({local}@) — not a person", "mx_checked": False}

    has_mx, checked = _has_mx(domain)
    if checked and not has_mx:
        return {"email": email, "valid": False, "quality": "invalid",
                "reason": f"domain {domain} has no mail server (won't deliver)",
                "mx_checked": True}

    quality = "free" if domain in FREE_DOMAINS else "good"
    reason  = ("domain accepts mail" if checked
               else "format ok (MX not checked — install dnspython for domain check)")
    if quality == "free":
        reason += "; personal mailbox (lower reply rate than a brand domain)"

    return {"email": email, "valid": True, "quality": quality,
            "reason": reason, "mx_checked": checked}


# Apify actor that does real SMTP verification from Apify's servers (port 25 open).
APIFY_VERIFY_ACTOR = "michael.g~email-verifier-validator"


def verify_via_apify(apify_key, emails, on_progress=None, strict=False):
    """
    Verify emails using an Apify SMTP actor — works where local port 25 is blocked.
    Returns {email: {"valid": bool, "label": str}}.
    'catch_all' counts as valid for SENDING (the server accepts mail → no hard bounce).

    strict=True (use for GUESSED emails): if the SMTP actor is unavailable we return
    {} rather than a local-MX guess — so unverifiable guesses are skipped, never sent.
    strict=False: fall back to the local MX check.
    """
    emails = list(dict.fromkeys((e or "").lower().strip() for e in emails if e))
    if not emails:
        return {}
    if not apify_key:
        return {} if strict else {e: _simple(verify(e)) for e in emails}

    import lead_finder
    try:
        items = lead_finder._apify_run(
            apify_key, APIFY_VERIFY_ACTOR, {"emails": emails}, timeout=300)
    except Exception as e:
        if on_progress:
            on_progress(f"Apify SMTP verify unavailable ({e})", 0)
        return {} if strict else {e: _simple(verify(e)) for e in emails}

    out = {}
    ok_status = {"good", "valid", "deliverable", "ok", "risky", "accept_all", "acceptall"}
    for it in items or []:
        em = (it.get("email") or it.get("address") or "").lower()
        if not em:
            continue
        # michael.g actor schema: status good/bad, technical_status valid/invalid,
        # verification_details.verdict.is_valid, catch_all flag.
        tech = str(it.get("technical_status") or "").lower()
        status = str(it.get("status") or it.get("result") or it.get("label") or "").lower()
        verdict = (it.get("verification_details") or {}).get("verdict") or {}
        is_valid = verdict.get("is_valid")
        if is_valid is None:
            is_valid = it.get("valid")
        if is_valid is None:
            is_valid = tech in ("valid", "deliverable", "ok") or status in ok_status
        valid = bool(is_valid) or bool(it.get("catch_all"))   # catch-all won't hard-bounce
        out[em] = {"valid": valid, "label": tech or status or ("valid" if valid else "unknown")}

    # anything the actor skipped → local fallback
    for e in emails:
        out.setdefault(e, _simple(verify(e)))
    return out


def _simple(res):
    return {"valid": res.get("valid", False), "label": res.get("quality", "")}


def verify_batch(emails, on_progress=None):
    """
    Verify a list of emails.
    Returns (valid_list, results_dict) where results_dict[email] = verify() result.
    on_progress(done, total) optional callback.
    """
    results = {}
    valid = []
    total = len(emails)
    for i, e in enumerate(emails):
        res = verify(e)
        results[e] = res
        if res["valid"]:
            valid.append(e)
        if on_progress:
            on_progress(i + 1, total)
    return valid, results
