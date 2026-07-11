"""Filter tests (PLAN.md §Test cases). Ground Rule 5: every filter rule gets a test.

The title-tier and eligibility cases are the Phase 2/3 acceptance criteria and run
against src/filters.py. The config-load tests are the Phase 0 acceptance check.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config"


# --------------------------------------------------------------------------------------
# Phase 0 — real tests (run now)
# --------------------------------------------------------------------------------------
def test_titles_yaml_loads_with_expected_shape():
    data = yaml.safe_load((CONFIG / "titles.yaml").read_text(encoding="utf-8"))
    for key in ("tier1", "tier2", "tier3", "hard_exclude", "soft_downrank"):
        assert isinstance(data.get(key), list) and data[key], f"missing/empty: {key}"
    assert data.get("also_match_intern") is True


def test_policy_yaml_loads_with_expected_shape():
    data = yaml.safe_load((CONFIG / "policy.yaml").read_text(encoding="utf-8"))
    for key in ("alert_eligibilities", "digest_eligibilities", "drop_eligibilities"):
        assert isinstance(data.get(key), list)
    assert isinstance(data.get("max_alerts_per_run"), int)


def test_companies_yaml_loads():
    # Placeholder before the resolver runs; a list after. Either way it must parse.
    data = yaml.safe_load((CONFIG / "companies.yaml").read_text(encoding="utf-8"))
    assert data is None or isinstance(data, list)


# --------------------------------------------------------------------------------------
# Phase 2/3 — acceptance cases
# --------------------------------------------------------------------------------------
# (title, expected_tier, expected_flags_subset)
TITLE_CASES = [
    ("GTM Engineer", 1, []),
    ("Go-To-Market Engineer", 1, []),
    ("Growth Engineer", 1, []),
    ("Revenue Systems Engineer", 1, []),         # "systems" is NOT a dev-exclude keyword
    ("Senior GTM Engineer", 1, ["senior_downrank"]),
    ("Director, Revenue Operations", 0, ["hard_exclude"]),
    ("GTM Operations Manager", 2, []),
    ("Technical Growth Lead", 2, []),            # tier match beats `lead` downrank
    ("Operations Engineer, Revenue", 1, []),     # order-insensitive rotation still works
    ("GTM Engineer Intern", 1, []),
    # 2026-07-11 tightening — the SE/FDE firehose + pure-dev + industrial titles now drop.
    ("Solutions Engineer", 0, []),               # removed from tier3 entirely
    ("Forward Deployed Engineer", 0, []),        # removed from tier3 entirely
    ("Android Engineer, Growth", 0, ["hard_exclude"]),        # dev role in a growth org
    ("Senior Software Engineer, Growth", 0, ["hard_exclude"]),
    ("Full Stack Engineer, Growth", 0, ["hard_exclude"]),
    ("Security Engineer", 0, ["hard_exclude"]),               # cybersecurity, not GTM
    ("Gas Pipeline Engineer", 0, ["hard_exclude"]),           # industrial, not sales pipeline
]

# (location_raw, description_snippet, expected_eligibility)
ELIGIBILITY_CASES = [
    ("Remote (US)", "", "US_REMOTE_ONLY"),
    ("Remote — United States", "", "US_REMOTE_ONLY"),
    ("Remote - Anywhere", "", "GLOBAL_REMOTE"),
    ("Fully remote, work from anywhere", "", "GLOBAL_REMOTE"),
    ("Bengaluru, India", "", "INDIA_ELIGIBLE"),
    ("Remote (APAC)", "", "INDIA_ELIGIBLE"),
    ("New York, NY", "visa sponsorship available for exceptional candidates", "SPONSORSHIP_POSITIVE"),
    ("San Francisco", "we are unable to sponsor visas at this time", "SPONSORSHIP_NEGATIVE_ONSITE"),
    ("Remote", "must be authorized to work in the United States without sponsorship", "US_REMOTE_ONLY"),
    ("", "", "UNKNOWN"),
    # description "global" marketing may only upgrade an UNRESTRICTED location
    ("Remote", "we are a remote-first, global company", "GLOBAL_REMOTE"),
    ("Sweden (Remote)", "we are a remote-first, global company", "UNKNOWN"),
]


@pytest.mark.parametrize("title, tier, flags", TITLE_CASES)
def test_title_tier(title, tier, flags):
    from src import filters

    result = filters.classify_title(title)
    assert result.tier == tier
    for flag in flags:
        assert flag in result.flags


@pytest.mark.parametrize("location, desc, expected", ELIGIBILITY_CASES)
def test_eligibility(location, desc, expected):
    from src import filters

    assert filters.classify_eligibility(location, desc) == expected
