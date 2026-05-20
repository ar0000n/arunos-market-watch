"""
Verify that Market Watch can read your LinkedIn session from Chrome.

Usage:
    .venv/bin/python setup_linkedin_auth.py

If this fails, open Chrome and log into linkedin.com, then re-run.
No separate login step is needed — the agent reads cookies live from Chrome.
"""

import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])

from tools.browser import _get_linkedin_storage_state, fetch_linkedin_page


def main() -> None:
    print("Checking LinkedIn cookies in Chrome...")
    try:
        state = _get_linkedin_storage_state()
        names = [c["name"] for c in state["cookies"]]
        print(f"  Found {len(names)} LinkedIn cookies: {', '.join(names)}")
        print()
        print("Fetching LinkedIn feed to confirm session works...")
        text = fetch_linkedin_page("https://www.linkedin.com/feed/", timeout=30_000)
        print(f"  OK — got {len(text)} chars from LinkedIn feed.")
        print()
        print("LinkedIn session is live. Market Watch Track 3 is ready.")
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
