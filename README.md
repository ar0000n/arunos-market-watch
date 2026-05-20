# Market Watch

A personal multi-agent job search monitor. Runs daily, emails you a prioritized digest of PM job openings, LinkedIn warm leads, and AI market signals — filtered to companies you actually care about.

Built on the raw Anthropic API. No frameworks. Orchestrator + three parallel worker tracks.

---

## How it works

**Track 1 — Primary target watch**
Polls your #1 target company's Greenhouse job board and news page daily. Surfaces new PM roles as CRITICAL the day they post.

**Track 2 — AI market signals**
Reads Hacker News RSS and fetches your Gmail newsletters via IMAP. Extracts AI funding rounds, product launches, and hiring signals. Passes newly discovered companies to Track 3 for same-day job board checks.

**Track 3 — Target company job boards + LinkedIn**
Searches LinkedIn Jobs across all your tier companies in parallel (4 workers). Fetches 1st-degree connections at Tier A companies and 2nd-degree connections at your primary target. Scans your LinkedIn feed for hiring signals.

**Orchestrator**
Synthesizes all three tracks into a prioritized digest. CRITICAL = act today. HIGH = act this week. MEDIUM = weekly context email.

**Email delivery**
- Daily email: CRITICAL + HIGH items only (action list)
- Weekly email (Sundays): MEDIUM items (context, newsletters, market signals)
- No email sent if zero CRITICAL + HIGH items that day

---

## Prerequisites

- **Python 3.11+**
- **Google Chrome** (installed and signed into LinkedIn — the agent reads your live session cookies)
- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)
- **Gmail App Password** — required for IMAP newsletter fetching (see setup step 4)

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/ar0000n/arunos-market-watch.git
cd market-watch
python3 -m venv .venv
source .venv/bin/activate
pip install anthropic python-dotenv playwright browser-cookie3
playwright install chromium
```

### 2. Configure your credentials

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-api03-...
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
NOTIFY_EMAIL=you@gmail.com
```

**Gmail App Password**: Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), create a password for "Market Watch", and paste the 16-character result into `.env`. This is separate from your regular Gmail password and only grants IMAP access.

### 3. Configure your job search

Edit `config.py`. This is the only file that's personal to you:

```python
USER_NAME     = "Your Name"
USER_LOCATION = "Austin, TX"          # or wherever you're based
DEADLINE_CONTEXT = "offer deadline..."  # optional — drives urgency in the digest

TIER_A_PRIMARY = "Anthropic"          # your #1 target — gets dedicated daily monitoring

TIER_A = ["Anthropic", "OpenAI", ...]  # willing to relocate
TIER_B = ["Company A", "Company B"]   # preferred location or remote
TIER_C = ["Company C", "Company D"]   # AI-forward, your city or remote-first

NEWSLETTER_SENDERS = [
    "importai@substack.com",
    "dan@tldrnewsletter.com",
    # add any newsletter you subscribe to
]
```

**Tier guide:**
- **Tier A** — your top targets. You'll get a dedicated news + Greenhouse check for `TIER_A_PRIMARY` every day. All Tier A companies get LinkedIn Jobs + warm lead checks via Track 3.
- **Tier B** — strong targets at your preferred location. Same Track 3 coverage.
- **Tier C** — AI-forward companies at your target location or remote-first. PM roles surface same day.

**If you change tier companies**, also update the descriptions in `prompts/system.md` (the `## Worker Tracks` section) so the orchestrator LLM has accurate context about each company.

### 4. Authenticate LinkedIn

The agent reads your live Chrome session cookies — no credentials stored. Just make sure you're logged into LinkedIn in Chrome before running.

```bash
python setup_linkedin_auth.py
```

If LinkedIn ever redirects to the login page during a run, open Chrome, log in, and re-run.

---

## Running manually

```bash
source .venv/bin/activate
python agents/market_watch.py
```

At the end of the run you'll see:

```
EMAIL SEND CHECKPOINT — DAILY
  To      : you@gmail.com
  Subject : Market Watch — 2026-05-20 — 3 CRITICAL, 5 HIGH
  ...
  Send? (y/n):
```

Type `y` to send. The full run log is always saved to `output/logs/` regardless.

On Sundays, a second prompt appears for the weekly context email (MEDIUM items).

---

## Automated scheduling (macOS)

The agent runs as a **LaunchDaemon** — fires at 7 AM daily without requiring you to be logged in. Only needs the Mac to be powered on.

**1. Create the plist** — replace `YOUR_USERNAME` and adjust the path if needed:

```bash
cat > /tmp/market-watch.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.marketwatch.daily</string>
    <key>UserName</key>
    <string>YOUR_USERNAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/path/to/market-watch/.venv/bin/python</string>
        <string>/Users/YOUR_USERNAME/path/to/market-watch/agents/market_watch.py</string>
        <string>--auto</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USERNAME/path/to/market-watch</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/path/to/market-watch/output/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/path/to/market-watch/output/logs/launchd_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key><string>/Users/YOUR_USERNAME</string>
        <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key><false/>
</dict>
</plist>
EOF
```

**2. Install and load:**

```bash
sudo cp /tmp/market-watch.plist /Library/LaunchDaemons/com.marketwatch.daily.plist
sudo chown root:wheel /Library/LaunchDaemons/com.marketwatch.daily.plist
sudo launchctl load /Library/LaunchDaemons/com.marketwatch.daily.plist
```

**3. Verify:**

```bash
sudo launchctl list | grep marketwatch
```

**4. Test immediately:**

```bash
sudo launchctl kickstart -k system/com.marketwatch.daily
tail -f /path/to/market-watch/output/logs/launchd_stdout.log
```

**Note:** The `--auto` flag skips the y/n prompt and sends email automatically. Daily email fires every day; weekly context email fires on Sundays.

---

## Email reference

| Email | When | Contains | Guard |
|-------|------|----------|-------|
| Daily digest | Every day at 7 AM | CRITICAL + HIGH + RECOMMENDATIONS | Skipped if 0 CRITICAL and 0 HIGH |
| Weekly context | Sundays at 7 AM | MEDIUM + META | Skipped if 0 MEDIUM |

RECOMMENDATIONS = companies Track 2 discovered and Track 3 verified as actively hiring PMs. These are candidates to add to your Tier C list in `config.py`.

---

## Troubleshooting

**LinkedIn shows login page / returns empty results**
Your Chrome session cookie has expired. Log into LinkedIn in Chrome and re-run. Cookies are read fresh each run — no re-auth step needed.

**Gmail IMAP fails with authentication error**
App Passwords require 2FA to be enabled on your Google account. Enable 2FA at myaccount.google.com/security, then create the App Password again.

**`ModuleNotFoundError: No module named 'anthropic'`**
You're using system Python instead of the venv. Run `source .venv/bin/activate` first, or use `.venv/bin/python agents/market_watch.py` directly.

**LaunchDaemon fires but sends no email**
Check `output/logs/launchd_stderr.log` for Python tracebacks. The most common cause is the Chrome cookie path — `browser_cookie3` reads from your user's Chrome profile, which requires the correct `HOME` env variable in the plist.

**Track 3 returns 0 items**
LinkedIn anti-bot detection can intermittently block scraping. If it happens consistently, check `output/logs/launchd_stderr.log`. A fresh Chrome login usually resolves it.

**Digest truncates mid-section**
The orchestrator synthesis call uses `max_tokens=8192`. If you have many companies across all tiers and the digest is still truncating, raise this value in `agents/market_watch.py`.

---

## Project structure

```
market-watch/
├── config.py                 ← personalize this
├── .env                      ← secrets (gitignored)
├── .env.example              ← template
├── agents/
│   └── market_watch.py       ← orchestrator + all three tracks
├── tools/
│   ├── browser.py            ← LinkedIn (Playwright + Chrome cookies)
│   ├── gmail.py              ← newsletter fetch (IMAP)
│   └── search.py             ← HTTP fetch + HTML → text
├── output/
│   ├── digest.py             ← email formatting + SMTP send
│   └── logs/                 ← timestamped .md run logs (gitignored)
├── prompts/
│   └── system.md             ← orchestrator system prompt (templated)
└── data/
    └── discovery_log.json    ← cross-run company tracking (gitignored)
```
