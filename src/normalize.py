"""ATS payloads -> normalized `Job`. Implemented in Phase 2 (PLAN.md §Data model).

The `Job` dataclass is defined here now because it is a fixed contract the fetchers,
filters, state, and notify layers all depend on. The per-ATS normalization functions
(payload -> Job) land in Phase 2, using the live-verified field maps documented in
`src/fetchers/*`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Job:
    id: str                 # "{ats}:{slug}:{external_id}" — stable across runs
    company: str
    title: str
    location_raw: str       # exactly as the ATS returns it
    workplace: str          # onsite | hybrid | remote | unknown
    url: str                # canonical application URL
    posted_at: str          # ISO date if the ATS provides it, else ""
    description: str         # plain text, truncated ~4000 chars
    source_ats: str
    eligibility: str = ""   # set by filters.py — see PLAN.md §Eligibility
    title_tier: int = 0     # 1/2/3, or 0 = no match
    flags: list[str] = field(default_factory=list)
    score: int | None = None        # AI layer, 0-100, None if AI disabled
    score_reason: str = ""          # one line from AI layer
