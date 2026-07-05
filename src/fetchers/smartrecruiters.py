"""SmartRecruiters fetcher. Phase 2.

Endpoint (unauth GET, paginated via `offset`):
    https://api.smartrecruiters.com/v1/companies/{slug}/postings

Verified live 2026-07-05 (company: Visa). Top-level: {offset, limit, totalFound, content[]}.
Posting fields (confirmed present):
    content[].name  -> Job.title
    content[].id    -> external id
Descriptions via /postings/{id} — fetch only for title matches (polite).

** RESOLVER CAVEAT (confirmed live): a garbage slug returns HTTP 200 + {"totalFound": 0,
"content": []}, NOT a 404. So an empty result does NOT prove the company exists. The
resolver requires totalFound >= 1 to mark a SmartRecruiters company `resolved`. **
"""
from __future__ import annotations
