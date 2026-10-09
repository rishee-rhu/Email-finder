"""
API key tester — called during onboarding to validate each key immediately.
Returns {"ok": bool, "message": str} for each key.
"""
import requests


def test_openai(api_key):
    if not api_key:
        return {"ok": False, "message": "No key entered"}
    try:
        from openai import OpenAI
        OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return {"ok": True, "message": "Connected — gpt-4o-mini responding"}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Incorrect API key" in msg:
            return {"ok": False, "message": "Invalid API key"}
        if "quota" in msg.lower() or "429" in msg:
            return {"ok": False, "message": "Key valid but quota exceeded — add credits"}
        return {"ok": False, "message": msg[:80]}


def test_anthropic(api_key):
    if not api_key:
        return {"ok": False, "message": "No key entered"}
    try:
        import anthropic
        anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"ok": True, "message": "Connected — Claude Haiku responding"}
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower():
            return {"ok": False, "message": "Invalid API key"}
        return {"ok": False, "message": msg[:80]}


def test_apify(api_key):
    if not api_key:
        return {"ok": False, "message": "No key entered — Apify is optional"}
    try:
        r = requests.get(
            "https://api.apify.com/v2/users/me",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            plan = data.get("plan", {}).get("id", "unknown")
            return {"ok": True, "message": f"Connected — plan: {plan}"}
        if r.status_code == 401:
            return {"ok": False, "message": "Invalid API key"}
        return {"ok": False, "message": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:80]}


def test_scrape_do(api_key):
    if not api_key:
        return {"ok": False, "message": "No key entered — Scrape.do is optional"}
    try:
        r = requests.get(
            "https://api.scrape.do/info",
            params={"token": api_key},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            rem  = data.get("remainingMonthlyRequests", data.get("remaining", "?"))
            return {"ok": True, "message": f"Connected — {rem} calls remaining"}
        if r.status_code in (401, 403):
            return {"ok": False, "message": "Invalid API key"}
        # Some plans return 200 even without balance info
        return {"ok": True, "message": "Connected (quota details unavailable)"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:80]}


def test_searlo(api_key):
    if not api_key:
        return {"ok": False, "message": "No key entered — Searlo is optional"}
    try:
        r = requests.get(
            "https://api.searlo.tech/balance",
            params={"apiKey": api_key},
            timeout=8,
        )
        if r.status_code == 200:
            data    = r.json()
            credits = data.get("credits") or data.get("balance") or data.get("remaining", "?")
            return {"ok": True, "message": f"Connected — {credits} lookups remaining"}
        if r.status_code in (401, 403):
            return {"ok": False, "message": "Invalid API key"}
        return {"ok": True, "message": "Connected (balance details unavailable)"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:80]}


def test_all(provider, ai_key, apify_key, scrape_do_key, searlo_key):
    """Test all keys and return results dict."""
    results = {}
    if provider == "openai":
        results["OpenAI"]     = test_openai(ai_key)
    else:
        results["Anthropic"]  = test_anthropic(ai_key)
    results["Apify"]      = test_apify(apify_key)
    results["Scrape.do"]  = test_scrape_do(scrape_do_key)
    results["Searlo"]     = test_searlo(searlo_key)
    return results
