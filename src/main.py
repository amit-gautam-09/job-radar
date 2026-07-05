"""Orchestrator: fetch -> normalize -> filter -> diff -> notify.

Phase 2+ (per PLAN.md §Build phases). Not yet implemented — Phase 0/1 ship the scaffold
and the one-time resolver (`python -m src.resolve`) only.
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="job-radar")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch + filter and print matches without touching state or sending notifications",
    )
    parser.parse_args()
    raise NotImplementedError(
        "Pipeline lands in Phase 2. For now run the resolver: python -m src.resolve"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
