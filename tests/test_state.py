"""State tests (PLAN.md §State & diffing). Ground Rule 5.

Covers load/diff/record/prune/save and the first-run signal that seed mode keys off.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src import state
from src.normalize import Job

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)


def mkjob(jid: str, company: str = "Acme", title: str = "GTM Engineer") -> Job:
    return Job(id=jid, company=company, title=title, location_raw="Remote",
               workplace="remote", url=f"https://x/{jid}", posted_at="", description="",
               source_ats="greenhouse")


# --- load -------------------------------------------------------------------------------
def test_load_missing_file_is_empty(tmp_path):
    assert state.load_state(tmp_path / "nope.json") == {}


def test_load_empty_file_is_empty(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text("", encoding="utf-8")
    assert state.load_state(p) == {}


def test_load_corrupt_raises(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        state.load_state(p)


def test_load_non_object_raises(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        state.load_state(p)


# --- diff / first-run -------------------------------------------------------------------
def test_first_run_signal_is_empty_state(tmp_path):
    # main.py keys seed mode off `not state`: empty -> first run, non-empty -> not.
    assert not state.load_state(tmp_path / "missing.json")   # empty -> first run
    assert {"a": {}}                                         # non-empty -> not first run


def test_diff_new_returns_only_absent_ids():
    seen = {"greenhouse:acme:1": {"first_seen": "2026-07-01"}}
    jobs = [mkjob("greenhouse:acme:1"), mkjob("greenhouse:acme:2")]
    new = state.diff_new(seen, jobs)
    assert [j.id for j in new] == ["greenhouse:acme:2"]


def test_diff_new_all_new_when_state_empty():
    jobs = [mkjob("a"), mkjob("b")]
    assert state.diff_new({}, jobs) == jobs


# --- record -----------------------------------------------------------------------------
def test_record_adds_entries_with_expected_shape():
    seen: dict = {}
    state.record(seen, [mkjob("a", company="Clay", title="Growth Engineer")], NOW)
    assert seen["a"] == {
        "first_seen": "2026-07-06",
        "last_seen": "2026-07-06",
        "title": "Growth Engineer",
        "company": "Clay",
    }


def test_record_updates_last_seen_but_keeps_first_seen():
    seen = {"a": {"first_seen": "2026-01-01", "last_seen": "2026-01-01",
                  "title": "GTM Engineer", "company": "Acme"}}
    state.record(seen, [mkjob("a")], NOW)
    assert seen["a"]["first_seen"] == "2026-01-01"
    assert seen["a"]["last_seen"] == "2026-07-06"


# --- prune ------------------------------------------------------------------------------
def test_prune_drops_stale_keeps_fresh():
    old = (NOW - timedelta(days=200)).date().isoformat()
    recent = (NOW - timedelta(days=10)).date().isoformat()
    seen = {
        "stale": {"first_seen": old, "last_seen": old, "title": "t", "company": "c"},
        "fresh": {"first_seen": old, "last_seen": recent, "title": "t", "company": "c"},
    }
    removed = state.prune(seen, NOW, days=120)
    assert removed == 1
    assert "stale" not in seen and "fresh" in seen


def test_prune_boundary_keeps_exactly_120_days():
    at_cutoff = (NOW - timedelta(days=120)).date().isoformat()
    seen = {"edge": {"first_seen": at_cutoff, "last_seen": at_cutoff,
                     "title": "t", "company": "c"}}
    assert state.prune(seen, NOW, days=120) == 0
    assert "edge" in seen


def test_prune_falls_back_to_first_seen_when_last_seen_missing():
    old = (NOW - timedelta(days=200)).date().isoformat()
    seen = {"a": {"first_seen": old, "title": "t", "company": "c"}}
    assert state.prune(seen, NOW, days=120) == 1


# --- save/load roundtrip ----------------------------------------------------------------
def test_save_then_load_roundtrips_and_is_stable(tmp_path):
    p = tmp_path / "seen.json"
    seen = {}
    state.record(seen, [mkjob("b"), mkjob("a")], NOW)
    state.save_state(seen, p)
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n")                       # trailing newline
    assert text.index('"a"') < text.index('"b"')     # sort_keys -> stable git diffs
    assert state.load_state(p) == seen
