"""Workable fetcher. Phase 2.

List endpoint (unauth GET):
    https://apply.workable.com/api/v1/widget/accounts/{slug}

Verified live 2026-07-05 (account: leadfeeder). Top-level: {name, description, jobs[]}.
Job fields (confirmed present):
    title          -> Job.title
    shortcode      -> external id (e.g. "5787A9BF4C")
    city / state / country / locations[]  -> Job.location_raw
    telecommuting  -> bool -> Job.workplace "remote" when true
    url            -> Job.url (https://apply.workable.com/j/{shortcode})
    published_on   -> Job.posted_at (date str)
NO description in the list payload. Per-job endpoint (verified live 2026-07-05;
the v1 widget per-job path 404s):
    https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}
    -> {description, requirements, benefits, ...} (HTML)
Fetched only for title-tier matches (PLAN.md description policy, Ground Rule 3).
Garbage slug -> HTTP 404. Empty-but-valid board -> 200 + {"jobs": []}.
"""
from __future__ import annotations

import requests

from . import FetchError, get_json


def fetch(session: requests.Session, slug: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    data = get_json(session, url)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise FetchError(f"unexpected shape from workable/{slug}")
    return jobs


def fetch_description(session: requests.Session, slug: str, raw: dict) -> str:
    """Per-job HTML description + requirements. Returns "" on failure — a missing
    description degrades eligibility to UNKNOWN rather than killing the run."""
    shortcode = raw.get("shortcode")
    if not shortcode:
        return ""
    url = f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"
    try:
        data = get_json(session, url)
    except FetchError:
        return ""
    parts = [data.get("description") or "", data.get("requirements") or ""]
    return "\n".join(p for p in parts if p)
