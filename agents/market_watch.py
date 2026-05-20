"""
Market Watch Orchestrator
ArunOS — multi-agent job search system

Orchestrator-Workers pattern. Raw Anthropic API. No frameworks.
Model: claude-sonnet-4-20250514

Execution order (dependency-aware, not fully parallel):
  Phase 1 — parallel : Track 1 + Track 2
  Phase 2 — sequential: Track 3  (uses Track 2's discovered_companies to expand target list)
"""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import anthropic
import concurrent.futures
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Literal, TypedDict

import dotenv
dotenv.load_dotenv()

import config
from tools.search import fetch_url, extract_text
from tools.browser import fetch_linkedin_jobs, fetch_linkedin_connections_at, fetch_linkedin_feed
from tools.gmail import fetch_newsletter_emails

DISCOVERY_LOG = pathlib.Path(__file__).parent.parent / "data" / "discovery_log.json"
VERIFY_THRESHOLD = 2  # appearances before actively checking for open PM roles


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-6"

def _tier_bullet_list(companies: list[str]) -> str:
    return "\n".join(f"- {c}" for c in companies)

_prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "system.md"
SYSTEM_PROMPT = _prompt_path.read_text().format(
    user_name=config.USER_NAME,
    user_role=config.USER_ROLE,
    user_location=config.USER_LOCATION,
    tier_a_primary=config.TIER_A_PRIMARY,
    deadline_context=config.DEADLINE_CONTEXT,
    tier_a_section=_tier_bullet_list([c for c in config.TIER_A if c != config.TIER_A_PRIMARY]),
    tier_b_section=_tier_bullet_list(config.TIER_B),
    tier_c_section=_tier_bullet_list(config.TIER_C),
)


# ---------------------------------------------------------------------------
# Worker result schema
# ---------------------------------------------------------------------------

Priority = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class WorkerItem(TypedDict):
    priority:  Priority       # worker's suggested priority; orchestrator may escalate
    source:    str            # human-readable name, e.g. "greenhouse.io/anthropic"
    url:       str            # direct link to the posting, article, or email
    title:     str            # job title, newsletter subject line, or article headline
    summary:   str            # 2–3 sentence factual description
    relevance: str            # why this matters to Arun's PM search specifically
    action:    str | None     # recommended next step, or None if no action needed


class DiscoveredCompany(TypedDict):
    """
    A company surfaced by Track 2 (AI market signals) that Track 3 should
    check for PM roles in the same run. Austin-based or remote-friendly
    companies are treated as dynamic Tier C additions.
    """
    name:            str   # company name, e.g. "Acme AI"
    reason:          str   # why it was flagged, e.g. "Series B announced, actively hiring PMs"
    location:        str   # "Austin, TX" | "Remote" | "San Francisco, CA" etc.
    remote_friendly: bool
    source_url:      str   # newsletter or HN thread where it was found


class WorkerResult:
    """Structured findings from a single worker track."""

    def __init__(self, track: str):
        self.track = track
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.items: list[WorkerItem] = []
        self.errors: list[str] = []
        self.meta: str = ""
        # Track 2 populates this; Track 3 consumes it to expand its target list
        self.discovered_companies: list[DiscoveredCompany] = []

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "timestamp": self.timestamp,
            "items": self.items,
            "errors": self.errors,
            "meta": self.meta,
            "discovered_companies": self.discovered_companies,
        }


# ---------------------------------------------------------------------------
# Worker Track 1 — Anthropic Watch
# ---------------------------------------------------------------------------

TRACK_1_WORKER_SYSTEM = f"""\
You are the Track 1 worker in a job search monitoring system.

Target person: {config.USER_NAME}, a PM leader whose #1 job search \
target is {config.TIER_A_PRIMARY}. They are specifically looking for Product Manager roles.

Given raw data fetched from {config.TIER_A_PRIMARY}'s Greenhouse job board and news page, \
produce a JSON array of WorkerItem objects. Return ONLY valid JSON — \
no explanation, no markdown fences, no commentary.

Each WorkerItem must have exactly these fields:
  priority   : "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
  source     : string  — human-readable source name
  url        : string  — direct link
  title      : string  — job title or article headline
  summary    : string  — 2–3 sentence factual description
  relevance  : string  — why this matters to the job search specifically
  action     : string or null — concrete next step, or null if none

Priority rules (apply strictly):
  - Any {config.TIER_A_PRIMARY} Product Manager role → "CRITICAL"
  - News about {config.TIER_A_PRIMARY} products, model releases, safety research → "HIGH"
  - General {config.TIER_A_PRIMARY} news (events, partnerships, hires) → "MEDIUM"
  - Irrelevant content → omit entirely, do not include in output

If no relevant items exist, return an empty JSON array: []
"""


def run_track_1_anthropic() -> WorkerResult:
    """
    Monitor Anthropic news page and Greenhouse job board.
    Highest priority track — runs daily.

    Data flow:
      1. Fetch Greenhouse public API → filter PM roles in Python (no LLM)
      2. Fetch anthropic.com/news → strip HTML to plain text
      3. Single worker LLM call → classify both into WorkerItems
    """
    result = WorkerResult(track="Track 1 — Anthropic Watch")
    raw: dict = {}

    # Step 1: Greenhouse public REST API — returns structured JSON, no parsing needed
    print("  [Track 1] Fetching Greenhouse API...")
    try:
        data = json.loads(fetch_url("https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"))
        all_jobs = data.get("jobs", [])
        pm_jobs = [
            {
                "title": j["title"],
                "location": j.get("location", {}).get("name", ""),
                "url": j["absolute_url"],
                "updated_at": j.get("updated_at", ""),
            }
            for j in all_jobs
            if "product manager" in j["title"].lower()
        ]
        raw["greenhouse_pm_jobs"] = pm_jobs
        print(f"  [Track 1] Greenhouse: {len(all_jobs)} total jobs, {len(pm_jobs)} PM roles found.")
        result.meta += f"Greenhouse: {len(all_jobs)} total, {len(pm_jobs)} PM roles. "
    except Exception as e:
        result.errors.append(f"Greenhouse fetch failed: {e}")
        print(f"  [Track 1] Greenhouse ERROR: {e}")

    # Step 2: Anthropic news page — fetch and strip to plain text
    print("  [Track 1] Fetching anthropic.com/news...")
    try:
        html = fetch_url("https://www.anthropic.com/news")
        text = extract_text(html)[:5000]  # lean context window
        raw["news_page_text"] = text
        print(f"  [Track 1] News page: extracted {len(text)} chars of text.")
        result.meta += f"News page: {len(text)} chars extracted. "
    except Exception as e:
        result.errors.append(f"Anthropic news fetch failed: {e}")
        print(f"  [Track 1] News ERROR: {e}")

    if not raw:
        result.meta = "All fetches failed — no data to process."
        return result

    # Step 3: Worker LLM call — classify and produce WorkerItems
    print("  [Track 1] Calling worker LLM to classify findings...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=TRACK_1_WORKER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Raw findings from Anthropic sources:\n\n"
                    f"{json.dumps(raw, indent=2)}"
                ),
            }
        ],
    )

    raw_text = response.content[0].text.strip()

    # Guard: strip markdown fences if Claude wrapped the output despite the instruction
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        items = json.loads(raw_text)
        result.items = items
        print(f"  [Track 1] Worker LLM produced {len(items)} WorkerItem(s).")
    except json.JSONDecodeError as e:
        result.errors.append(f"Worker LLM returned invalid JSON: {e}\nRaw: {raw_text[:200]}")
        print(f"  [Track 1] JSON parse ERROR: {e}")

    return result


# ---------------------------------------------------------------------------
# Worker Track 2 — AI Market Signals
# ---------------------------------------------------------------------------

_HN_AI_KEYWORDS = frozenset({
    "openai", "anthropic", "mistral", "perplexity", "cohere", "deepmind",
    "llm", "gpt-", "claude", "gemini", "language model", "neural net",
    "machine learning", "generative",
    "series a", "series b", "series c", "raises $", "raised $",
    "product manager", " ai ",
})


def _fetch_hn_items(max_items: int = 40) -> list[dict]:
    """Fetch HN front page RSS and return AI-relevant items."""
    xml_text = fetch_url("https://news.ycombinator.com/rss")
    root = ET.fromstring(xml_text)

    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        comments_url = (item.findtext("comments") or "").strip()
        description = (item.findtext("description") or "").strip()[:300]
        pub_date = (item.findtext("pubDate") or "").strip()

        padded = " " + (title + " " + description).lower() + " "
        if any(kw in padded for kw in _HN_AI_KEYWORDS):
            items.append({
                "title": title,
                "url": link or comments_url,
                "hn_url": comments_url,
                "description": description,
                "pub_date": pub_date,
            })

    return items[:max_items]

def _build_track_2_system() -> str:
    already_tracked = (
        f"Already tracked (Tier A): {', '.join(config.TIER_A)}\n"
        f"Already tracked (Tier B): {', '.join(config.TIER_B)}\n"
        f"Already tracked (Tier C): {', '.join(config.TIER_C)}"
    )
    career_authors = " or ".join(config.CAREER_NEWSLETTER_AUTHORS)
    return f"""\
You are the Track 2 worker in a job search monitoring system.

Target person: {config.USER_NAME}, a PM leader actively searching for a PM role.
Priority target: {config.TIER_A_PRIMARY}. Location preference: {config.USER_LOCATION} or remote.

You will receive raw text from Hacker News RSS and Gmail newsletters (AI-focused).
Return a JSON object with exactly two keys. Return ONLY valid JSON — no markdown, no commentary.

Output format:
{{
  "items": [ <WorkerItem>, ... ],
  "discovered_companies": [ <DiscoveredCompany>, ... ]
}}

WorkerItem fields:
  priority   : "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
  source     : string  — newsletter name or "Hacker News"
  url        : string  — direct link to article or email
  title      : string  — article headline or newsletter subject
  summary    : string  — 2–3 sentence factual description
  relevance  : string  — why this matters to the job search
  action     : string or null

DiscoveredCompany fields (populate whenever you spot a company that is):
  (a) AI-forward — building products or infrastructure where AI is the core, not a feature
  (b) Matches the target location OR remote-friendly
  (c) Hiring or likely to hire senior PMs based on the signal (funding, launch, growth post)
  name            : string  — company name
  reason          : string  — specific signal: "Series B $50M announced, job posts include Head of Product"
  location        : string  — "Austin, TX" | "Remote" | city
  remote_friendly : boolean
  source_url      : string  — where you found it

IMPORTANT: Do NOT include any company already on the static target list in discovered_companies.
{already_tracked}
discovered_companies is ONLY for net-new companies not already on these lists.

Priority rules for items:
  - Import AI by Jack Clark (any content) → "CRITICAL"
  - AI company funding/launch directly relevant to the target list → "HIGH"
  - General AI market signals useful for PM job search strategy → "MEDIUM"
  - {career_authors} newsletter content (any topic) → "MEDIUM" — always include; these are career development reads
  - General AI noise with no job search relevance → omit

If nothing relevant, return: {{"items": [], "discovered_companies": []}}
"""

TRACK_2_WORKER_SYSTEM = _build_track_2_system()


def run_track_2_market_signals() -> WorkerResult:
    """
    Monitor Hacker News RSS and Gmail newsletters for AI market signals.
    Also extracts DiscoveredCompany signals that Track 3 uses to expand its target list.

    Data flow:
      1. Fetch HN RSS → filter AI-relevant threads (keyword pre-filter)
      2. [TODO] Fetch Gmail newsletters via MCP: Import AI by Jack Clark, TLDR AI,
         Ben's Bites, Lenny's Newsletter, Superhuman AI, Shreyas Doshi (last 24h)
      3. Single worker LLM call → produce items[] + discovered_companies[]

    discovered_companies is consumed by Track 3 immediately after this track completes.
    """
    result = WorkerResult(track="Track 2 — AI Market Signals")
    raw: dict = {}

    # Step 1: HN RSS
    print("  [Track 2] Fetching Hacker News RSS...")
    try:
        hn_items = _fetch_hn_items()
        raw["hacker_news"] = hn_items
        print(f"  [Track 2] HN: {len(hn_items)} AI-relevant item(s) found.")
        result.meta += f"HN: {len(hn_items)} items. "
    except Exception as e:
        result.errors.append(f"HN RSS fetch failed: {e}")
        print(f"  [Track 2] HN RSS ERROR: {e}")

    # Step 2: Gmail newsletters (last 24h)
    print("  [Track 2] Fetching Gmail newsletters...")
    try:
        newsletters = fetch_newsletter_emails()
        if newsletters:
            raw["newsletters"] = newsletters
            print(f"  [Track 2] Gmail: {len(newsletters)} newsletter email(s) fetched.")
            result.meta += f"Gmail: {len(newsletters)} emails. "
        else:
            print("  [Track 2] Gmail: no newsletter emails in last 24h.")
            result.meta += "Gmail: 0 emails. "
    except RuntimeError as e:
        # Missing credentials — skip gracefully so HN still runs
        result.errors.append(f"Gmail skipped: {e}")
        print(f"  [Track 2] Gmail SKIPPED: {e}")
    except Exception as e:
        result.errors.append(f"Gmail fetch failed: {e}")
        print(f"  [Track 2] Gmail ERROR: {e}")

    if not raw:
        result.meta = result.meta.strip() or "All fetches failed."
        return result

    # Step 3: Worker LLM call — classify both HN and newsletters together
    print("  [Track 2] Calling worker LLM to classify HN + newsletter findings...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=TRACK_2_WORKER_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Raw findings (Hacker News RSS, last 24h, AI-relevant stories):\n\n"
                f"{json.dumps(raw, indent=2)}"
            ),
        }],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(raw_text)
        result.items = parsed.get("items", [])
        result.discovered_companies = parsed.get("discovered_companies", [])
        print(
            f"  [Track 2] Worker LLM: {len(result.items)} item(s), "
            f"{len(result.discovered_companies)} discovered company/companies."
        )
        result.meta += (
            f"Worker: {len(result.items)} items, "
            f"{len(result.discovered_companies)} discovered."
        )
    except json.JSONDecodeError as e:
        result.errors.append(f"Worker LLM returned invalid JSON: {e}\nRaw: {raw_text[:200]}")
        print(f"  [Track 2] JSON parse ERROR: {e}")

    return result


# ---------------------------------------------------------------------------
# Worker Track 3 — Target Company Job Boards  [STUB]
# ---------------------------------------------------------------------------

TIER_A = config.TIER_A
TIER_B = config.TIER_B
TIER_C = config.TIER_C
ALL_TARGET_COMPANIES = TIER_A + TIER_B + TIER_C


def _build_track_3_system(discovered_companies: list[DiscoveredCompany]) -> str:
    """
    Build the Track 3 worker system prompt, injecting any companies discovered
    by Track 2 as dynamic Tier C additions for this run.
    """
    dynamic_section = ""
    if discovered_companies:
        lines = ["Dynamic Tier C additions from Track 2 (check these too, same HIGH priority):"]
        for c in discovered_companies:
            loc = c["location"]
            remote = " (remote-friendly)" if c["remote_friendly"] else ""
            lines.append(f"  - {c['name']} — {loc}{remote} — {c['reason']}")
        dynamic_section = "\n" + "\n".join(lines) + "\n"

    tier_c_list = ", ".join(config.TIER_C)
    return f"""\
You are the Track 3 worker in a job search monitoring system.

Target person: {config.USER_NAME}, a PM leader, actively searching for a PM role.
Priority target: {config.TIER_A_PRIMARY}. Hard deadline: {config.DEADLINE_CONTEXT}.

You will receive raw data from LinkedIn (authenticated) and company job boards.
Produce a JSON array of WorkerItem objects. Return ONLY valid JSON — no markdown, no commentary.

Each WorkerItem must have exactly these fields:
  priority   : "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
  source     : string  — e.g. "LinkedIn (1st-degree connection)" or "OpenAI careers page"
  url        : string  — direct link (use LinkedIn search URL if no direct link)
  title      : string  — job title, connection name + company, or signal description
  summary    : string  — 2–3 sentence factual description
  relevance  : string  — why this matters to the job search specifically
  action     : string or null — concrete next step (e.g. "Message [Name] on LinkedIn before applying")

Priority rules for LinkedIn warm leads (rank ABOVE cold board equivalents):
  - 1st-degree connection at {config.TIER_A_PRIMARY} (any role) → "CRITICAL"; action = suggested outreach message
  - 1st-degree connection at Tier A + PM role open → "HIGH"; action = "contact before applying cold"
  - 1st-degree connection at Tier B + PM role open → "HIGH"; action = "contact before applying cold"
  - 1st-degree connection at Tier C (static or dynamic) + PM role open → "HIGH"; same warm-first action
  - 2nd-degree connection at {config.TIER_A_PRIMARY} or Tier A → "MEDIUM"; action = name the mutual connection for intro ask
  - LinkedIn feed post mentioning hiring at a target company → "HIGH" or "MEDIUM" per company tier

Priority rules for cold job board leads:
  - PM role at {config.TIER_A_PRIMARY} (any board) → "CRITICAL"
  - PM role at Tier A company → "HIGH"
  - PM role at Tier B company → "HIGH"
  - PM role at Tier C AI-forward company → "HIGH"
  - Irrelevant content → omit entirely

Static Tier C companies: {tier_c_list}
{dynamic_section}
If no relevant items exist, return an empty JSON array: []
"""


_PM_KEYWORDS = frozenset([
    "product manager", "head of product", "vp of product",
    "director of product", "chief product officer",
])


def _linkedin_jobs_safe(company: str) -> tuple[str, str | None]:
    """Fetch LinkedIn jobs for a company; return (text, error_or_None)."""
    try:
        return fetch_linkedin_jobs(company, max_chars=3000), None
    except Exception as e:
        return "", str(e)


def run_track_3_job_boards(
    discovered_companies: list[DiscoveredCompany] | None = None,
) -> WorkerResult:
    """
    Monitor Tier A/B/C target company job boards AND LinkedIn (authenticated) for PM roles.

    Data flow:
      1. LinkedIn Jobs — parallel search across all targets (4 workers), skip Anthropic
         (Track 1 already covers it via Greenhouse). Pre-filter to companies with PM keywords.
      2. LinkedIn Connections — 1st-degree at all Tier A companies + 2nd-degree at Anthropic.
      3. LinkedIn Feed — scan for hiring signals from connections.
      4. Worker LLM call — classify all findings into WorkerItems.

    LinkedIn warm leads always rank above cold board equivalents per escalation rules.
    """
    result = WorkerResult(track="Track 3 — Target Company Boards + LinkedIn")
    dc = discovered_companies or []
    raw: dict = {}

    # Skip TIER_A_PRIMARY — Track 1 covers it via Greenhouse API
    job_targets = [c for c in ALL_TARGET_COMPANIES if c != config.TIER_A_PRIMARY] + [c["name"] for c in dc]

    # Step 1: LinkedIn Jobs — parallel, 4 workers
    print(f"  [Track 3] LinkedIn Jobs: searching {len(job_targets)} companies (4 workers)...")
    job_results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_co = {executor.submit(_linkedin_jobs_safe, co): co for co in job_targets}
        for future in concurrent.futures.as_completed(future_to_co):
            company = future_to_co[future]
            text, err = future.result()
            if err:
                result.errors.append(f"LinkedIn Jobs [{company}]: {err}")
                print(f"  [Track 3]   ✗ {company}: {err}")
            elif text:
                job_results[company] = text
                print(f"  [Track 3]   ✓ {company}: {len(text)} chars")

    # Pre-filter: only send companies with actual PM roles to the LLM
    pm_jobs = {
        co: text
        for co, text in job_results.items()
        if any(kw in text.lower() for kw in _PM_KEYWORDS)
    }
    print(f"  [Track 3] {len(pm_jobs)}/{len(job_results)} companies have open PM roles.")
    if pm_jobs:
        raw["linkedin_jobs_with_pm_roles"] = pm_jobs

    # Step 2: LinkedIn Connections — 1st-degree at Tier A + 2nd-degree at primary target
    print(f"  [Track 3] LinkedIn Connections: Tier A (1st degree) + {config.TIER_A_PRIMARY} (2nd degree)...")
    conn_futures: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for co in TIER_A:
            conn_futures[executor.submit(fetch_linkedin_connections_at, co, "F")] = f"{co} (1st)"
        conn_futures[executor.submit(fetch_linkedin_connections_at, config.TIER_A_PRIMARY, "S")] = f"{config.TIER_A_PRIMARY} (2nd)"

        conn_results: dict[str, str] = {}
        for future in concurrent.futures.as_completed(conn_futures):
            label = conn_futures[future]
            try:
                text = future.result()
                conn_results[label] = text[:3000]
                print(f"  [Track 3]   ✓ {label}: {len(text)} chars")
            except Exception as e:
                result.errors.append(f"LinkedIn Connections [{label}]: {e}")
                print(f"  [Track 3]   ✗ {label}: {e}")

    if conn_results:
        raw["linkedin_connections"] = conn_results

    # Step 3: LinkedIn Feed
    print("  [Track 3] LinkedIn Feed...")
    try:
        feed = fetch_linkedin_feed(max_chars=5000)
        raw["linkedin_feed"] = feed
        print(f"  [Track 3]   ✓ Feed: {len(feed)} chars")
    except Exception as e:
        result.errors.append(f"LinkedIn Feed: {e}")
        print(f"  [Track 3]   ✗ Feed: {e}")

    if not raw:
        result.meta = "All fetches failed — check LinkedIn auth."
        return result

    # Step 4: Worker LLM call
    print("  [Track 3] Calling worker LLM to classify all findings...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=_build_track_3_system(dc),
        messages=[{
            "role": "user",
            "content": (
                "Raw findings from LinkedIn and target company job boards:\n\n"
                f"{json.dumps(raw, indent=2)}"
            ),
        }],
    )

    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result.items = json.loads(raw_text)
        print(f"  [Track 3] Worker LLM: {len(result.items)} item(s).")
    except json.JSONDecodeError as e:
        result.errors.append(f"Worker LLM invalid JSON: {e}\nRaw: {raw_text[:200]}")
        print(f"  [Track 3] JSON parse ERROR: {e}")

    result.meta = (
        f"LinkedIn Jobs: {len(job_results)} fetched, {len(pm_jobs)} with PM roles. "
        f"Connections: {len(conn_results)} checked. "
        f"Feed: {'yes' if 'linkedin_feed' in raw else 'failed'}."
        + (f" {len(dc)} dynamic from T2." if dc else "")
    )
    return result


# ---------------------------------------------------------------------------
# Discovery log — persists Track 2 discovery counts across runs
# ---------------------------------------------------------------------------

def _load_discovery_log() -> dict:
    if DISCOVERY_LOG.exists():
        return json.loads(DISCOVERY_LOG.read_text())
    return {}


def _verify_company_hiring(company_name: str) -> tuple[bool, str]:
    """
    Actively check LinkedIn for open PM roles at a discovered company.
    Called only when a company has appeared VERIFY_THRESHOLD times in Track 2.
    Returns (has_open_pm_roles, evidence_summary).
    """
    print(f"  [Discovery] Verifying hiring at {company_name} via LinkedIn...")
    try:
        text = fetch_linkedin_jobs(company_name, max_chars=4000)
        lower = text.lower()
        pm_signals = ["product manager", "head of product", "vp of product", "director of product"]
        found = [s for s in pm_signals if s in lower]
        if found:
            return True, f"LinkedIn confirms open PM roles ({', '.join(found)})"
        return False, "No open PM roles found on LinkedIn"
    except Exception as e:
        return False, f"LinkedIn verification failed: {e}"


def _update_discovery_log(
    discovered: list[DiscoveredCompany],
    t3_items: list[WorkerItem],
) -> list[dict]:
    """
    Increment appearance counts for each company Track 2 discovered this run.

    Recommendation logic (both conditions must be true):
      1. Count reached VERIFY_THRESHOLD OR Track 3 passively found a PM role there
      2. Verified: open PM roles confirmed via LinkedIn (active check)

    Count alone never triggers a recommendation — hiring must be confirmed.
    """
    if not discovered:
        return []

    log = _load_discovery_log()
    now = datetime.now(timezone.utc).isoformat()

    # Build set of companies Track 3 passively found HIGH/CRITICAL items for
    t3_high_sources = {
        item["source"].lower()
        for item in t3_items
        if item.get("priority") in ("CRITICAL", "HIGH")
    }

    recommendations = []

    for company in discovered:
        name = company["name"]
        entry = log.get(name, {
            "count": 0,
            "first_seen": now,
            "location": company["location"],
            "remote_friendly": company["remote_friendly"],
            "verified_hiring": False,
            "verification_evidence": "",
            "reasons": [],
        })

        entry["count"] += 1
        entry["last_seen"] = now
        if company["reason"] not in entry["reasons"]:
            entry["reasons"].append(company["reason"])

        already_static = name in ALL_TARGET_COMPANIES
        if already_static:
            log[name] = entry
            continue

        # Check if Track 3 passively found a PM role at this company
        t3_found_role = any(name.lower() in src for src in t3_high_sources)

        # Actively verify when signal is recurring or T3 already found something
        should_verify = (
            entry["count"] >= VERIFY_THRESHOLD or t3_found_role
        ) and not entry["verified_hiring"]

        if should_verify:
            verified, evidence = _verify_company_hiring(name)
            if verified:
                entry["verified_hiring"] = True
                entry["verification_evidence"] = evidence
            else:
                print(f"  [Discovery] {name}: signal present but no open PM roles confirmed — skipping.")

        if entry["verified_hiring"]:
            recommendations.append({
                "name": name,
                "count": entry["count"],
                "t3_found_role": t3_found_role,
                "location": entry["location"],
                "remote_friendly": entry["remote_friendly"],
                "latest_reason": entry["reasons"][-1],
                "verification_evidence": entry["verification_evidence"],
            })

        log[name] = entry

    DISCOVERY_LOG.parent.mkdir(exist_ok=True)
    DISCOVERY_LOG.write_text(json.dumps(log, indent=2))
    return recommendations


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_orchestrator() -> str:
    """
    Execution order:
      Phase 1 (parallel)   — Track 1 + Track 2
      Phase 2 (sequential) — Track 3, seeded with Track 2's discovered_companies

    Track 3 depends on Track 2 because any AI company surfaced in newsletters or HN
    (funding round, product launch, hiring post) is immediately checked for PM roles
    in the same daily run. This ensures no warm signal discovered in T2 sits unacted-on
    until the next day's T3 run.
    """
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Market Watch starting...")
    print("=" * 72)
    print("Phase 1: Launching Track 1 + Track 2 in parallel...")
    print("=" * 72)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_t1 = executor.submit(run_track_1_anthropic)
        future_t2 = executor.submit(run_track_2_market_signals)
        result_t1 = future_t1.result()
        result_t2 = future_t2.result()

    print()
    print("=" * 72)
    _static = set(ALL_TARGET_COMPANIES)
    dc = [c for c in result_t2.discovered_companies if c["name"] not in _static]
    if dc:
        print(f"Phase 2: Track 2 discovered {len(dc)} new company signal(s) — passing to Track 3:")
        for c in dc:
            print(f"  + {c['name']} ({c['location']}) — {c['reason']}")
    else:
        print("Phase 2: No new companies discovered by Track 2.")
    print("Launching Track 3...")
    print("=" * 72)

    result_t3 = run_track_3_job_boards(discovered_companies=dc)

    # Update discovery log and check for Tier C promotion recommendations
    promo_recs = _update_discovery_log(dc, result_t3.items)
    if promo_recs:
        print()
        print("=" * 72)
        print(f"TIER C PROMOTION RECOMMENDATIONS ({len(promo_recs)} company/companies)")
        print("=" * 72)
        for r in promo_recs:
            extra = " — T3 found role" if r["t3_found_role"] else f" — seen {r['count']}x in Track 2"
            print(f"  → Add to TIER_C: {r['name']} ({r['location']}){extra}")
            print(f"     Verified: {r['verification_evidence']}")

    print()
    print("=" * 72)
    print("WORKER RESULTS SUMMARY")
    print("=" * 72)
    for result in (result_t1, result_t2, result_t3):
        status = "LIVE" if "STUB" not in result.meta else "stub"
        print(f"\n[{status.upper()}] {result.track}")
        print(f"  items  : {len(result.items)}")
        print(f"  errors : {result.errors or 'none'}")
        print(f"  meta   : {result.meta.strip()}")

    print()
    print("=" * 72)
    print("TRACK 1 WORKER ITEMS (raw, before synthesis)")
    print("=" * 72)
    if result_t1.items:
        print(json.dumps(result_t1.items, indent=2))
    else:
        print("  (no items)")

    print()
    print("=" * 72)
    print("TRACK 2 WORKER ITEMS (raw, before synthesis)")
    print("=" * 72)
    if result_t2.items:
        print(json.dumps(result_t2.items, indent=2))
    else:
        print("  (no items)")
    if result_t2.discovered_companies:
        print()
        print("  Discovered companies:")
        print(json.dumps(result_t2.discovered_companies, indent=2))

    print()
    print("=" * 72)
    print("TRACK 3 WORKER ITEMS (raw, before synthesis)")
    print("=" * 72)
    if result_t3.items:
        print(json.dumps(result_t3.items, indent=2))
    else:
        print("  (no items)")

    # Assemble all findings for the orchestrator synthesis call
    worker_findings = json.dumps(
        {
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "tracks": [
                result_t1.to_dict(),
                result_t2.to_dict(),
                result_t3.to_dict(),
            ],
            "tier_c_promotion_recommendations": promo_recs,
        },
        indent=2,
    )

    print()
    print("=" * 72)
    print("ORCHESTRATOR SYNTHESIS CALL")
    print("=" * 72)
    print("Sending all WorkerItems to orchestrator LLM for escalation + digest...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here are the raw findings from all three worker tracks. "
                    "Apply your escalation rules and produce the structured digest.\n\n"
                    f"```json\n{worker_findings}\n```"
                ),
            }
        ],
    )

    all_items = result_t1.items + result_t2.items + result_t3.items
    return response.content[0].text, all_items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

class _Tee:
    """Write to multiple streams simultaneously (terminal + log file)."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)

    def flush(self):
        for s in self._streams:
            s.flush()

    def fileno(self):
        return self._streams[0].fileno()


if __name__ == "__main__":
    import argparse
    import sys as _sys
    from output.digest import send_digest, send_weekly_digest

    parser = argparse.ArgumentParser(description="ArunOS Market Watch")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip y/n prompts and send emails automatically (used by launchd scheduler).",
    )
    args = parser.parse_args()

    log_dir = pathlib.Path(__file__).parent.parent / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md"

    with open(log_path, "w", buffering=1) as _log_file:
        _sys.stdout = _Tee(_sys.__stdout__, _log_file)
        try:
            digest, all_items = run_orchestrator()
            print()
            print("=" * 72)
            print("FINAL DIGEST")
            print("=" * 72)
            print(digest)
            print("=" * 72)
        finally:
            _sys.stdout = _sys.__stdout__

    print(f"\nFull log saved → {log_path}")

    # Daily email: CRITICAL + HIGH (always)
    send_digest(digest, all_items, log_path, auto=args.auto)

    # Weekly digest: MEDIUM + META (Sundays only in auto mode; always prompt when manual)
    is_sunday = datetime.now().weekday() == 6
    if not args.auto or is_sunday:
        send_weekly_digest(digest, all_items, log_path, auto=args.auto)
