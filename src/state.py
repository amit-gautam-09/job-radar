"""seen.json load / diff / record / prune / save (PLAN.md §State & diffing).

Phase 3. `state/seen.json` maps job_id -> {first_seen, last_seen, title, company}.
A new job is one whose id is absent from state. Every run refreshes `last_seen`
for the matches it re-sees, so entries not seen in any fetch for `PRUNE_DAYS` can be
pruned (the schema in PLAN.md is illustrative; `last_seen` is the field pruning needs).

State tracks only title-tier matches, not every posting scanned — that keeps the file
small and is all the diff (new vs already-alerted) requires. First-run seed mode is a
main.py concern: it keys off `not state` so the baseline is recorded without firing a
ping per existing posting.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state" / "seen.json"
PRUNE_DAYS = 120


def load_state(path: Path = STATE_PATH) -> dict[str, dict]:
    """Return the seen map, or {} if the file is missing or empty.

    A corrupt seen.json raises (Ground Rule 6: fail loud) rather than silently
    re-seeding and spamming a full digest — the caller turns that into a health alert.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)  # JSONDecodeError propagates — fail loud
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object (got {type(data).__name__})")
    return data


def diff_new(state: dict[str, dict], jobs: Iterable) -> list:
    """Jobs whose id is absent from state (i.e. never seen / never alerted)."""
    return [j for j in jobs if j.id not in state]


def record(state: dict[str, dict], jobs: Iterable, now: datetime | None = None) -> None:
    """Add unseen jobs and refresh `last_seen` on jobs already present. Mutates state."""
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    for j in jobs:
        entry = state.get(j.id)
        if entry is None:
            state[j.id] = {
                "first_seen": today,
                "last_seen": today,
                "title": j.title,
                "company": j.company,
            }
        else:
            entry["last_seen"] = today


def prune(state: dict[str, dict], now: datetime | None = None,
          days: int = PRUNE_DAYS) -> int:
    """Drop entries not seen for `days`. Returns the number removed. Mutates state."""
    cutoff = (now or datetime.now(timezone.utc)).date() - timedelta(days=days)
    stale = [jid for jid, e in state.items() if _last_seen(e) < cutoff]
    for jid in stale:
        del state[jid]
    return len(stale)


def save_state(state: dict[str, dict], path: Path = STATE_PATH) -> None:
    """Atomically write state as stable, sorted JSON (clean git diffs for the Action)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem, incl. Windows


# --- internals --------------------------------------------------------------------------
def _last_seen(entry: dict) -> date:
    """`last_seen`, falling back to `first_seen`; unparseable -> today (keep, don't lose)."""
    raw = entry.get("last_seen") or entry.get("first_seen") or ""
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date()
