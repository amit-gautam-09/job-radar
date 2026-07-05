"""Workable fetcher. Phase 2.

Endpoint (unauth GET):
    https://apply.workable.com/api/v1/widget/accounts/{slug}

Verified live 2026-07-05 (shape confirmed). Top-level: {name, description, jobs[]}.
Lists jobs + locations; descriptions may need a per-job fetch — only fetch descriptions
for title-tier matches to stay polite (Ground Rule 3 / PLAN.md description policy).
TODO Phase 2: confirm per-job field names on a populated board.
Garbage slug -> HTTP 404. Empty-but-valid board -> 200 + {"jobs": []}.
"""
from __future__ import annotations
