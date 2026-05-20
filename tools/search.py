"""
search.py — URL fetching and HTML text extraction for worker tracks.
Uses stdlib only (urllib, html.parser) — no extra dependencies.
"""

import urllib.request
import urllib.error
from html.parser import HTMLParser


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch URL and return response body decoded as UTF-8."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    """Strip HTML tags, skip script/style/head blocks, return plain text."""

    _SKIP = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._depth == 0:
            chunk = data.strip()
            if chunk:
                self._parts.append(chunk)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def extract_text(html: str) -> str:
    """Return plain text from HTML, skipping script/style/head blocks."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()
