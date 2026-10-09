"""
API balance checker — fetches remaining credits/quota for each configured API.
Returns structured dicts so the dashboard can display them.
"""
import requests


def check_openai(api_key):
    """Returns remaining credit info from OpenAI billing API."""
    if not api_key:
        return {"label": "OpenAI", "status": "not_configured", "display": "Not set"}
    try:
        # OpenAI usage endpoint
        r = requests.get(
            "https://api.openai.com/v1/dashboard/billing/subscription",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            hard = data.get("hard_limit_usd", 0)
            soft = data.get("soft_limit_usd", 0)
            return {
                "label":   "OpenAI",
                "status":  "ok",
                "display": f"${soft:.2f} soft limit / ${hard:.2f} hard limit",
                "detail":  "Check platform.openai.com/usage for exact spend",
            }
        elif r.status_code == 401:
            return {"label": "OpenAI", "status": "error", "display": "Invalid API key"}
        else:
            return {"label": "OpenAI", "status": "unknown",
                    "display": "Connected (balance unavailable via API)"}
    except Exception as e:
        return {"label": "OpenAI", "status": "error", "display": str(e)[:60]}


def check_anthropic(api_key):
    """Anthropic does not expose a balance API — confirm key is valid only."""
    if not api_key:
        return {"label": "Anthropic", "status": "not_configured", "display": "Not set"}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        # Cheapest possible call to verify key
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {
            "label":   "Anthropic",
            "status":  "ok",
            "display": "Key valid — check console.anthropic.com for balance",
        }
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower():
            return {"label": "Anthropic", "status": "error", "display": "Invalid API key"}
        return {"label": "Anthropic", "status": "error", "display": msg[:60]}


def check_apify(api_key):
    """Returns Apify compute units remaining."""
    if not api_key:
        return {"label": "Apify", "status": "not_configured", "display": "Not set"}
    try:
        r = requests.get(
            "https://api.apify.com/v2/users/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            plan = data.get("plan", {})
            used = data.get("monthlyUsage", {})
            cu_limit = plan.get("monthlyUsageCreditUsdLimit", 0)
            cu_used  = used.get("ACTOR_COMPUTE_UNITS", {}).get("usdCost", 0)
            cu_left  = max(0, cu_limit - cu_used)
            return {
                "label":   "Apify",
                "status":  "ok",
                "display": f"${cu_left:.2f} remaining this month (${cu_used:.2f} used of ${cu_limit:.2f})",
                "pct_used": round(cu_used / max(cu_limit, 0.01) * 100, 1),
            }
        elif r.status_code == 401:
            return {"label": "Apify", "status": "error", "display": "Invalid API key"}
        return {"label": "Apify", "status": "unknown", "display": "Connected (balance unavailable)"}
    except Exception as e:
        return {"label": "Apify", "status": "error", "display": str(e)[:60]}


def check_scrape_do(api_key):
    """Returns Scrape.do remaining API calls."""
    if not api_key:
        return {"label": "Scrape.do", "status": "not_configured", "display": "Not set"}
    try:
        r = requests.get(
            f"https://api.scrape.do/info?token={api_key}",
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            remaining = data.get("remainingMonthlyRequests") or data.get("remaining", "?")
            total     = data.get("monthlyRequests") or data.get("total", "?")
            return {
                "label":   "Scrape.do",
                "status":  "ok",
                "display": f"{remaining} calls left this month (of {total})",
            }
        return {"label": "Scrape.do", "status": "unknown",
                "display": "Connected (quota unavailable via API)"}
    except Exception as e:
        return {"label": "Scrape.do", "status": "error", "display": str(e)[:60]}


def check_searlo(api_key):
    """Returns Searlo.tech credit balance."""
    if not api_key:
        return {"label": "Searlo.tech", "status": "not_configured", "display": "Not set"}
    try:
        r = requests.get(
            "https://api.searlo.tech/balance",
            params={"apiKey": api_key},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            credits = data.get("credits") or data.get("balance") or data.get("remaining", "?")
            return {
                "label":   "Searlo.tech",
                "status":  "ok",
                "display": f"{credits} lookups remaining",
            }
        return {"label": "Searlo.tech", "status": "unknown",
                "display": "Connected (balance unavailable via API)"}
    except Exception as e:
        return {"label": "Searlo.tech", "status": "error", "display": str(e)[:60]}


def check_all(ai_provider, ai_key, apify_key, scrape_do_key, searlo_key):
    """Check all configured APIs and return list of balance dicts."""
    results = []

    if ai_provider == "openai":
        results.append(check_openai(ai_key))
    elif ai_provider == "claude":
        results.append(check_anthropic(ai_key))

    if apify_key:
        results.append(check_apify(apify_key))
    if scrape_do_key:
        results.append(check_scrape_do(scrape_do_key))
    if searlo_key:
        results.append(check_searlo(searlo_key))

    return results
