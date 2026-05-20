"""
gmail.py — fetch newsletter emails via IMAP using a Gmail App Password.
Requires GMAIL_USER and GMAIL_APP_PASSWORD in .env.

To create an App Password:
  1. Go to myaccount.google.com/apppasswords
  2. Create a password for "Market Watch"
  3. Add it to .env as GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

import email
import imaplib
import os
from datetime import datetime, timedelta, timezone
from email.header import decode_header

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import config
from tools.search import extract_text

NEWSLETTER_SENDERS = config.NEWSLETTER_SENDERS

# Subjects to skip — welcome/verification emails add no signal
_SKIP_SUBJECTS = {"welcome", "confirm", "verification", "verify", "unsubscribe"}


def _decode_header_value(raw) -> str:
    parts = decode_header(raw or "")
    decoded = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            decoded.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return " ".join(decoded)


def _extract_body(msg) -> str:
    """Return plain text from an email.Message, preferring text/plain."""
    if msg.is_multipart():
        # First pass: text/plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        # Second pass: text/html → strip tags
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return extract_text(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                return extract_text(text)
            return text
    return ""


def fetch_newsletter_emails(
    max_chars_per_email: int = 2000,
    lookback_hours: int = 26,
) -> list[dict]:
    """
    Fetch newsletter emails from the past lookback_hours via Gmail IMAP.
    Returns list of {sender, subject, date, body} dicts.
    Skips welcome/verification emails and truncates body to max_chars_per_email.
    """
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        raise RuntimeError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env. "
            "Create an App Password at myaccount.google.com/apppasswords."
        )

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    # IMAP SINCE is date-granular — use cutoff date (may return some older emails, LLM filters)
    since_str = cutoff.strftime("%d-%b-%Y")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user, password)
    # [Gmail]/All Mail covers Primary, Promotions, Updates — newsletters land anywhere
    mail.select('"[Gmail]/All Mail"')

    results = []
    for sender in NEWSLETTER_SENDERS:
        try:
            _, data = mail.search(None, f'FROM "{sender}" SINCE "{since_str}"')
            if not data[0]:
                continue
            msg_ids = data[0].split()
            # Take up to 3 most recent per sender
            for mid in msg_ids[-3:]:
                _, raw = mail.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])

                subject = _decode_header_value(msg.get("Subject", ""))

                # Skip welcome/verification noise
                if any(kw in subject.lower() for kw in _SKIP_SUBJECTS):
                    continue

                body = _extract_body(msg).strip()
                if not body:
                    continue

                results.append({
                    "sender": sender,
                    "subject": subject,
                    "date": msg.get("Date", ""),
                    "body": body[:max_chars_per_email],
                })
        except Exception as e:
            # Log but don't abort — one bad sender shouldn't kill the whole fetch
            print(f"  [Gmail] WARNING: failed to fetch from {sender}: {e}")

    try:
        mail.close()
        mail.logout()
    except Exception:
        pass

    return results
