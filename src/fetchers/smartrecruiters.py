"""SmartRecruiters fetcher. Phase 2.

List endpoint (unauth GET, paginated via `offset`):
    https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=N

Verified live 2026-07-05 (companies: Visa, canva, gong). Top-level:
{offset, limit, totalFound, content[]}. Posting fields (confirmed present):
    content[].name          -> Job.title
    content[].id            -> external id (str)
    content[].releasedDate  -> Job.posted_at (ISO)
    content[].location      -> {city, region, country, remote, hybrid, fullLocation}
NO description in the list payload. Detail endpoint (verified live 2026-07-05):
    /postings/{id} -> {applyUrl, jobAd.sections.{companyDescription,jobDescription,
    qualifications,additionalInformation}.text}
Fetched only for title-tier matches (PLAN.md description policy, Ground Rule 3).

** RESOLVER CAVEAT (confirmed live): a garbage slug returns HTTP 200 + {"totalFound": 0,
"content": []}, NOT a 404. So an empty result does NOT prove the company exists. The
resolver requires totalFound >= 1 to mark a SmartRecruiters company `resolved`. **
"""
from __future__ import annotations

import requests

from . import FetchError, get_json

PAGE = 100


def fetch(session: requests.Session, slug: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        url = (f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
               f"?limit={PAGE}&offset={offset}")
        data = get_json(session, url)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list):
            raise FetchError(f"unexpected shape from smartrecruiters/{slug}")
        out.extend(content)
        total = int(data.get("totalFound", 0))
        offset += len(content)
        if not content or offset >= total:
            return out


def fetch_description(session: requests.Session, slug: str, raw: dict) -> str:
    """Detail-endpoint jobAd text (all sections). Returns "" on failure."""
    pid = raw.get("id")
    if not pid:
        return ""
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}"
    try:
        data = get_json(session, url)
    except FetchError:
        return ""
    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation",
                "companyDescription"):
        sec = sections.get(key) or {}
        if sec.get("text"):
            parts.append(sec["text"])
    return "\n".join(parts)
