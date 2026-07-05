# job-radar

A daily, zero-server job monitor. Every day at **5:00 PM IST**, a GitHub Action polls the
public ATS APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee) of ~150
target companies, filters for **GTM-Engineer-adjacent roles** that are actually reachable
for an India-based candidate — global-remote, India-eligible, or US roles with visa
sponsorship — diffs against previously-seen postings, and pushes only the new matches to
Telegram. No servers, near-zero cost.

Built as a working system *and* as a portfolio piece for GTM-engineering interviews — the
interesting part is the **eligibility classifier**, which separates genuinely reachable
roles from the "Remote (US, must be authorized)" mirage that dominates US job boards.

## How it works

```
fetch (ATS JSON APIs) → normalize → title filter → eligibility classify → diff vs seen → notify
```

1. **Resolve** (one-time): map each target company to its ATS + board slug
   (`src/resolve.py` → `config/companies.yaml`).
2. **Fetch**: one polite GET per resolved board (≤10 concurrent, 15s timeout, retries).
3. **Filter**: title tiers (`config/titles.yaml`) run first; descriptions are only
   fetched/scanned for title matches.
4. **Classify eligibility**: regex-first (India-eligible / global-remote /
   sponsorship-positive / US-remote-only / onsite-no-sponsorship / unknown); an optional
   Claude Haiku layer resolves only the `UNKNOWN` cases when `ANTHROPIC_API_KEY` is set.
5. **Diff & notify**: only postings unseen in `state/seen.json` are alerted; first run
   seeds a baseline and sends a single summary instead of hundreds of pings.

## Tech

Python 3.12, `requests` + `pyyaml` (that's it), `pytest`, GitHub Actions. Fully functional
in **regex-only mode** — the AI layer is optional.

## Setup

See **`PLAN.md §Human Checklist`**: create the repo, add `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` (and optional `ANTHROPIC_API_KEY`) as Actions secrets. Locally, copy
`.env.example` → `.env`.

```bash
pip install -r requirements.txt
python -m src.resolve        # build the watchlist (Phase 1)
python -m src.main --dry-run # preview matches without state/notifications
pytest -q
```

## Status

Phase 0 (scaffold) and Phase 1 (ATS resolver) complete. Fetch/filter/notify phases per
`PLAN.md §Build phases`.
