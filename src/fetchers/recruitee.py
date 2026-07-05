"""Recruitee fetcher. Phase 2.

Endpoint (unauth GET):
    https://{slug}.recruitee.com/api/offers/

Verified live 2026-07-05 (board: channable; full field set re-verified same day).
Top-level: {offers[]}. Offer fields (confirmed present):
    id                 -> external id (int)
    title              -> Job.title
    location           -> Job.location_raw ("Utrecht, Utrecht, Netherlands");
                          city / country also present separately
    remote / hybrid / on_site  -> bools -> Job.workplace
    careers_apply_url  -> Job.url (careers_url also present)
    description        -> HTML, ships INLINE (requirements also present, HTML)
    published_at / created_at  -> Job.posted_at
Garbage slug -> HTTP 404 + {"error": "Not Found"}. Empty-but-valid board -> 200 + {"offers": []}.
"""
from __future__ import annotations

import requests

from . import FetchError, get_json


def fetch(session: requests.Session, slug: str) -> list[dict]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    data = get_json(session, url)
    offers = data.get("offers") if isinstance(data, dict) else None
    if not isinstance(offers, list):
        raise FetchError(f"unexpected shape from recruitee/{slug}")
    return offers
