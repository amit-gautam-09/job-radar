"""Ashby fetcher. Phase 2.

Endpoint (unauth GET):
    https://api.ashbyhq.com/posting-api/job-board/{slug}

Verified live 2026-07-05 (boards: openai, ramp, notion, linear). Top-level: {jobs[], apiVersion}.
Job fields (confirmed present):
    id       -> external id (uuid str)
    title    -> Job.title
    department
TODO Phase 2: confirm location / isRemote / jobUrl / publishedAt / descriptionHtml on a
populated board, and whether description ships inline vs. needs the per-job endpoint
(prefer whatever avoids N extra calls).
Garbage slug -> HTTP 404. Empty-but-valid board -> 200 + {"jobs": [], "apiVersion": "1"}.
"""
from __future__ import annotations
