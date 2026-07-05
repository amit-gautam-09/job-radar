"""Per-ATS fetchers. One module per ATS; each returns raw postings for normalize.py.

Field maps in each module were confirmed against LIVE responses on 2026-07-05
(Ground Rule 2).

Contract every module honors:
    fetch(session, slug) -> list[dict]     raw postings; raises FetchError on failure
    fetch_description(session, slug, raw) -> str
        only on modules whose list endpoint omits descriptions (workable,
        smartrecruiters); called AFTER the title filter so we only pay the
        per-job request for tier 1-3 matches (PLAN.md description policy).

Shared HTTP is polite per Ground Rule 3: 15s timeout, 2 retries with exponential
backoff, fixed User-Agent. Concurrency (<=10 workers) is main.py's job.
"""
from __future__ import annotations

import time

import requests

UA = "job-radar/1.0 (personal job alerts)"
TIMEOUT = 15
RETRIES = 2


class FetchError(Exception):
    """An endpoint we resolved in Phase 1 failed to return a valid payload."""


def get_json(session: requests.Session, url: str):
    """GET url -> parsed JSON. Retries transport errors and 5xx with backoff;
    404 / non-200 / non-JSON raise FetchError immediately (fail loud, Ground Rule 6)."""
    last = "unknown error"
    for attempt in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < RETRIES:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break
        if r.status_code >= 500 and attempt < RETRIES:
            last = f"HTTP {r.status_code}"
            time.sleep(0.5 * (2 ** attempt))
            continue
        if r.status_code != 200:
            raise FetchError(f"HTTP {r.status_code} for {url}")
        try:
            return r.json()
        except ValueError:
            raise FetchError(f"non-JSON body for {url}")
    raise FetchError(f"{last} for {url}")


from . import ashby, greenhouse, lever, recruitee, smartrecruiters, workable  # noqa: E402

FETCHERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "recruitee": recruitee,
}
