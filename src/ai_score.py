"""Optional Claude Haiku scoring layer — runs only when ANTHROPIC_API_KEY is set.

Phase 5 (PLAN.md §AI layer). The pipeline must be fully functional without it (regex-only
mode). One call per job that passed the title filter and is eligibility UNKNOWN (or needs
a fit score); strict-JSON output; temperature 0.
"""
from __future__ import annotations
