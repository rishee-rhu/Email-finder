"""
Gmail OAuth — connects Gmail without storing your password.
User authorises once via browser; token is saved locally and auto-refreshes.

Setup (one-time):
  1. Go to console.cloud.google.com
  2. New project → Enable Gmail API
  3. OAuth consent screen → External → add your email as test user
  4. Credentials → Create → OAuth 2.0 Client ID → Desktop app
  5. Download JSON → save as  gmail_credentials.json  in this folder
  6. Click "Connect Gmail" in the app — browser opens, you approve, done.
"""
import base64
import os
from pathlib import Path
from email.mime.text import MIMEText

SCOPES      = ["https://mail.google.com/"]
TOKEN_FILE  = Path(__file__).parent / "gmail_token.json"
CREDS_FILE  = Path(__file__).parent / "gmail_credentials.json"


def _load_creds():
    """Load and refresh stored credentials. Returns Credentials or None."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if not TOKEN_FILE.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
            return creds
    except Exception:
        pass
    return None


def is_connected():
    return _load_creds() is not None


def connected_email():
    """Return the authorised Gmail address, or None."""
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=_load_creds(), cache_discovery=False)
        return svc.users().getProfile(userId="me").execute().get("emailAddress")
    except Exception:
        return None


def run_oauth_flow():
    """
    Open browser → user approves Gmail access → token saved.
    Returns (email_address, error_message).
    """
    if not CREDS_FILE.exists():
        return None, (
            "gmail_credentials.json not found.\n"
            "Download it from Google Cloud Console → Credentials → your OAuth Client."
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN_FILE.write_text(creds.to_json())
        email = connected_email()
        return email, None
    except Exception as e:
        return None, str(e)


def disconnect():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def send(to_email, subject, body):
    """Send plain-text email via OAuth. Raises on failure."""
    creds = _load_creds()
    if not creds:
        raise RuntimeError("Gmail not connected — run OAuth flow first.")
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"]      = to_email
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.messages().send(userId="me", body={"raw": raw}).execute()


def check_replies(target_emails):
    """
    Check if any of target_emails have sent us a message.
    Returns list of addresses that replied.
    """
    creds = _load_creds()
    if not creds:
        return []
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        replied = []
        for email in target_emails:
            q = f"from:{email}"
            res = svc.users().messages().list(userId="me", q=q, maxResults=1).execute()
            if res.get("messages"):
                replied.append(email)
        return replied
    except Exception as e:
        print(f"[gmail_oauth] check_replies error: {e}")
        return []


def fetch_replies(target_emails):
    """
    Like check_replies, but also returns the latest reply snippet per address.
    Returns list of {"email": addr, "snippet": text}.
    """
    creds = _load_creds()
    if not creds:
        return []
    out = []
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        for email in target_emails:
            res = svc.users().messages().list(
                userId="me", q=f"from:{email}", maxResults=1).execute()
            msgs = res.get("messages")
            if not msgs:
                continue
            full = svc.users().messages().get(
                userId="me", id=msgs[0]["id"], format="full").execute()
            out.append({"email": email.lower(), "snippet": full.get("snippet", "")})
    except Exception as e:
        print(f"[gmail_oauth] fetch_replies error: {e}")
    return out
