"""
Reply classifier — reads a prospect's reply and labels it.

Used after the app detects a reply, so the dashboard can show not just
"they replied" but WHAT kind of reply it was:
  sentiment : positive | negative | neutral
  label     : interested | not_interested | question | referral |
              auto_reply | unsubscribe | other

Reuses the OpenAI key already in Settings. Falls back to a keyword
heuristic if no key / the call fails.
"""

PROMPT = """Classify this reply to a cold outreach email. Return STRICT JSON only:
{{"sentiment": "positive|negative|neutral", "label": "interested|not_interested|question|referral|auto_reply|unsubscribe|other", "summary": "max 12 words"}}

Guidance:
- "interested" = wants to talk, asks for a call, says yes / send more
- "question" = asking something before deciding (still warm)
- "referral" = pointing you to someone else
- "not_interested" = polite or blunt no
- "unsubscribe" = asks to stop / not relevant / remove me
- "auto_reply" = out-of-office, autoresponder, bounce
sentiment: positive for interested/question/referral, negative for not_interested/unsubscribe, neutral for auto_reply/other.

Reply text:
{text}"""

_POS = ("interested", "yes", "let's talk", "lets talk", "call", "sure", "sounds good",
        "tell me more", "send", "keen", "happy to")
_NEG = ("not interested", "no thanks", "remove", "unsubscribe", "stop", "not relevant",
        "no thank")
_AUTO = ("out of office", "auto-reply", "automatic reply", "away from", "on leave",
         "vacation", "ooo")


def _heuristic(text):
    t = (text or "").lower()
    if any(k in t for k in _AUTO):
        return {"sentiment": "neutral", "label": "auto_reply", "summary": "automatic reply"}
    if any(k in t for k in _NEG):
        return {"sentiment": "negative", "label": "not_interested", "summary": "declined"}
    if any(k in t for k in _POS):
        return {"sentiment": "positive", "label": "interested", "summary": "showed interest"}
    if "?" in t:
        return {"sentiment": "positive", "label": "question", "summary": "asked a question"}
    return {"sentiment": "neutral", "label": "other", "summary": "reply received"}


def classify(text, provider="openai", api_key=None):
    """Return {sentiment, label, summary}. Never raises."""
    text = (text or "").strip()
    if not text:
        return {"sentiment": "neutral", "label": "other", "summary": "empty reply"}
    if not api_key:
        return _heuristic(text)

    try:
        import json
        prompt = PROMPT.format(text=text[:2000])
        if provider == "openai":
            from openai import OpenAI
            r = OpenAI(api_key=api_key).chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=80,
                response_format={"type": "json_object"},
            )
            data = json.loads(r.choices[0].message.content)
        else:
            import anthropic
            r = anthropic.Anthropic(api_key=api_key).messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = r.content[0].text.strip()
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start:end + 1])
        # sanity defaults
        data.setdefault("sentiment", "neutral")
        data.setdefault("label", "other")
        data.setdefault("summary", "")
        return data
    except Exception:
        return _heuristic(text)
