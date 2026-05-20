"""
browser.py — Authenticated LinkedIn browser for Market Watch Track 3.

Extracts LinkedIn session cookies live from your running Chrome (via browser_cookie3),
injects them into a headless Playwright Chromium context, and scrapes LinkedIn pages.

No setup script needed. No Chrome profile locking. Works while Chrome is open.
Re-reads cookies on every call, so session refreshes automatically.
"""

import browser_cookie3
from playwright.sync_api import sync_playwright, Page, BrowserContext


def _get_linkedin_storage_state() -> dict:
    """
    Extract LinkedIn cookies from the running Chrome and return a
    Playwright storage_state dict. Raises RuntimeError if li_at is missing.
    """
    raw = browser_cookie3.chrome(domain_name=".linkedin.com")
    cookies = []
    for c in raw:
        cookies.append({
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
            "path": c.path or "/",
            "expires": int(c.expires) if c.expires else -1,
            "httpOnly": bool(getattr(c, "has_nonstandard_attr", lambda _: False)("HttpOnly")),
            "secure": bool(c.secure),
            "sameSite": "None",
        })

    names = {c["name"] for c in cookies}
    if "li_at" not in names:
        raise RuntimeError(
            "li_at cookie not found in Chrome. "
            "Make sure you're logged into LinkedIn in Chrome."
        )

    return {"cookies": cookies, "origins": []}


def _page_text(page: Page, max_chars: int = 8000) -> str:
    text: str = page.evaluate("() => document.body.innerText")
    return text[:max_chars]


def _is_logged_in(page: Page) -> bool:
    return (
        "linkedin.com/login" not in page.url
        and "linkedin.com/checkpoint" not in page.url
    )


def fetch_linkedin_page(url: str, wait_for: str | None = None, timeout: int = 25_000) -> str:
    """
    Fetch a LinkedIn URL using cookies extracted from Chrome.
    Returns visible page text. Raises RuntimeError if session is expired.
    """
    storage_state = _get_linkedin_storage_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx: BrowserContext = browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(url, timeout=timeout)

        page.wait_for_load_state("load", timeout=timeout)
        if wait_for:
            try:
                page.wait_for_selector(wait_for, timeout=min(timeout, 12_000))
            except Exception:
                page.wait_for_timeout(3000)  # fallback: wait for JS render
        else:
            page.wait_for_timeout(3000)

        if not _is_logged_in(page):
            browser.close()
            raise RuntimeError(
                "LinkedIn redirected to login. "
                "Re-authenticate in Chrome and try again."
            )

        text = _page_text(page)
        browser.close()
        return text


def fetch_linkedin_jobs(company: str, max_chars: int = 6000) -> str:
    """Search LinkedIn Jobs for PM roles at a specific company (last 24h)."""
    url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords=Product+Manager+{company.replace(' ', '+')}"
        "&f_TPR=r86400"
    )
    return fetch_linkedin_page(url, wait_for=".jobs-search-results-list", timeout=30_000)[:max_chars]


def fetch_linkedin_connections_at(company: str, degree: str = "F", max_chars: int = 6000) -> str:
    """
    Search LinkedIn connections at a specific company.
    degree: "F" = 1st-degree (direct referral), "S" = 2nd-degree (intro path).
    """
    url = (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={company.replace(' ', '+')}"
        f"&network=%5B%22{degree}%22%5D"
    )
    return fetch_linkedin_page(url, wait_for=".search-results-container", timeout=30_000)[:max_chars]


def fetch_linkedin_feed(max_chars: int = 8000) -> str:
    """Fetch the LinkedIn feed to detect hiring signals from connections."""
    return fetch_linkedin_page(
        "https://www.linkedin.com/feed/",
        wait_for=".feed-shared-update-v2",
        timeout=30_000,
    )[:max_chars]
