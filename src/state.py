"""seen.json load / diff / save / prune (PLAN.md §State & diffing).

Phase 3. state/seen.json maps job_id -> {first_seen, title, company}. New job = id absent.
Prune entries not seen in 120 days. First-run seed mode sends one summary, not N pings.
"""
from __future__ import annotations
