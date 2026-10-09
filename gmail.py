"""
Gmail SMTP (send) + IMAP (monitor replies) using Gmail App Password.
To generate an App Password: Google Account → Security → App Passwords
"""
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send(gmail_address, app_password, to_email, subject, body):
    """Send a plain-text email via Gmail SMTP SSL."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_address
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, app_password)
        server.sendmail(gmail_address, to_email, msg.as_string())


def test_credentials(gmail_address, app_password):
    """Return True if SMTP login succeeds."""
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(gmail_address, app_password)
        return True
    except Exception:
        return False


def check_replies(gmail_address, app_password, target_emails: list[str]) -> list[str]:
    """
    Connect to Gmail INBOX via IMAP and return which of `target_emails`
    have sent a reply (any message FROM that address).
    """
    replied = []
    if not target_emails:
        return replied

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, app_password)
        mail.select("INBOX")

        for addr in target_emails:
            # Search for any message from this address
            result, data = mail.search(None, f'(FROM "{addr}")')
            if result == "OK" and data and data[0]:
                replied.append(addr.lower())

        mail.logout()

    except Exception as e:
        print(f"[IMAP] error: {e}")

    return replied


def _extract_body(msg):
    """Pull plain-text body from an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    pass
        return ""
    try:
        return msg.get_payload(decode=True).decode(errors="ignore")
    except Exception:
        return msg.get_payload() or ""


def fetch_replies(gmail_address, app_password, target_emails):
    """
    Like check_replies, but also returns the latest reply text per address.
    Returns list of {"email": addr, "snippet": text}.
    """
    out = []
    if not target_emails:
        return out
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_address, app_password)
        mail.select("INBOX")
        for addr in target_emails:
            addr = (addr or "").replace('"', "").replace("\r", "").replace("\n", "")
            result, data = mail.search(None, f'(FROM "{addr}")')
            if result == "OK" and data and data[0]:
                ids = data[0].split()
                latest = ids[-1]
                r2, msg_data = mail.fetch(latest, "(RFC822)")
                snippet = ""
                if r2 == "OK" and msg_data and msg_data[0]:
                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    snippet = _extract_body(msg)[:1500]
                out.append({"email": addr.lower(), "snippet": snippet})
        mail.logout()
    except Exception as e:
        print(f"[IMAP] fetch_replies error: {e}")
    return out
