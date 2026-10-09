"""
Fills a throwaway database with fake leads, drafts and replies so you can
work on the interface without API keys, Gmail, or sending anything real.

Used by preview_ui.bat. Never point CEE_DB at your real leads.db when running this.
"""
import json
import os
import sys
from datetime import datetime, timedelta

if os.environ.get("CEE_DB", "leads.db") == "leads.db":
    sys.exit("Refusing to seed the real leads.db. Set CEE_DB=demo.db first.")

import db

if os.path.exists(db.DB):
    os.remove(db.DB)
db.init()

db.put("onboarding_complete", "1")
db.put("ai_key", "demo")
db.put("apify_key", "demo")
db.put("sender_name", "Demo User")
db.put("dossier", "DEMO DOSSIER: AI-assisted content writer for Indian D2C brands.")
db.put("warmup_start", (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d"))

BRANDS = [
    ("Glow Theory", "Ananya Rao", "ananya@glowtheory.in", "Skincare"),
    ("Kora Threads", "Rahul Mehta", "rahul@korathreads.com", "Fashion"),
    ("Saffron Pantry", "Meera Iyer", "meera@saffronpantry.in", "Food"),
    ("Lumen Home", "Arjun Shah", "arjun@lumenhome.co", "Home Decor"),
    ("Veda Vitals", "Priya Nair", "priya@vedavitals.in", "Supplements"),
    ("Aurum Lane", "Kabir Sethi", "kabir@aurumlane.com", "Jewellery"),
]


def seq(brand, name):
    first = name.split()[0]
    out = {1: {"subject": f"{brand}'s product pages",
               "body": f"Hi {first},\n\nI rewrote 2 of {brand}'s product descriptions. "
                       "Want me to send them over?\n\nDemo User",
               "spam_score": 9, "spam_issues": []}}
    for n in range(2, 6):
        out[n] = {"subject": f"Re: {brand}'s product pages",
                  "body": f"Hi {first},\n\nFollow-up {n} body goes here.\n\nDemo User"}
    return out


# Sent leads with history (drives Dashboard, All leads, Replies)
now = datetime.now()
for i, (brand, name, email, cat) in enumerate(BRANDS):
    s = seq(brand, name)
    lid = db.upsert_lead(brand, email, contact_name=name, website=email.split("@")[1],
                         category=cat, emails_json=json.dumps({str(k): v for k, v in s.items()}))
    db.mark_sent(lid, 1, s[1]["subject"], s[1]["body"])
    if i == 0:
        db.mark_replied(lid, "positive", "interested", "Sounds good, send them over!")
    elif i == 1:
        db.mark_replied(lid, "neutral", "more_info", "What would this cost us?")
    elif i == 2:
        db.mark_replied(lid, "negative", "not_interested", "Not right now, thanks.")

# An in-progress campaign (drives the Campaign page stepper + review cards)
verified = [{"brand_name": f"New {b}", "contact_name": n, "contact_role": "Founder",
             "email": "new." + e, "category": c, "market": "India",
             "email_quality": "founder_real" if k % 2 else "verified_guess"}
            for k, (b, n, e, c) in enumerate(BRANDS[:4])]
drafts = [{"_lead": l, "_seq": seq(l["brand_name"], l["contact_name"]),
           "_approved": k == 0, "_skip": False} for k, l in enumerate(verified)]
db.save_campaign({"verified": verified, "audits": {}, "drafts": drafts,
                  "profile": None, "verify_results": {}, "found_count": 12})

print(f"Demo data written to {db.DB}")
