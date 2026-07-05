"""Recruitee fetcher. Phase 2.

Endpoint (unauth GET):
    https://{slug}.recruitee.com/api/offers/

Verified live 2026-07-05 (board: channable). Top-level: {offers[]}.
Offer fields (confirmed present):
    title              -> Job.title
    city / country     -> Job.location_raw
    careers_apply_url  -> Job.url  (careers_url also present)
Garbage slug -> HTTP 404 + {"error": "Not Found"}. Empty-but-valid board -> 200 + {"offers": []}.
"""
from __future__ import annotations
