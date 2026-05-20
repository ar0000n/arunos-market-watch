"""Tests for tools/browser.py — LinkedIn cookie extraction and page fetching."""

import pytest
from unittest.mock import MagicMock, patch
from tools.browser import (
    _get_linkedin_storage_state,
    _is_logged_in,
    _page_text,
    fetch_linkedin_jobs,
    fetch_linkedin_connections_at,
    fetch_linkedin_feed,
)


def _make_cookie(name, value, domain=".linkedin.com", path="/", expires=9999999999, secure=True):
    c = MagicMock()
    c.name = name
    c.value = value
    c.domain = domain
    c.path = path
    c.expires = expires
    c.secure = secure
    return c


class TestGetLinkedInStorageState:
    def test_returns_storage_state_with_cookies(self):
        cookies = [
            _make_cookie("li_at", "abc123"),
            _make_cookie("JSESSIONID", "sess456"),
        ]
        with patch("tools.browser.browser_cookie3.chrome", return_value=iter(cookies)):
            state = _get_linkedin_storage_state()

        assert "cookies" in state
        assert "origins" in state
        names = [c["name"] for c in state["cookies"]]
        assert "li_at" in names
        assert "JSESSIONID" in names

    def test_raises_if_li_at_missing(self):
        cookies = [_make_cookie("bcookie", "xyz")]
        with patch("tools.browser.browser_cookie3.chrome", return_value=iter(cookies)):
            with pytest.raises(RuntimeError, match="li_at cookie not found"):
                _get_linkedin_storage_state()

    def test_domain_prefixed_with_dot(self):
        cookies = [_make_cookie("li_at", "val", domain="linkedin.com")]
        with patch("tools.browser.browser_cookie3.chrome", return_value=iter(cookies)):
            state = _get_linkedin_storage_state()
        c = next(c for c in state["cookies"] if c["name"] == "li_at")
        assert c["domain"].startswith(".")

    def test_none_value_becomes_empty_string(self):
        cookies = [_make_cookie("li_at", None)]
        with patch("tools.browser.browser_cookie3.chrome", return_value=iter(cookies)):
            state = _get_linkedin_storage_state()
        c = next(c for c in state["cookies"] if c["name"] == "li_at")
        assert c["value"] == ""

    def test_none_expires_becomes_minus_one(self):
        c = _make_cookie("li_at", "v")
        c.expires = None
        with patch("tools.browser.browser_cookie3.chrome", return_value=iter([c])):
            state = _get_linkedin_storage_state()
        cookie = next(x for x in state["cookies"] if x["name"] == "li_at")
        assert cookie["expires"] == -1


class TestIsLoggedIn:
    def test_feed_url_is_logged_in(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/feed/"
        assert _is_logged_in(page) is True

    def test_login_url_is_not_logged_in(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/login"
        assert _is_logged_in(page) is False

    def test_checkpoint_url_is_not_logged_in(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/checkpoint/challenge"
        assert _is_logged_in(page) is False

    def test_jobs_url_is_logged_in(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/search/?keywords=PM"
        assert _is_logged_in(page) is True


class TestPageText:
    def test_truncates_to_max_chars(self):
        page = MagicMock()
        page.evaluate.return_value = "a" * 10000
        assert len(_page_text(page, max_chars=500)) == 500

    def test_short_text_returned_in_full(self):
        page = MagicMock()
        page.evaluate.return_value = "short text"
        assert _page_text(page, max_chars=8000) == "short text"


class TestFetchLinkedInJobs:
    def test_url_contains_company_and_timeframe(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="results") as mock_fetch:
            fetch_linkedin_jobs("Anthropic")
        url = mock_fetch.call_args[0][0]
        assert "Product+Manager+Anthropic" in url
        assert "f_TPR=r86400" in url

    def test_multi_word_company_encoded(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="x") as mock_fetch:
            fetch_linkedin_jobs("Perplexity AI")
        url = mock_fetch.call_args[0][0]
        assert "Perplexity+AI" in url

    def test_result_truncated_to_max_chars(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="x" * 10000):
            result = fetch_linkedin_jobs("Cohere", max_chars=100)
        assert len(result) == 100


class TestFetchLinkedInConnectionsAt:
    def test_first_degree_network_param(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="x") as mock_fetch:
            fetch_linkedin_connections_at("Anthropic", degree="F")
        url = mock_fetch.call_args[0][0]
        assert "%22F%22" in url

    def test_second_degree_network_param(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="x") as mock_fetch:
            fetch_linkedin_connections_at("OpenAI", degree="S")
        url = mock_fetch.call_args[0][0]
        assert "%22S%22" in url


class TestFetchLinkedInFeed:
    def test_hits_feed_url(self):
        with patch("tools.browser.fetch_linkedin_page", return_value="feed content") as mock_fetch:
            result = fetch_linkedin_feed()
        url = mock_fetch.call_args[0][0]
        assert "linkedin.com/feed/" in url
        assert result == "feed content"
