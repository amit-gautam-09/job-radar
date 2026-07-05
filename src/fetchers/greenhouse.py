"""Greenhouse fetcher. Phase 2.

Endpoint (unauth GET):
    https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

Verified live 2026-07-05 (board: robinhood). Top-level: {jobs[], meta}.
Job fields (confirmed present):
    title           -> Job.title
    location.name   -> Job.location_raw
    absolute_url    -> Job.url
    id              -> external id (int)                 e.g. 6669758
    updated_at      -> Job.posted_at (ISO w/ tz)         e.g. 2026-06-24T16:17:10-04:00
    content         -> HTML description (present with content=true) -> strip to text
    first_published -> available; better "posted_at" than updated_at if desired
Garbage slug -> HTTP 404. Empty-but-valid board -> 200 + {"jobs": []}.

NOTE: `content` arrives HTML-entity-escaped (&lt;p&gt;...) — normalize.strip_html
unescapes before stripping tags.
"""
from __future__ import annotations

import requests

from . import FetchError, get_json


def fetch(session: requests.Session, slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = get_json(session, url)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise FetchError(f"unexpected shape from greenhouse/{slug}")
    return jobs
