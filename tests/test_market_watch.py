"""Tests for agents/market_watch.py — schema, discovery log, orchestration logic."""

import json
from datetime import datetime
from unittest.mock import patch

from agents.market_watch import (
    WorkerResult,
    WorkerItem,
    DiscoveredCompany,
    _build_track_3_system,
    _load_discovery_log,
    _verify_company_hiring,
    _update_discovery_log,
    run_track_3_job_boards,
    TIER_A, TIER_B, TIER_C,
    VERIFY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_company(name="Acme AI", location="Remote", remote=True) -> DiscoveredCompany:
    return DiscoveredCompany(
        name=name,
        reason="Series B announced, hiring PMs",
        location=location,
        remote_friendly=remote,
        source_url="https://example.com",
    )


def make_item(priority="HIGH", source="test source") -> WorkerItem:
    return WorkerItem(
        priority=priority,
        source=source,
        url="https://example.com/job",
        title="Senior PM",
        summary="A PM role.",
        relevance="Relevant.",
        action=None,
    )


# ---------------------------------------------------------------------------
# WorkerResult
# ---------------------------------------------------------------------------

class TestWorkerResult:
    def test_init_defaults(self):
        r = WorkerResult("Track 1")
        assert r.track == "Track 1"
        assert r.items == []
        assert r.errors == []
        assert r.meta == ""
        assert r.discovered_companies == []

    def test_to_dict_includes_all_keys(self):
        r = WorkerResult("Track 2")
        d = r.to_dict()
        assert set(d.keys()) == {"track", "timestamp", "items", "errors", "meta", "discovered_companies"}

    def test_to_dict_preserves_items(self):
        r = WorkerResult("Track 1")
        r.items = [make_item()]
        assert r.to_dict()["items"][0]["priority"] == "HIGH"

    def test_to_dict_preserves_discovered_companies(self):
        r = WorkerResult("Track 2")
        r.discovered_companies = [make_company()]
        assert r.to_dict()["discovered_companies"][0]["name"] == "Acme AI"

    def test_timestamp_is_utc_iso(self):
        r = WorkerResult("Track 1")
        # Should parse as valid ISO timestamp
        dt = datetime.fromisoformat(r.timestamp)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _build_track_3_system
# ---------------------------------------------------------------------------

class TestBuildTrack3System:
    def test_no_discovered_companies(self):
        prompt = _build_track_3_system([])
        assert "Dynamic Tier C" not in prompt
        assert "Static Tier C" in prompt

    def test_discovered_companies_injected(self):
        companies = [
            make_company("Cognition AI", "Remote", True),
            make_company("Armada", "Austin, TX", False),
        ]
        prompt = _build_track_3_system(companies)
        assert "Cognition AI" in prompt
        assert "Armada" in prompt
        assert "Dynamic Tier C" in prompt

    def test_remote_friendly_label_present(self):
        prompt = _build_track_3_system([make_company("TestCo", "Remote", True)])
        assert "remote-friendly" in prompt

    def test_non_remote_no_label(self):
        prompt = _build_track_3_system([make_company("TestCo", "Austin, TX", False)])
        assert "remote-friendly" not in prompt

    def test_static_tier_c_always_present(self):
        prompt = _build_track_3_system([])
        for company in ["SparkCognition", "CrowdStrike", "Cohere", "Glean"]:
            assert company in prompt

    def test_reason_injected(self):
        c = make_company("Foo AI")
        c["reason"] = "raised $100M Series C"
        prompt = _build_track_3_system([c])
        assert "raised $100M Series C" in prompt


# ---------------------------------------------------------------------------
# _load_discovery_log
# ---------------------------------------------------------------------------

class TestLoadDiscoveryLog:
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        missing = tmp_path / "nope.json"
        with patch("agents.market_watch.DISCOVERY_LOG", missing):
            assert _load_discovery_log() == {}

    def test_returns_parsed_content(self, tmp_path):
        log_file = tmp_path / "log.json"
        log_file.write_text(json.dumps({"Acme AI": {"count": 2}}))
        with patch("agents.market_watch.DISCOVERY_LOG", log_file):
            result = _load_discovery_log()
        assert result["Acme AI"]["count"] == 2


# ---------------------------------------------------------------------------
# _verify_company_hiring
# ---------------------------------------------------------------------------

class TestVerifyCompanyHiring:
    def test_returns_true_for_product_manager_signal(self):
        with patch("agents.market_watch.fetch_linkedin_jobs", return_value="Senior Product Manager role open"):
            found, evidence = _verify_company_hiring("Acme AI")
        assert found is True
        assert "product manager" in evidence.lower()

    def test_returns_true_for_head_of_product(self):
        with patch("agents.market_watch.fetch_linkedin_jobs", return_value="Head of Product wanted"):
            found, _ = _verify_company_hiring("Acme AI")
        assert found is True

    def test_returns_true_for_vp_of_product(self):
        with patch("agents.market_watch.fetch_linkedin_jobs", return_value="VP of Product opening"):
            found, _ = _verify_company_hiring("Acme AI")
        assert found is True

    def test_returns_false_when_no_pm_roles(self):
        with patch("agents.market_watch.fetch_linkedin_jobs", return_value="Software Engineer openings only"):
            found, evidence = _verify_company_hiring("Acme AI")
        assert found is False
        assert "No open PM roles" in evidence

    def test_returns_false_on_exception(self):
        with patch("agents.market_watch.fetch_linkedin_jobs", side_effect=RuntimeError("network error")):
            found, evidence = _verify_company_hiring("Acme AI")
        assert found is False
        assert "failed" in evidence.lower()


# ---------------------------------------------------------------------------
# _update_discovery_log
# ---------------------------------------------------------------------------

class TestUpdateDiscoveryLog:
    def test_empty_discovered_returns_empty(self, tmp_path):
        log_file = tmp_path / "log.json"
        with patch("agents.market_watch.DISCOVERY_LOG", log_file):
            recs = _update_discovery_log([], [])
        assert recs == []
        assert not log_file.exists()

    def test_first_appearance_logged_no_verification(self, tmp_path):
        log_file = tmp_path / "log.json"
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring") as mock_verify:
            recs = _update_discovery_log([make_company("NewCo")], [])

        mock_verify.assert_not_called()
        assert recs == []
        log = json.loads(log_file.read_text())
        assert log["NewCo"]["count"] == 1

    def test_static_company_skipped(self, tmp_path):
        log_file = tmp_path / "log.json"
        # Seed with 1 prior appearance
        log_file.write_text(json.dumps({
            TIER_C[0]: {"count": 1, "first_seen": "x", "location": "Remote",
                        "remote_friendly": True, "verified_hiring": False,
                        "verification_evidence": "", "reasons": ["prior"]}
        }))
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring") as mock_verify:
            recs = _update_discovery_log([make_company(TIER_C[0])], [])

        mock_verify.assert_not_called()
        assert recs == []

    def test_verification_triggered_at_threshold(self, tmp_path):
        log_file = tmp_path / "log.json"
        log_file.write_text(json.dumps({
            "NewCo": {"count": VERIFY_THRESHOLD - 1, "first_seen": "x",
                      "location": "Remote", "remote_friendly": True,
                      "verified_hiring": False, "verification_evidence": "",
                      "reasons": ["prior"]}
        }))
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring", return_value=(True, "LinkedIn confirms PM roles")) as mock_verify:
            recs = _update_discovery_log([make_company("NewCo")], [])

        mock_verify.assert_called_once_with("NewCo")
        assert len(recs) == 1
        assert recs[0]["name"] == "NewCo"
        assert recs[0]["verification_evidence"] == "LinkedIn confirms PM roles"

    def test_no_recommendation_when_verification_fails(self, tmp_path):
        log_file = tmp_path / "log.json"
        log_file.write_text(json.dumps({
            "NewCo": {"count": VERIFY_THRESHOLD - 1, "first_seen": "x",
                      "location": "Remote", "remote_friendly": True,
                      "verified_hiring": False, "verification_evidence": "",
                      "reasons": ["prior"]}
        }))
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring", return_value=(False, "No PM roles found")):
            recs = _update_discovery_log([make_company("NewCo")], [])

        assert recs == []

    def test_t3_passive_role_triggers_early_verification(self, tmp_path):
        log_file = tmp_path / "log.json"
        # Only 1 appearance so far (below threshold)
        log_file.write_text(json.dumps({
            "NewCo": {"count": 1, "first_seen": "x", "location": "Remote",
                      "remote_friendly": True, "verified_hiring": False,
                      "verification_evidence": "", "reasons": ["prior"]}
        }))
        t3_items = [make_item(priority="HIGH", source="newco careers page")]
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring", return_value=(True, "Confirmed")) as mock_verify:
            recs = _update_discovery_log([make_company("NewCo")], t3_items)

        mock_verify.assert_called_once()
        assert len(recs) == 1

    def test_already_verified_not_re_verified(self, tmp_path):
        log_file = tmp_path / "log.json"
        log_file.write_text(json.dumps({
            "NewCo": {"count": 5, "first_seen": "x", "location": "Remote",
                      "remote_friendly": True, "verified_hiring": True,
                      "verification_evidence": "already confirmed",
                      "reasons": ["prior"]}
        }))
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring") as mock_verify:
            recs = _update_discovery_log([make_company("NewCo")], [])

        mock_verify.assert_not_called()
        assert len(recs) == 1  # still recommended since verified_hiring=True

    def test_count_incremented_across_runs(self, tmp_path):
        log_file = tmp_path / "log.json"
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring", return_value=(False, "none")):
            _update_discovery_log([make_company("NewCo")], [])
            _update_discovery_log([make_company("NewCo")], [])

        log = json.loads(log_file.read_text())
        assert log["NewCo"]["count"] == 2

    def test_reasons_deduplicated(self, tmp_path):
        log_file = tmp_path / "log.json"
        with patch("agents.market_watch.DISCOVERY_LOG", log_file), \
             patch("agents.market_watch._verify_company_hiring", return_value=(False, "none")):
            c = make_company("NewCo")
            c["reason"] = "same reason"
            _update_discovery_log([c], [])
            _update_discovery_log([c], [])

        log = json.loads(log_file.read_text())
        assert log["NewCo"]["reasons"].count("same reason") == 1


# ---------------------------------------------------------------------------
# run_track_3_job_boards (stub behaviour)
# ---------------------------------------------------------------------------

class TestRunTrack3JobBoards:
    def test_returns_worker_result(self):
        r = run_track_3_job_boards()
        assert isinstance(r, WorkerResult)
        assert "Track 3" in r.track

    def test_stub_meta_reports_static_count(self):
        r = run_track_3_job_boards()
        total = len(TIER_A) + len(TIER_B) + len(TIER_C)
        assert str(total) in r.meta

    def test_stub_meta_lists_dynamic_companies(self):
        dc = [make_company("Cognition AI"), make_company("Armada")]
        r = run_track_3_job_boards(discovered_companies=dc)
        assert "Cognition AI" in r.meta
        assert "Armada" in r.meta

    def test_no_discovered_companies_by_default(self):
        r = run_track_3_job_boards()
        assert "dynamic" not in r.meta.lower() or "0 dynamic" in r.meta

    def test_accepts_none_discovered_companies(self):
        r = run_track_3_job_boards(discovered_companies=None)
        assert isinstance(r, WorkerResult)


# ---------------------------------------------------------------------------
# Tier list integrity
# ---------------------------------------------------------------------------

class TestTierLists:
    def test_no_duplicates_across_tiers(self):
        all_companies = TIER_A + TIER_B + TIER_C
        assert len(all_companies) == len(set(all_companies)), "Duplicate company across tiers"

    def test_tier_a_contains_anthropic(self):
        assert "Anthropic" in TIER_A

    def test_tier_c_has_austin_and_remote_companies(self):
        # At least some Austin and some remote — not all one type
        assert "SparkCognition" in TIER_C  # Austin
        assert "Cohere" in TIER_C           # Remote
