"""
Company researcher — uses AI (OpenAI / Claude) to find real facts about a brand.

Why AI instead of Apify Google?
  - ~$0.0001 per brand (gpt-4o-mini) vs Apify compute units
  - No extra API key needed — reuses the AI key already in Settings
  - Works for most established brands (training data covers news up to mid-2024)
  - Falls back gracefully if brand is too new or niche to be indexed

Returns 1–2 real, confident facts to personalise Email 1.
"""

RESEARCH_PROMPT = """I am writing a personalised cold email to {brand_name}, a {category} brand.
Website: {website}

From your training data, what do you know about this brand? I need:
1. Any funding rounds, investment, or valuation news
2. Recent product launches, expansions, or collaborations
3. Notable achievements, awards, or press coverage (Inc42, YourStory, TechCrunch, etc.)
4. Revenue scale or growth indicators if known

STRICT RULES:
- Only include facts you are CONFIDENT about from your training data
- Do NOT speculate, infer, or make anything up
- If you don't know this specific brand, just say "Insufficient data"
- Maximum 2 bullet points
- Each bullet must be a concrete, specific fact (not generic observations)
- No company description or background — only NEWS/EVENTS/ACHIEVEMENTS

Respond in this exact format:
FACTS:
- [specific fact 1, or "Insufficient data"]
- [specific fact 2, optional]
CONFIDENCE: [high / medium / low]"""


def research_brand(brand_name, website="", category="D2C",
                   api_key=None, provider="openai"):
    """
    Use AI to surface real facts about a brand from training data.
    Returns {"facts": [...], "found": bool}
    """
    if not api_key or not brand_name:
        return {"facts": [], "found": False}

    prompt = RESEARCH_PROMPT.format(
        brand_name=brand_name,
        category=category,
        website=website or "unknown",
    )

    try:
        text = _call_ai(prompt, provider, api_key)
        facts = _parse_facts(text)
        return {"facts": facts, "found": bool(facts)}

    except Exception as e:
        print(f"[researcher] {brand_name}: {e}")
        return {"facts": [], "found": False}


def _call_ai(prompt, provider, api_key):
    if provider == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        return r.choices[0].message.content.strip()

    elif provider == "claude":
        import anthropic
        r = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text.strip()

    return ""


def _parse_facts(text):
    """Extract bullet points from AI response, filtering out low-confidence results."""
    facts = []
    skip_phrases = [
        "insufficient data", "don't know", "not aware", "no information",
        "unable to find", "i cannot", "no specific", "not familiar",
        "limited information", "no data",
    ]
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") and len(line) > 15:
            fact = line[2:].strip()
            if not any(p in fact.lower() for p in skip_phrases):
                facts.append(fact)
    return facts[:2]
