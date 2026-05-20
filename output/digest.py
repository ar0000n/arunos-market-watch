"""
digest.py — format and email Market Watch digests.

Daily email   : CRITICAL + HIGH + RECOMMENDATIONS only — pure action list.
Weekly digest : MEDIUM + META — context, newsletters, market signals.

Called from market_watch.py __main__ after each run.
Requires GMAIL_USER and GMAIL_APP_PASSWORD in .env.
"""

import os
import pathlib
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import dotenv
dotenv.load_dotenv()

TO_ADDRESS = os.environ.get("NOTIFY_EMAIL") or os.environ.get("GMAIL_USER", "")
_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587

# Sections included in each email type
_DAILY_SECTIONS   = {"CRITICAL", "HIGH", "RECOMMENDATIONS"}
_WEEKLY_SECTIONS  = {"MEDIUM", "META"}


# ---------------------------------------------------------------------------
# Section filtering
# ---------------------------------------------------------------------------

def _split_sections(digest_text: str) -> tuple[str, list[tuple[str, str]]]:
    """
    Split digest into (preamble, [(header_line, body), ...]).
    preamble = everything before the first ## section (title, date line, etc.)
    """
    preamble_lines: list[str] = []
    sections: list[tuple[str, str]] = []
    current_header: str | None = None
    current_body: list[str] = []

    for line in digest_text.split("\n"):
        if line.startswith("## "):
            if current_header is not None:
                sections.append((current_header, "\n".join(current_body)))
            elif current_body:
                preamble_lines = current_body[:]
            current_header = line
            current_body = []
        else:
            current_body.append(line)

    if current_header is not None:
        sections.append((current_header, "\n".join(current_body)))
    elif current_body and not preamble_lines:
        preamble_lines = current_body

    return "\n".join(preamble_lines), sections


def _filter_digest(digest_text: str, keep: set[str]) -> str:
    """Return a digest containing only the sections whose header matches keep keywords."""
    preamble, sections = _split_sections(digest_text)
    parts = [preamble] if preamble.strip() else []
    for header, body in sections:
        if any(k in header.upper() for k in keep):
            parts.append(header)
            parts.append(body)
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _inline_md(text: str) -> str:
    text = re.sub(r"\*\*\*(.*?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#f5f5f5;padding:2px 4px;border-radius:3px;font-size:13px">\1</code>',
        text,
    )
    return text


_SECTION_STYLES: dict[str, tuple[str, str]] = {
    "CRITICAL":        ("#c0392b", "2px solid"),
    "HIGH":            ("#d35400", "2px solid"),
    "MEDIUM":          ("#2471a3", "1px solid"),
    "RECOMMENDATIONS": ("#1e8449", "1px solid"),
    "META":            ("#6c757d", "1px dashed"),
}


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    in_list = False
    in_blockquote = False

    def close_open():
        nonlocal in_list, in_blockquote
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_blockquote:
            out.append("</blockquote>")
            in_blockquote = False

    for line in lines:
        if line.startswith("## "):
            close_open()
            title = line[3:]
            color, border = "#333", "1px solid"
            for key, (c, b) in _SECTION_STYLES.items():
                if key in title.upper():
                    color, border = c, b
                    break
            out.append(
                f'<h2 style="color:{color};border-bottom:{border} {color};'
                f'padding-bottom:6px;margin-top:28px;font-size:16px">'
                f"{_inline_md(title)}</h2>"
            )
        elif line.startswith("### "):
            close_open()
            out.append(
                f'<h3 style="font-size:15px;margin-top:18px;margin-bottom:2px">'
                f"{_inline_md(line[4:])}</h3>"
            )
        elif line.startswith("# "):
            close_open()
            out.append(
                f'<h1 style="font-size:20px;color:#1a1a2e;margin:0 0 4px">'
                f"{_inline_md(line[2:])}</h1>"
            )
        elif line.startswith("---"):
            close_open()
            out.append('<hr style="border:none;border-top:1px solid #e8e8e8;margin:10px 0">')
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_blockquote:
                out.append(
                    '<blockquote style="border-left:3px solid #ccc;margin:6px 0;'
                    'padding:4px 12px;background:#f9f9f9;border-radius:0 4px 4px 0">'
                )
                in_blockquote = True
            out.append(f'<p style="margin:2px 0;font-style:italic">{_inline_md(line[2:])}</p>')
        elif line.startswith(("- ", "* ")):
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            if not in_list:
                out.append('<ul style="margin:4px 0;padding-left:20px">')
                in_list = True
            out.append(f"<li>{_inline_md(line[2:])}</li>")
        elif line.strip() == "":
            close_open()
            out.append("<br>")
        else:
            close_open()
            out.append(f'<p style="margin:3px 0">{_inline_md(line)}</p>')

    close_open()
    return "\n".join(out)


def _build_html(
    digest_text: str,
    banner_title: str,
    banner_subtitle: str,
    pills: list[tuple[str, str, str]],   # [(label, bg_color, text_color), ...]
    log_path: pathlib.Path,
) -> str:
    pill_html = "".join(
        f'<span style="padding:4px 13px;border-radius:12px;font-size:13px;font-weight:600;'
        f'background:{bg};color:{fg};border:1px solid {bg}">{label}</span>'
        for label, bg, fg in pills
    )
    body = _md_to_html(digest_text)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
     max-width:780px;margin:0 auto;padding:20px 24px;color:#222;line-height:1.55;font-size:15px}}
a{{color:#2c6fad;text-decoration:none}}a:hover{{text-decoration:underline}}
ul{{margin:4px 0;padding-left:20px}}li{{margin:2px 0}}
.banner{{background:#1a1a2e;color:#fff;padding:16px 20px;border-radius:8px;margin-bottom:24px}}
.btitle{{font-size:18px;font-weight:700;margin:0 0 3px}}
.bsub{{color:#aab;font-size:13px;margin:0}}
.pills{{display:flex;gap:10px;margin-top:10px;flex-wrap:wrap}}
</style>
</head>
<body>
<div class="banner">
  <div class="btitle">{banner_title}</div>
  <div class="bsub">{banner_subtitle}</div>
  <div class="pills">{pill_html}</div>
</div>
{body}
<hr style="border:none;border-top:1px solid #eee;margin:28px 0 10px">
<p style="color:#aaa;font-size:12px">ArunOS Market Watch &middot; {log_path.name}</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Shared send helper
# ---------------------------------------------------------------------------

def _send_email(subject: str, plain_text: str, html_body: str) -> bool:
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not user or not password:
        print("[Digest] GMAIL_USER / GMAIL_APP_PASSWORD not set — skipping.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = TO_ADDRESS
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"[Digest] Connecting to {_SMTP_HOST}:{_SMTP_PORT}...")
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[Digest] ✓ Sent to {TO_ADDRESS}")
        return True
    except smtplib.SMTPException as e:
        print(f"[Digest] ✗ SMTP error: {e}")
        return False


def _checkpoint(label: str, subject: str, preview: str, log_path: pathlib.Path, auto: bool) -> bool:
    """
    Print terminal checkpoint.
    If auto=True, print a summary and return True immediately (no prompt).
    Otherwise, return True only if user types 'y'.
    """
    print()
    print("=" * 72)
    print(f"EMAIL SEND CHECKPOINT — {label}")
    print("=" * 72)
    print(f"  To      : {TO_ADDRESS}")
    print(f"  Subject : {subject}")
    print(f"  Log     : {log_path}")
    print()
    lines = preview.strip().splitlines()[:25]
    print("  --- Preview (first 25 lines) ---")
    for ln in lines:
        print(f"  {ln}")
    if len(preview.splitlines()) > 25:
        print("  ...")
    print()
    if auto:
        print("  [auto mode] Sending without prompt.")
        return True
    try:
        answer = input("  Send? (y/n): ").strip().lower()
    except EOFError:
        answer = "n"
    if answer != "y":
        print("[Digest] Send cancelled.")
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_digest(
    digest_text: str,
    all_items: list[dict],
    log_path: pathlib.Path,
    auto: bool = False,
) -> bool:
    """
    Daily email: CRITICAL + HIGH + RECOMMENDATIONS only.
    Skips silently if zero CRITICAL and zero HIGH items.
    auto=False (default): prompts for y/n.
    auto=True: sends immediately without prompt — used by the launchd scheduler.
    """
    n_critical = sum(1 for i in all_items if i.get("priority") == "CRITICAL")
    n_high = sum(1 for i in all_items if i.get("priority") == "HIGH")

    if n_critical == 0 and n_high == 0:
        print("\n[Digest] 0 CRITICAL + 0 HIGH items — log saved, no daily email.")
        return False

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"ArunOS Market Watch — {date_str} — {n_critical} CRITICAL, {n_high} HIGH"

    filtered = _filter_digest(digest_text, _DAILY_SECTIONS)

    if not _checkpoint("DAILY", subject, filtered, log_path, auto):
        return False

    pills = [
        (f"&#x1F534; {n_critical} CRITICAL", "#c0392b22", "#ff6b6b"),
        (f"&#x1F7E0; {n_high} HIGH",          "#d3540022", "#ffa94d"),
    ]
    html = _build_html(filtered, "ArunOS Market Watch", date_str, pills, log_path)
    return _send_email(subject, filtered, html)


def send_weekly_digest(
    digest_text: str,
    all_items: list[dict],
    log_path: pathlib.Path,
    auto: bool = False,
) -> bool:
    """
    Weekly email: MEDIUM + META only — context, newsletters, market signals.
    Skips silently if zero MEDIUM items.
    auto=False (default): prompts for y/n.
    auto=True: sends immediately without prompt — used by the launchd scheduler.
    """
    n_medium = sum(1 for i in all_items if i.get("priority") == "MEDIUM")

    if n_medium == 0:
        print("\n[Digest] 0 MEDIUM items — skipping weekly digest.")
        return False

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"ArunOS Market Watch — Weekly Context — {date_str} — {n_medium} items"

    filtered = _filter_digest(digest_text, _WEEKLY_SECTIONS)

    if not _checkpoint("WEEKLY", subject, filtered, log_path, auto):
        return False

    pills = [
        (f"&#x1F535; {n_medium} MEDIUM", "#2471a322", "#74b9ff"),
    ]
    html = _build_html(filtered, "ArunOS Market Watch — Weekly Context", date_str, pills, log_path)
    return _send_email(subject, filtered, html)
