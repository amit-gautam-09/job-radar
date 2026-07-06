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

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env         # then paste your Telegram token + chat id
python -m src.resolve        # build the watchlist (one-time; already committed)
python -m src.main --dry-run # preview matches without state/notifications
python -m src.main           # live: diff seen.json, seed on first run, notify
pytest -q
```

`.env` is gitignored — secrets never get committed.

## Deploy (GitHub Actions)

The daily run is `.github/workflows/daily.yml` (17:00 IST cron + manual
`workflow_dispatch`). It runs the pipeline and commits `state/seen.json` back to the repo.

1. **Get the two Telegram values** (`PLAN.md §Human Checklist`): message `@BotFather` →
   `/newbot` → copy the token; message your bot once, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy your `chat.id`.
2. **Add them as repo secrets:** repo → **Settings → Secrets and variables → Actions →
   New repository secret** → add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
   (and optionally `ANTHROPIC_API_KEY` for the AI layer).
3. **Test it:** repo → **Actions → daily-radar → Run workflow**. First run seeds the
   baseline and sends one summary; the job then commits `state/seen.json`
   (`radar: state update [skip ci]`). Green run + state commit = it's live.

## Status

Phases 0–3 complete (resolver, fetch/normalize/filter, state diffing + seed mode +
Telegram alerts/digests), 54 tests green. Phase 4 (CI) wired — pending secrets + a first
`workflow_dispatch`. Optional AI scoring layer (`src/ai_score.py`) is Phase 5.
