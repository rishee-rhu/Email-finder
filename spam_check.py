"""
Spam trigger checker — scans a cold email before it is sent.

Based on the deliverability rules from the cold-email course:
  - Flags spam trigger words (urgency, discount, guarantee, overpromising)
  - Flags excessive punctuation (!!!, ???) and ALL-CAPS shouting
  - Suggests safe alternatives
  - Scores deliverability 1-10
  - Optional AI rewrite that keeps the persuasion but strips the flags

No API key needed for the rule-based check. The AI optimiser reuses the
OpenAI key already in Settings.
"""
import re

# ── Trigger word map: bad word → safe alternative ─────────────────────────────
TRIGGER_WORDS = {
    # urgency
    "act now": "let's discuss",
    "don't miss out": "good fit",
    "limited time": "this month",
    "hurry": "when you're ready",
    "last chance": "whenever suits you",
    "deadline": "timeline",
    "expires": "available now",
    "urgent": "quick",
    "final notice": "last note",
    # discount
    "free": "complimentary",
    "discount": "rate",
    "cheap": "cost-effective",
    "sale": "offer",
    "bargain": "value",
    "lowest price": "fair rate",
    "save money": "reduce costs",
    # guarantee
    "guarantee": "promise",
    "guaranteed": "committed",
    "risk-free": "no obligation",
    "no risk": "no obligation",
    "money-back": "refund",
    "100% guaranteed": "fully committed",
    # overpromising
    "make $": "earn",
    "get rich": "grow revenue",
    "quick money": "added revenue",
    "secret": "approach",
    "unbeatable": "strong",
    "incredible opportunity": "worth exploring",
    "click here": "reply",
    "winner": "selected",
    "congratulations": "well done",
    "cash": "revenue",
    "prize": "result",
    # emotional manipulation
    "don't delete": "",
    "you must respond": "whenever you have a moment",
    "click or lose": "reply if useful",
}

# Words that are only a problem in ALL CAPS or with heavy emphasis
CAPS_RE   = re.compile(r"\b[A-Z]{4,}\b")
BANG_RE   = re.compile(r"!{2,}")
QMARK_RE  = re.compile(r"\?{2,}")
MULTI_BANG = re.compile(r"!")


def check(subject, body):
    """
    Rule-based spam scan.
    Returns dict:
      {
        "score": int (1-10, higher = safer),
        "issues": [ {type, found, suggestion} ],
        "ok": bool  (score >= 7 and no hard blockers),
      }
    """
    text = f"{subject}\n{body}"
    low  = text.lower()
    issues = []

    # 1. Trigger words
    for bad, good in TRIGGER_WORDS.items():
        if bad in low:
            issues.append({
                "type": "trigger_word",
                "found": bad,
                "suggestion": f'replace "{bad}" with "{good}"' if good else f'remove "{bad}"',
            })

    # 2. Excessive punctuation
    if BANG_RE.search(text):
        issues.append({"type": "punctuation", "found": "!! (multiple)",
                       "suggestion": "use a single full stop"})
    if QMARK_RE.search(text):
        issues.append({"type": "punctuation", "found": "?? (multiple)",
                       "suggestion": "use a single question mark"})

    # 3. Too many exclamation marks overall (>1 in whole email)
    bang_count = len(MULTI_BANG.findall(text))
    if bang_count > 1:
        issues.append({"type": "punctuation", "found": f"{bang_count} exclamation marks",
                       "suggestion": "keep at most one exclamation mark"})

    # 4. ALL CAPS shouting (ignore common acronyms)
    allow_caps = {"D2C", "DTC", "AI", "SEO", "CEO", "CTO", "CPC", "ROI",
                  "UGC", "DM", "USA", "UK", "GST", "NRI", "CTA", "SaaS", "B2B"}
    for w in CAPS_RE.findall(text):
        if w not in allow_caps:
            issues.append({"type": "all_caps", "found": w,
                           "suggestion": f'use normal case for "{w}"'})

    # 5. Length (cold emails should be tight)
    word_count = len(body.split())
    if word_count > 200:
        issues.append({"type": "length", "found": f"{word_count} words",
                       "suggestion": "trim to under 160 words"})

    # ── Score ─────────────────────────────────────────────────────────────────
    trigger_hits = sum(1 for i in issues if i["type"] == "trigger_word")
    punct_hits   = sum(1 for i in issues if i["type"] == "punctuation")
    caps_hits    = sum(1 for i in issues if i["type"] == "all_caps")

    score = 10
    score -= trigger_hits * 2      # trigger words hurt most
    score -= punct_hits * 1
    score -= caps_hits * 1
    if word_count > 200:
        score -= 1
    score = max(1, min(10, score))

    return {
        "score": score,
        "issues": issues,
        "ok": score >= 7 and trigger_hits == 0,
        "word_count": word_count,
    }


def auto_fix(subject, body):
    """
    Rule-based auto-fix: swap trigger words for safe alternatives and
    collapse excessive punctuation. Returns (new_subject, new_body, changes).
    This is deterministic — no API call. For deeper rewrites use ai_optimise().
    """
    changes = []

    def fix_text(t):
        out = t
        for bad, good in TRIGGER_WORDS.items():
            # case-insensitive whole-phrase replace
            pattern = re.compile(re.escape(bad), re.IGNORECASE)
            if pattern.search(out):
                out = pattern.sub(good, out)
                changes.append(f'"{bad}" → "{good}"' if good else f'removed "{bad}"')
        out = BANG_RE.sub("!", out)
        out = QMARK_RE.sub("?", out)
        return out

    return fix_text(subject), fix_text(body), changes


AI_OPTIMISE_PROMPT = """Check this cold email for spam trigger words and optimise it for deliverability.

1. Remove any spam trigger words, excessive punctuation, or ALL-CAPS shouting
2. Keep the persuasive impact and the 6-step structure intact
3. Keep it under 160 words
4. Do not add buzzwords or salesy language

Return ONLY the optimised email in this exact format:
SUBJECT: [subject]

[body]

Email to fix:
SUBJECT: {subject}

{body}"""


def ai_optimise(subject, body, provider="openai", api_key=None):
    """
    Optional: send the email to the AI to rewrite away spam flags while keeping
    the message. Returns (new_subject, new_body). Falls back to auto_fix on error.
    """
    if not api_key:
        s, b, _ = auto_fix(subject, body)
        return s, b

    prompt = AI_OPTIMISE_PROMPT.format(subject=subject, body=body)
    try:
        if provider == "openai":
            from openai import OpenAI
            r = OpenAI(api_key=api_key).chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=500,
            )
            text = r.choices[0].message.content.strip()
        else:
            import anthropic
            r = anthropic.Anthropic(api_key=api_key).messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = r.content[0].text.strip()

        # parse SUBJECT: / body
        new_subj, new_body, in_body = subject, [], False
        for line in text.splitlines():
            if line.upper().startswith("SUBJECT:"):
                new_subj = line.split(":", 1)[1].strip()
                in_body = True
                continue
            if in_body:
                new_body.append(line)
        body_out = "\n".join(new_body).strip() or body
        return new_subj, body_out
    except Exception:
        s, b, _ = auto_fix(subject, body)
        return s, b
