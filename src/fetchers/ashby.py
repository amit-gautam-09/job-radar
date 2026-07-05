"""Ashby fetcher. Phase 2.

Endpoint (unauth GET):
    https://api.ashbyhq.com/posting-api/job-board/{slug}

Verified live 2026-07-05 (boards: openai, ramp, notion, linear; full field set
re-verified on cognition, 75 jobs). Top-level: {jobs[], apiVersion}.
Job fields (confirmed present):
    id                 -> external id (uuid str)
    title              -> Job.title
    location           -> Job.location_raw (str; also secondaryLocations[].location)
    workplaceType      -> Job.workplace ("Onsite"|"Hybrid"|"Remote"); isRemote bool too
    jobUrl             -> Job.url (applyUrl also present)
    publishedAt        -> Job.posted_at (ISO w/ tz)
    descriptionPlain   -> Job.description  ** ships INLINE — no per-job call needed **
    descriptionHtml    -> also inline
    isListed           -> bool; unlisted postings are filtered out here
Garbage slug -> HTTP 404. Empty-but-valid board -> 200 + {"jobs": [], "apiVersion": "1"}.
"""
from __future__ import annotations

import requests

from . import FetchError, get_json


def fetch(session: requests.Session, slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = get_json(session, url)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise FetchError(f"unexpected shape from ashby/{slug}")
    return [j for j in jobs if j.get("isListed", True)]
