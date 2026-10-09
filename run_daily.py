"""
Daily runner — meant to be called by Windows Task Scheduler (or GitHub Actions).
Does three things in order:
  1. If pool is running low (< 200 leads), refill it via Apify/Scrape.do/Searlo.tech
  2. Pull 100 leads from pool → generate Email 1 → send
  3. Check replies + send all due follow-up emails

Run manually:   python run_daily.py
Scheduled:      see setup_scheduler.bat
"""
import json
import time
import sys
import os
from datetime import datetime

# Make sure we can import sibling modules when run from Task Scheduler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import db
import gmail
import email_gen
import lead_finder
import scheduler

# ─── config ───────────────────────────────────────────────────────────────────

POOL_REFILL_BELOW   = 200   # refill pool when it drops below this number
POOL_REFILL_TARGET  = 500   # how many leads to fetch during refill
DELAY_BETWEEN_SENDS = 6     # seconds between each send (100 sends ≈ 10 min)
LOG_FILE = "daily_log.txt"


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    db.init()

    log("=" * 60)
    log("Daily run started")

    apify_key     = db.get("apify_key",     "")
    scrape_do_key = db.get("scrape_do_key", "")
    searlo_key    = db.get("searlo_key",    "")
    ai_key        = db.get("ai_key",        "")
    provider      = db.get("ai_provider",   "openai")
    gmail_addr    = db.get("gmail_address", "")
    gmail_pass    = db.get("gmail_password","")
    dossier       = db.get("dossier",       email_gen.DEFAULT_DOSSIER)
    sender_name   = db.get("sender_name",   "Broti Dev")
    markets_raw   = db.get("target_markets", "India")
    markets       = [m.strip() for m in markets_raw.split(",") if m.strip()]

    # Warmup-aware daily limit
    DAILY_SEND_COUNT = db.warmup_daily_limit()
    log(f"Daily send limit (warmup): {DAILY_SEND_COUNT}")

    # ── guard ──────────────────────────────────────────────────────────────
    if not gmail_addr or not gmail_pass:
        log("ERROR: Gmail not configured. Open the app → Settings.")
        sys.exit(1)
    if not ai_key:
        log("ERROR: AI API key not configured. Open the app → Settings.")
        sys.exit(1)

    # ── 1. Refill pool if low ───────────────────────────────────────────────
    pool = db.pool_size()
    log(f"Pool size: {pool} leads")

    if pool < POOL_REFILL_BELOW:
        if not apify_key and not scrape_do_key and not searlo_key:
            log("WARNING: Pool low but no search API keys configured — skipping refill.")
        else:
            needed = POOL_REFILL_TARGET - pool
            log(f"Pool below {POOL_REFILL_BELOW} — fetching ~{needed} new leads…")

            def on_progress(msg, count):
                log(f"  [find] {msg}")

            new_leads = lead_finder.find_leads(
                apify_key=apify_key or None,
                scrape_do_key=scrape_do_key or None,
                searlo_key=searlo_key or None,
                target=needed,
                markets=markets,
                on_progress=on_progress,
            )

            added = 0
            for lead in new_leads:
                lid = db.upsert_lead(
                    brand_name=lead.get("brand_name", "Unknown"),
                    email=lead["email"],
                    contact_name=lead.get("contact_name", ""),
                    website=lead.get("website", ""),
                    instagram=lead.get("instagram", ""),
                    category=lead.get("category", "D2C"),
                    # status stays 'pool' (default)
                )
                if lid:
                    db.upsert_lead(
                        brand_name=lead.get("brand_name", "Unknown"),
                        email=lead["email"],
                        contact_name=lead.get("contact_name", ""),
                        website=lead.get("website", ""),
                        instagram=lead.get("instagram", ""),
                        category=lead.get("category", "D2C"),
                        market=lead.get("market", "India"),
                        source=lead.get("source", ""),
                    )
                    added += 1

            log(f"Pool refill complete — added {added} new leads. New pool size: {db.pool_size()}")

    # ── 2. Send Email 1 to today's batch of 100 ────────────────────────────
    batch = db.pull_from_pool(DAILY_SEND_COUNT)
    log(f"Sending Email 1 to {len(batch)} leads from pool…")

    sent   = 0
    errors = 0

    for lead in batch:
        try:
            # Generate full 5-email sequence
            seq = email_gen.generate_sequence(
                lead, dossier, provider, ai_key, sender_name
            )
            e1 = seq.get(1, {})

            if not e1.get("body"):
                raise ValueError("Empty email generated")

            # Send Email 1
            gmail.send(gmail_addr, gmail_pass, lead["email"],
                       e1["subject"], e1["body"])

            # Save all 5 emails + mark step 1 sent
            emails_json = json.dumps({str(k): v for k, v in seq.items()})
            db.upsert_lead(          # update emails_json on existing row
                brand_name   = lead["brand_name"],
                email        = lead["email"],
                contact_name = lead.get("contact_name", ""),
                website      = lead.get("website", ""),
                instagram    = lead.get("instagram", ""),
                category     = lead.get("category", "D2C"),
                emails_json  = emails_json,
            )
            db.mark_sent(lead["id"], 1, e1["subject"], e1["body"])
            sent += 1
            log(f"  ✓ [{sent}/{len(batch)}] {lead['brand_name']} <{lead['email']}>")

        except Exception as e:
            errors += 1
            log(f"  ✗ {lead['brand_name']} <{lead['email']}>: {e}")

        time.sleep(DELAY_BETWEEN_SENDS)

    log(f"Email 1 batch done — sent: {sent}, errors: {errors}")

    # ── 3. Follow-ups + reply check ────────────────────────────────────────
    log("Running follow-up sequence check…")
    result = scheduler.run(log=log)
    log(f"Replies found: {len(result['replies'])} | Follow-ups sent: {len(result['sent'])}")
    if result["errors"]:
        for e in result["errors"]:
            log(f"  ✗ {e}")

    log("Daily run complete")
    log("=" * 60)


if __name__ == "__main__":
    main()
