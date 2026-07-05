# CLAUDE.md — project conventions

**What this is:** `job-radar` — a daily poller of public ATS APIs for ~150 target
companies that alerts on GTM-Engineer-adjacent roles reachable from India. Zero servers;
runs in GitHub Actions. Full spec in `PLAN.md`.

**Ground rules (from `PLAN.md §Ground rules` — these override defaults):**
1. No browser automation / no AI page navigation — deterministic JSON polling only. An
   endpoint that doesn't exist ⇒ mark `unresolved` and move on.
2. Verify ATS field names against live responses before writing/altering parsers.
   Confirmed shapes live 2026-07-05 into `src/fetchers/*` docstrings.
3. Be polite: one run/day, ≤10 concurrent, 15s timeout, 2 retries w/ backoff,
   `User-Agent: job-radar/1.0 (personal job alerts)`.
4. Never commit secrets — tokens live in Actions secrets and local `.env` (gitignored).
5. Every filter rule gets a test (`tests/test_filters.py`).
6. Fail loud — health problems go to Telegram, not silent misses.

**How to run:**
- Resolver (one-time, Phase 1): `python -m src.resolve`
- Pipeline: `python -m src.main` (add `--dry-run` to skip state + notifications)
- Tests: `pytest -q`

**Build phases & status:** see `PLAN.md §Build phases`. Current: Phase 0–1 complete.
