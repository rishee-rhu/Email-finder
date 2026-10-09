"""
AI email generation v2 — Cold outreach sequence for Broti Dev.

Email structure (researched from 100 top-performing cold emails):
  Email 1 (Day 0)  : Problem → Actor → Solution → CTA  (personalised audit offer)
  Email 2 (Day 2)  : Gentle bump — resurfaces thread, one new hook
  Email 3 (Day 5)  : Value-add — relevant industry insight / mini case-study
  Email 4 (Day 8)  : Ultra-short yes/no question
  Email 5 (Day 12) : Breakup email (statistically highest reply rate in sequence)

Anti-spam rules baked into every prompt:
  ✓ Plain text only — no HTML, images, or heavy formatting
  ✓ Zero spam trigger words (FREE, GUARANTEE, ACT NOW, CLICK HERE, LIMITED TIME)
  ✓ Max 1 exclamation mark per email
  ✓ No all-caps words
  ✓ Under 200 words
  ✓ Single CTA only
  ✓ Soft unsubscribe line on Email 1
  ✓ Personalised subject (brand name or specific reference)
  ✓ Sounds human — peer to peer, not vendor to prospect
"""

DEFAULT_DOSSIER = """
NAME: Broti Dev
OFFER: AI-Assisted Content Writer & Strategist for D2C Brands
LOCATION: Kolkata, West Bengal, India

BACKGROUND:
- English Honours graduate with exceptional writing
- 14 years sales experience: HSBC (credit card activations + upsells) and
  3G Hutchison UK (telecom bundles) — customers sent appreciation emails because
  Broti matched them to the right product, not the most profitable one
- That instinct — lead with the problem, product comes second — is the
  foundation of conversion copywriting

WHAT I DELIVER:
1. Content audit: exact ₹/$/£ cost of their current content gap (free, no pitch)
2. Product page rewrites (emotional trigger → objection handling → CTA)
3. SEO blog content (4–6 posts/month, 1,500–2,500 words, keyword clusters)
4. Ad scripts for Google, Facebook, Instagram (15–20 variations/quarter)
5. Email sequences (welcome, abandoned cart, post-purchase, win-back)
6. Brand voice guide + AI prompt templates so their team can maintain consistency

TARGET CLIENT:
- India: D2C founders/marketing heads in skincare, fashion, jewellery, health,
  food, home décor doing ₹10–50 lakh/month
- USA/UK: DTC founders doing $10k–$500k/month struggling with content ROI

KEY MARKET INSIGHT (India): Google Ads CPCs rose 30–100% across Indian D2C in 2024.
Every brand in the ₹10–50L revenue band is under pressure. Organic content is
the moat they're already looking for.

KEY MARKET INSIGHT (USA/UK): The DTC bubble squeezed CAC. Brands that built
content audiences weathered it; pure paid-ads brands didn't. Content = resilience.

LEAD WITH: Free content audit — show the exact cost of their content gap BEFORE
mentioning paid work. Frame: "I'll show you exactly where your content is
costing you money."
"""

# ── Sequence timing (days to wait AFTER the previous email) ───────────────────
# Email 1 = Day 0, Email 2 = Day 3, Email 3 = Day 7, Email 4 = Day 12, Email 5 = Day 16.
# This MUST match db.FOLLOWUP_DELAYS (the scheduler uses that one to decide what's due).
SEQUENCE_DELAYS = {2: 3, 3: 4, 4: 5, 5: 4}

# ── Category pain points (used when research finds nothing) ───────────────────
CATEGORY_PAIN_POINTS = {
    "Skincare": (
        "Are your product pages explaining ingredients or selling transformation? "
        "Most skincare brands list the chemistry — but buyers decide in 8 seconds "
        "based on feeling, not formulation."
    ),
    "Fashion": (
        "Are your product photos doing all the work while the copy stays generic? "
        "Fashion brands lose 40% of potential buyers in the product description alone "
        "— not to price, not to competition."
    ),
    "Jewellery": (
        "Is your jewellery content selling the piece or the moment it creates? "
        "The brands that win in this category don't describe jewellery — they narrate "
        "the occasion it belongs to."
    ),
    "Health & Wellness": (
        "Are your customers reading your supplement labels trying to understand them? "
        "Health brands that translate science into real outcomes on their pages "
        "consistently convert 2–3x better."
    ),
    "Food & Beverage": (
        "Is your food brand selling product specs or the experience of eating it? "
        "The brands that lead in this category make you taste the product before you buy it."
    ),
    "Home & Living": (
        "Are your product pages describing dimensions when buyers are imagining rooms? "
        "Home décor brands that sell the lifestyle — not the product — convert far better."
    ),
    "Hair Care": (
        "Are your hair care pages listing ingredients when customers are searching for "
        "results? Bad hair days are emotional — your content should be too."
    ),
    "Pet Care": (
        "Is your pet brand talking to pet owners about formulations when they want to "
        "know their pet will be happy? Emotion beats science in pet care content every time."
    ),
    "Baby & Kids": (
        "Are you selling safety specs when parents are buying peace of mind? "
        "Baby brands that lead with reassurance rather than features consistently "
        "convert higher."
    ),
    "D2C": (
        "Is your content team spending more time producing content than your customers "
        "spend reading it? Most D2C brands publish but don't convert — the gap is usually "
        "in how the content is written, not how much of it there is."
    ),
    "D2C India": (
        "Google Ads CPCs in Indian D2C rose 30–100% last year. "
        "Are you paying more per click for the same customers? "
        "The brands building organic content now will own those customers "
        "without the ad spend in 6 months."
    ),
    "D2C USA": (
        "DTC brands that survived the paid-ads squeeze built content audiences. "
        "Is your brand's content working as hard as your ad budget — or harder?"
    ),
    "D2C UK": (
        "UK consumers are doing more research before every purchase. "
        "Is your content showing up when they search — or are you paying "
        "for ads to reach people who already have doubts?"
    ),
}

# ── Market context injected into Email 1 ─────────────────────────────────────
MARKET_CONTEXT = {
    "India": (
        "Reference currency as ₹. You may reference Indian platforms (Nykaa, Myntra, "
        "Amazon India, Shopify India) or media (Inc42, Shark Tank India) where relevant. "
        "Avoid 'Hi there' — use 'Hi {contact_name}' or just launch into the email."
    ),
    "USA": (
        "Reference currency as $. You may reference US platforms (Amazon, Shopify, "
        "Product Hunt) or media (TechCrunch, DTC Newsletter) where relevant. "
        "Tone: direct, American business casual. No 'I hope this finds you well'."
    ),
    "UK": (
        "Reference currency as £. You may reference UK context (cost-of-living squeeze, "
        "UK consumer research habits). Tone: professional but warm, British business style. "
        "No 'I hope this email finds you well'."
    ),
}

# ── Anti-spam rules appended to every prompt ─────────────────────────────────
ANTISPAM_RULES = """
ANTI-SPAM & DELIVERABILITY RULES (non-negotiable):
- Plain text only. No HTML, no bullet symbols (•), no bold/italic markdown
- NEVER use these words: FREE, GUARANTEE, ACT NOW, CLICK HERE, LIMITED TIME,
  WINNER, CONGRATULATIONS, CASH, PRIZE, URGENT, EARN MONEY, MAKE MONEY
- Replace "free" with "complimentary" or rephrase naturally
- Maximum 1 exclamation mark in the entire email (ideally zero)
- No ALL CAPS words except proper nouns
- Under 200 words total
- One call-to-action only — no multiple asks
- One link maximum (or none)
- No attachments referenced
- End with a natural sign-off: "[sender_name]" only, no "Best regards" boilerplate
- Write like a person emailing a person, not a marketer emailing a list
"""

# ── Subject line guidance (researched from 100 top cold emails) ──────────────
SUBJECT_GUIDE = """
SUBJECT LINE RULES (based on top-performing cold emails):
- Under 7 words ideally
- Must NOT look like marketing (no brackets, no emojis, no "RE:" trick)
- Good patterns:
  * Specific observation: "[Brand] — one thing I noticed on your site"
  * Direct question: "Is [pain point] a problem for [Brand]?"
  * Intrigue: "Your [category] content — quick thought"
  * Peer-to-peer: "[Brand] content audit — worth 2 min?"
  * Compliment + hook: "Noticed [Brand] on [platform] — one suggestion"
- Bad patterns (avoid): "Quick question", "Following up", "Just checking in",
  "Did you see my email?", "Are you the right person?"
- The subject must relate directly to the email content
"""

# ── Single-call sequence prompt (all 5 emails in ONE request = ~80% fewer tokens) ─

SYSTEM_PROMPT = """You are an expert cold-email copywriter. You write short, human,
peer-to-peer emails that earn replies. You never sound like a marketer, never use
spam words, and you personalise from real evidence only — never invented facts."""

SEQUENCE_PROMPT = """Write a 5-email cold outreach sequence for ONE prospect.
Write as {sender_name} — a real person emailing another person.

ABOUT ME (my offer — base every email on this):
{dossier}

THE PROSPECT:
- Brand: {brand_name}
- Category: {category}
- Market: {market} — {market_context}
- Website: {website}

WHAT I CAN ACTUALLY SEE ABOUT THEM ONLINE (use for specific personalisation;
do NOT invent anything beyond this):
{signals_block}

If the visible info is thin, open Email 1 on this category pain instead of
inventing specifics:
{pain_point}

WRITE EXACTLY 5 EMAILS:

EMAIL 1 — the opener (UNDER 120 words). Six beats, in order:
 1) Hook: one specific line about THEM using a real signal above. Never "I hope this finds you well".
 2) Problem stated AS A QUESTION that makes them pause.
 3) FOMO: one line that peers in {category} are pulling ahead.
 4) Solution + a one-liner offer in the form "I will [specific result] — [light risk-reversal]" + ONE short credibility line.
 5) One clear, easy-to-say-yes CTA.
 6) Tiny opt-out on its own last line: "Reply 'not relevant' and I'll stop."
EMAIL 2 — Day +3, 50-70 words. A gentle bump with ONE new angle. Never "just following up".
EMAIL 3 — Day +7, 90-120 words. Lead with one real {category}/{market} insight, tie it to them, soft CTA.
EMAIL 4 — Day +12, 40-60 words. A single yes/no question, light humour about the earlier emails.
EMAIL 5 — Day +16, 70-90 words. Breakup email: leave the door open + one genuine parting insight.

RULES for every email:
- Plain text only. No markdown, no bullet symbols, no greasy sales tone.
- Banned words: free, guarantee, act now, limited time, click here, winner, cash, urgent, congratulations. Max ONE "!" in the whole email.
- Each email a DIFFERENT subject line: short, specific or curious. Never "Quick question" or "Following up".
- Sign EVERY email as exactly: {sender_name}

Return STRICT JSON only (no commentary), shape:
{{"1":{{"subject":"...","body":"..."}},"2":{{"subject":"...","body":"..."}},"3":{{"subject":"...","body":"..."}},"4":{{"subject":"...","body":"..."}},"5":{{"subject":"...","body":"..."}}}}"""


def _call_ai_json(prompt, provider, api_key):
    """One call, JSON back."""
    if provider == "openai":
        from openai import OpenAI
        r = OpenAI(api_key=api_key).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        return r.choices[0].message.content
    elif provider == "claude":
        import anthropic
        r = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text
    raise ValueError(f"Unknown AI provider: {provider}")


def _coerce_json(text):
    import json
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        text = text[s:e + 1]
    return json.loads(text)


def _signals_block(lead, signals, research_facts):
    lines = []
    if lead.get("contact_name"):
        lines.append(f"Contact person — address them by first name: {lead['contact_name']}")
    signals = signals or lead.get("signals") or {}
    soc = signals.get("social") or {}
    if soc:
        lines.append("Social channels linked on their site: " + ", ".join(soc.keys()))
    elif signals:
        lines.append("No social channels linked on their homepage")
    if signals.get("hasBlog") is not None:
        lines.append("Has a blog/content section: " + ("yes" if signals.get("hasBlog") else "no"))
    if signals.get("title"):
        lines.append("Homepage title: " + str(signals["title"])[:140])
    if signals.get("description"):
        lines.append("Homepage description: " + str(signals["description"])[:200])
    for f in (research_facts or []):
        if f:
            lines.append(str(f))
    return "\n".join(f"- {s}" for s in lines) if lines else "- (Little public info available.)"


# ── Public API ────────────────────────────────────────────────────────────────

def generate_sequence(
    lead,
    dossier=None,
    provider="openai",
    api_key=None,
    sender_name="",
    research_facts=None,
    signals=None,
):
    """
    Generate all 5 emails for a lead in ONE AI call.
    signals: dict of scraped site signals (social, hasBlog, title, description).
    research_facts: optional extra facts to weave in.
    Returns {1:{subject,body,spam_*}, ..., 5:{...}}.
    """
    import spam_check

    dossier = dossier or DEFAULT_DOSSIER
    market  = lead.get("market", "India")
    cat     = lead.get("category", "D2C")
    pain = CATEGORY_PAIN_POINTS.get(cat) or CATEGORY_PAIN_POINTS.get(
        f"D2C {market}", CATEGORY_PAIN_POINTS["D2C"])
    mkt_ctx = MARKET_CONTEXT.get(market, MARKET_CONTEXT["India"])

    prompt = SEQUENCE_PROMPT.format(
        sender_name=sender_name or "Me",
        dossier=dossier,
        brand_name=lead.get("brand_name", "your brand"),
        category=cat,
        market=market,
        market_context=mkt_ctx,
        website=lead.get("website", ""),
        signals_block=_signals_block(lead, signals, research_facts),
        pain_point=pain,
    )

    data = {}
    try:
        data = _coerce_json(_call_ai_json(prompt, provider, api_key))
    except Exception as e:
        print(f"[email_gen] {lead.get('brand_name')}: {e}")

    brand = lead.get("brand_name", "you")
    result = {}
    for step in range(1, 6):
        em = data.get(str(step)) or data.get(step) or {}
        subject = (em.get("subject") or f"A quick note for {brand}").strip()
        body = (em.get("body") or "").strip() or "[generation failed — edit before sending]"
        subject, body, _ = spam_check.auto_fix(subject, body)
        rep = spam_check.check(subject, body)
        result[step] = {
            "subject": subject, "body": body,
            "spam_score": rep["score"], "spam_ok": rep["ok"],
            "spam_issues": rep["issues"],
        }
    return result
