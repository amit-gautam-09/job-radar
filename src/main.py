"""Orchestrator: fetch -> normalize -> filter -> diff -> notify.

Phase 2 ships fetch -> normalize -> filter and `--dry-run` (print matches, touch
nothing). State diffing + Telegram land in Phase 3; running without --dry-run
says so and exits rather than pretending.

Politeness (Ground Rule 3): <=10 workers total, one requests.Session per company,
descriptions fetched per-job only for title-tier matches on the two ATSes that
need it (workable, smartrecruiters).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from . import filters
from .fetchers import FETCHERS, FetchError
from .normalize import Job, normalize

ROOT = Path(__file__).resolve().parents[1]
MAX_WORKERS = 10

ELIGIBILITY_ORDER = [
    "INDIA_ELIGIBLE", "GLOBAL_REMOTE", "SPONSORSHIP_POSITIVE",
    "US_REMOTE_ONLY", "UNKNOWN", "SPONSORSHIP_NEGATIVE_ONSITE",
]


@dataclass
class CompanyResult:
    name: str
    ats: str
    slug: str
    scanned: int = 0                        # postings seen before any filtering
    matches: list[Job] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0


def load_watchlist() -> list[dict]:
    data = yaml.safe_load((ROOT / "config" / "companies.yaml").read_text(encoding="utf-8"))
    return [c for c in data or [] if c.get("status") == "resolved"]


def fetch_company(company: dict) -> CompanyResult:
    name, ats, slug = company["name"], company["ats"], company["slug"]
    res = CompanyResult(name=name, ats=ats, slug=slug)
    module = FETCHERS[ats]
    t0 = time.monotonic()
    try:
        with requests.Session() as session:
            raws = module.fetch(session, slug)
            res.scanned = len(raws)
            for raw in raws:
                job = normalize(ats, name, slug, raw)
                if job is None:
                    continue
                tr = filters.classify_title(job.title)
                if tr.tier == 0:
                    continue
                job.title_tier, job.flags = tr.tier, tr.flags
                if not job.description and hasattr(module, "fetch_description"):
                    job.description = module.fetch_description(session, slug, raw)
                job.eligibility = filters.classify_eligibility(
                    job.location_raw, job.description, job.workplace)
                res.matches.append(job)
    except FetchError as exc:
        res.error = str(exc)
    res.elapsed = time.monotonic() - t0
    return res


def run_pipeline() -> list[CompanyResult]:
    watchlist = load_watchlist()
    print(f"job-radar: fetching {len(watchlist)} resolved companies "
          f"(<= {MAX_WORKERS} concurrent)...", file=sys.stderr)
    results: list[CompanyResult] = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_company, c): c for c in watchlist}
        done = 0
        for fut in cf.as_completed(futures):
            r = fut.result()
            results.append(r)
            done += 1
            tag = f"FAIL: {r.error}" if r.error else \
                f"{r.scanned} postings, {len(r.matches)} matches"
            print(f"  [{done:>3}/{len(watchlist)}] {r.name:<28} {tag}", file=sys.stderr)
    return results


def print_dry_run(results: list[CompanyResult]) -> None:
    ok = [r for r in results if not r.error]
    failed = sorted((r for r in results if r.error), key=lambda r: r.name)
    matches = [j for r in ok for j in r.matches]
    matches.sort(key=lambda j: (j.title_tier, ELIGIBILITY_ORDER.index(j.eligibility),
                                j.company.lower()))

    print("\n" + "=" * 78)
    print("  job-radar DRY RUN -- no state written, nothing sent")
    print("=" * 78)
    print(f"  Companies fetched : {len(ok)} ok, {len(failed)} failed")
    print(f"  Postings scanned  : {sum(r.scanned for r in ok)}")
    print(f"  Title-tier matches: {len(matches)}")

    by_elig: dict[str, int] = {}
    for j in matches:
        by_elig[j.eligibility] = by_elig.get(j.eligibility, 0) + 1
    if by_elig:
        breakdown = ", ".join(f"{k}={by_elig[k]}" for k in ELIGIBILITY_ORDER if k in by_elig)
        print(f"  By eligibility    : {breakdown}")

    alert_grade = [j for j in matches
                   if j.eligibility in ("INDIA_ELIGIBLE", "GLOBAL_REMOTE",
                                        "SPONSORSHIP_POSITIVE")]
    print(f"  Alert-grade (would ping Telegram): {len(alert_grade)}")
    print("-" * 78)
    for j in matches:
        flags = f"  [{', '.join(j.flags)}]" if j.flags else ""
        print(f"  T{j.title_tier} {j.eligibility:<27} {j.company} -- {j.title}{flags}")
        loc = j.location_raw or "(no location)"
        print(f"     {loc}  |  {j.workplace}")
        print(f"     {j.url}")
    if failed:
        print("-" * 78)
        print("  FAILED ENDPOINTS (fail loud, Ground Rule 6):")
        for r in failed:
            print(f"    {r.name} ({r.ats}/{r.slug}): {r.error}")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(prog="job-radar")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch + filter and print matches without touching state or sending notifications",
    )
    args = parser.parse_args()
    if not args.dry_run:
        print("state + notifications land in Phase 3 -- run with --dry-run for now",
              file=sys.stderr)
        return 2

    t0 = time.monotonic()
    results = run_pipeline()
    print_dry_run(results)
    print(f"  Total wall time: {time.monotonic() - t0:.1f}s "
          f"(Phase 2 acceptance: < 300s)")
    failed_frac = sum(1 for r in results if r.error) / max(len(results), 1)
    return 1 if failed_frac > 0.2 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
