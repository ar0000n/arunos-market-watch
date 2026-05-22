# config.py — personalize this for your job search.
#
# This is the only file you need to edit to tailor the agent to you.
# After changing anything here, re-run the agent to see the effect.

# ── Who you are ──────────────────────────────────────────────────────────────

CANDIDATE_PROFILE = """\
- ~13 years in product; currently Director of Product & Design at Wayfair; prior: Associate Director (Wayfair), PM Manager (Apple), Principal PM (Zest AI), Senior Manager Ad Product (Hulu), PM + SDE (Microsoft)
- CS depth: MS Computer Science (USC); began career as SDE at Microsoft (Exchange Server); actively building multi-agent AI side projects (ChessDebrief, Learning Plan, Bloom — all live)
- Current scope: leads product + design for customer service, incidents, returns, and supplier support — millions of interactions/year, >$1B post-order exposure
- Proven financial impact: $250M+ in measurable cost savings across two consecutive Wayfair roles; reduced cost as % of revenue from 5.1% → 3.6%
- AI/ML execution: shipped GenAI + agentic workflows at production scale (fraud detection, resolution automation); built ML model monitoring SaaS (ZAMLMonitor) at Zest AI
- 0→1 track record: ZAMLMonitor (Zest AI), Apple One and Fitness acquisition journeys at launch, three live AI-native side projects
- Platform scale: owned Hulu's $2B ads platform and Microsoft's $2B online ads delivery; fluent in technical platform PM work
- Cross-functional leader: partners across engineering, data science, design, and ops; authored Wayfair's org-wide next-gen AI contact center strategy
- Status: actively searching; Austin TX, willing to relocate for Tier A targets; pending Xometry offer, deadline Aug 15 2026
- Target: Senior/Director PM at an AI-first company — strongest fit at the intersection of AI product, developer tooling, or platform monetization"""

USER_NAME     = "Arun Ramalingam"
USER_ROLE     = "Product Management leader (~10 years, including PM leadership at Wayfair)"
USER_LOCATION = "Austin, TX"

# The hard deadline that drives urgency throughout the digest.
# Example: "pending offer at Xometry, decision required by Aug 15 2026"
DEADLINE_CONTEXT = "pending offer at Xometry, decision required by Aug 15 2026"

# ── Target companies ─────────────────────────────────────────────────────────
#
# Track 1 monitors TIER_A_PRIMARY daily with a dedicated Greenhouse + news check.
# Track 3 covers all companies in TIER_A + TIER_B + TIER_C via LinkedIn + job boards.
#
# Tier A  — your top targets; willing to relocate
# Tier B  — strong targets; prefer Austin-based or remote
# Tier C  — AI-forward companies; Austin or remote-first; PM roles surface same day

TIER_A_PRIMARY = "Anthropic"    # Your #1 target — gets its own dedicated track

TIER_A = [
    "Anthropic",
    "OpenAI",
    "Mistral AI",
    "Google DeepMind",
]

TIER_B = [
    "Indeed",
    "Apple",
    "Tesla",
    "Oracle",
    "Xometry",
]

TIER_C = [
    # Austin AI companies
    "SparkCognition",
    "CrowdStrike",
    "Enverus",
    # Remote-first AI (well-funded, PM-rich product orgs)
    "Cohere",
    "Perplexity AI",
    "Glean",
    "Scale AI",
    "Harvey",
    "Writer",
    "ElevenLabs",
]

# ── Gmail newsletters ─────────────────────────────────────────────────────────
#
# From-addresses of newsletters you subscribe to.
# Fetched via IMAP (last 26h) and passed to the Track 2 worker LLM.
# Add any newsletter whose sender address you know.

NEWSLETTER_SENDERS = [
    "importai@substack.com",               # Import AI — Jack Clark
    "dan@tldrnewsletter.com",              # TLDR AI
    "bensbites@substack.com",              # Ben's Bites
    "lenny@substack.com",                  # Lenny's Newsletter
    "superhuman@mail.joinsuperhuman.ai",   # Superhuman AI
    "shreyasdoshi@substack.com",           # Shreyas Doshi
]

# Authors whose newsletters are always included at MEDIUM priority, regardless of
# whether the content is directly about AI market signals. These are career reads.
CAREER_NEWSLETTER_AUTHORS = ["Lenny Rachitsky", "Shreyas Doshi"]
