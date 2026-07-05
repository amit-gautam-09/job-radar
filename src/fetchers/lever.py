"""Lever fetcher. Phase 2.

Endpoint (unauth GET):
    https://api.lever.co/v0/postings/{slug}?mode=json

Verified live 2026-07-05 (board: spotify). Returns a JSON ARRAY of postings.
Job fields (confirmed present):
    text                 -> Job.title
    categories.location  -> Job.location_raw  (also categories.allLocations[], .commitment, .department, .team)
    workplaceType        -> Job.workplace     e.g. "hybrid"  (onsite|hybrid|remote)
    hostedUrl            -> Job.url           (applyUrl also present)
    descriptionPlain     -> Job.description   (also descriptionBodyPlain)
    id                   -> external id
    createdAt            -> epoch MILLISECONDS (int), e.g. 1781109739214  ** convert to ISO **
Garbage slug -> HTTP 404 + {"ok": false, ...}. Empty-but-valid board -> 200 + [].
"""
from __future__ import annotations

import requests

from . import FetchError, get_json


def fetch(session: requests.Session, slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = get_json(session, url)
    if not isinstance(data, list):
        raise FetchError(f"unexpected shape from lever/{slug}")
    return data
