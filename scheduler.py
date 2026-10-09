"""
Sequence runner — checks for replies and sends due follow-ups.
Call run() on app load or via the Sync button.
"""
import json
from datetime import datetime

import db
import gmail
import gmail_oauth
import email_gen
import reply_classifier


def _send(gmail_addr, gmail_pass, to, subject, body):
    """Send via OAuth if connected, else fall back to App Password."""
    if gmail_oauth.is_connected():
        gmail_oauth.send(to, subject, body)
    else:
        gmail.send(gmail_addr, gmail_pass, to, subject, body)


def _fetch_replies(gmail_addr, gmail_pass, target_emails):
    """Return [{email, snippet}] for any of target_emails that replied."""
    if gmail_oauth.is_connected():
        return gmail_oauth.fetch_replies(target_emails)
    return gmail.fetch_replies(gmail_addr, gmail_pass, target_emails)


def run(log=None):
    """
    1. Check Gmail for replies from all active leads.
    2. Send any due follow-up emails.

    log: optional callable(msg) for status messages.
    Returns dict with counts.
    """
    def emit(msg):
        if log:
            log(msg)
        print(msg)

    gmail_addr   = db.get("gmail_address", "")
    gmail_pass   = db.get("gmail_password", "")
    provider     = db.get("ai_provider", "openai")
    api_key      = db.get("ai_key", "")
    dossier      = db.get("dossier", email_gen.DEFAULT_DOSSIER)
    sender_name  = db.get("sender_name", "Broti Dev")

    result = {"replies": [], "sent": [], "errors": []}

    if not gmail_addr and not gmail_oauth.is_connected():
        emit("Gmail not configured — skipping sync.")
        return result

    # ── 1. Check for replies ────────────────────────────────────────────────
    active_leads = db.all_leads(status="active")
    if active_leads:
        emit(f"Checking Gmail for replies from {len(active_leads)} active leads…")
        active_emails = [l["email"] for l in active_leads]
        try:
            replies = _fetch_replies(gmail_addr, gmail_pass, active_emails)
            for rep in replies:
                addr    = rep.get("email", "").lower()
                snippet = rep.get("snippet", "")
                for lead in active_leads:
                    if lead["email"].lower() == addr:
                        cls = reply_classifier.classify(snippet, provider, api_key)
                        db.mark_replied(lead["id"], cls.get("sentiment", ""),
                                        cls.get("label", ""), snippet)
                        result["replies"].append(
                            f"{lead['brand_name']} ({cls.get('label','reply')})")
                        emit(f"  Reply from {lead['brand_name']}: "
                             f"{cls.get('sentiment','')}/{cls.get('label','')}")
        except Exception as e:
            result["errors"].append(f"Reply check failed: {e}")
            emit(f"  ⚠ Reply check error: {e}")

    # ── 2. Send due follow-ups ──────────────────────────────────────────────
    due = db.due_followups()
    if due:
        emit(f"Sending {len(due)} due follow-up email(s)…")
    else:
        emit("No follow-ups due right now.")

    for lead in due:
        next_step = lead["step"] + 1
        if next_step > 5:
            continue

        try:
            # Use pre-generated emails if stored, else generate on-the-fly
            emails_json = json.loads(lead.get("emails_json") or "{}")
            email_data = emails_json.get(str(next_step))

            if not email_data:
                emit(f"  Generating Email {next_step} for {lead['brand_name']}…")
                seq = email_gen.generate_sequence(
                    lead, dossier, provider, api_key, sender_name
                )
                email_data = seq.get(next_step, {})

            if not email_data or not email_data.get("body"):
                raise ValueError("Empty email generated")

            _send(gmail_addr, gmail_pass,
                  lead["email"], email_data["subject"], email_data["body"])

            db.mark_sent(lead["id"], next_step,
                         email_data["subject"], email_data["body"])

            result["sent"].append(f"{lead['brand_name']} (Email {next_step})")
            emit(f"  ✓ Sent Email {next_step} → {lead['brand_name']}")

        except Exception as e:
            result["errors"].append(f"{lead['brand_name']}: {e}")
            emit(f"  ✗ Error for {lead['brand_name']}: {e}")

    return result
