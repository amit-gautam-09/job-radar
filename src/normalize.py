"""ATS payloads -> normalized `Job` (PLAN.md §Data model).

Per-ATS field maps below mirror the live-verified shapes documented in each
`src/fetchers/*` docstring (Ground Rule 2, verified 2026-07-05). Normalizers are
defensive: a malformed posting yields None (skipped) rather than a crash, but a
whole-payload shape problem is the fetcher's job to raise.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

DESC_LIMIT = 4000


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


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    """Entity-escaped or plain HTML -> readable text, truncated to DESC_LIMIT.
    Greenhouse double-escapes (&lt;p&gt;), so unescape before stripping tags."""
    if not raw:
        return ""
    text = html.unescape(raw)
    if "<" in text:
        text = re.sub(r"<(?:br|/p|/div|/li|/h[1-6])[^>]*>", "\n", text, flags=re.I)
        text = _TAG.sub(" ", text)
        text = html.unescape(text)  # entities that surfaced after tag removal
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", "\n".join(line.strip() for line in text.split("\n")))
    return text.strip()[:DESC_LIMIT]


def _plain(text: str | None) -> str:
    return (text or "").strip()[:DESC_LIMIT]


def _epoch_ms_to_iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _workplace(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in ("onsite", "hybrid", "remote") else "unknown"


# ---------------------------------------------------------------------------------------
# Per-ATS normalizers: raw dict -> Job | None
# ---------------------------------------------------------------------------------------
def _greenhouse(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("id")
    title = raw.get("title")
    if ext is None or not title:
        return None
    return Job(
        id=f"greenhouse:{slug}:{ext}",
        company=company,
        title=title,
        location_raw=(raw.get("location") or {}).get("name") or "",
        workplace="unknown",  # greenhouse has no workplace field; location carries it
        url=raw.get("absolute_url") or "",
        posted_at=raw.get("first_published") or raw.get("updated_at") or "",
        description=strip_html(raw.get("content")),
        source_ats="greenhouse",
    )


def _lever(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("id")
    title = raw.get("text")
    if ext is None or not title:
        return None
    cats = raw.get("categories") or {}
    location = cats.get("location") or ", ".join(cats.get("allLocations") or []) or ""
    return Job(
        id=f"lever:{slug}:{ext}",
        company=company,
        title=title,
        location_raw=location,
        workplace=_workplace(raw.get("workplaceType")),
        url=raw.get("hostedUrl") or "",
        posted_at=_epoch_ms_to_iso(raw.get("createdAt")),  # epoch MILLISECONDS
        description=_plain(raw.get("descriptionPlain") or raw.get("descriptionBodyPlain")),
        source_ats="lever",
    )


def _ashby(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("id")
    title = raw.get("title")
    if ext is None or not title:
        return None
    locations = [raw.get("location") or ""]
    locations += [s.get("location") or "" for s in raw.get("secondaryLocations") or []]
    workplace = _workplace(raw.get("workplaceType"))
    if workplace == "unknown" and raw.get("isRemote"):
        workplace = "remote"
    return Job(
        id=f"ashby:{slug}:{ext}",
        company=company,
        title=title,
        location_raw="; ".join(loc for loc in locations if loc),
        workplace=workplace,
        url=raw.get("jobUrl") or raw.get("applyUrl") or "",
        posted_at=raw.get("publishedAt") or "",
        description=_plain(raw.get("descriptionPlain")) or strip_html(raw.get("descriptionHtml")),
        source_ats="ashby",
    )


def _workable(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("shortcode")
    title = raw.get("title")
    if not ext or not title:
        return None
    parts = [raw.get("city"), raw.get("state"), raw.get("country")]
    location = ", ".join(p for p in parts if p)
    if not location:
        locs = raw.get("locations") or []
        location = "; ".join(
            ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
            for loc in locs if isinstance(loc, dict)
        )
    return Job(
        id=f"workable:{slug}:{ext}",
        company=company,
        title=title,
        location_raw=location,
        workplace="remote" if raw.get("telecommuting") else "unknown",
        url=raw.get("url") or f"https://apply.workable.com/j/{ext}",
        posted_at=raw.get("published_on") or raw.get("created_at") or "",
        description="",  # deferred: fetchers.workable.fetch_description for title matches
        source_ats="workable",
    )


def _smartrecruiters(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("id")
    title = raw.get("name")
    if ext is None or not title:
        return None
    loc = raw.get("location") or {}
    location = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
    )
    workplace = "unknown"
    if loc.get("remote"):
        workplace = "remote"
    elif loc.get("hybrid"):
        workplace = "hybrid"
    company_id = (raw.get("company") or {}).get("identifier") or slug
    return Job(
        id=f"smartrecruiters:{slug}:{ext}",
        company=company,
        title=title,
        location_raw=location,
        workplace=workplace,
        url=f"https://jobs.smartrecruiters.com/{company_id}/{ext}",
        posted_at=raw.get("releasedDate") or "",
        description="",  # deferred: fetchers.smartrecruiters.fetch_description for matches
        source_ats="smartrecruiters",
    )


def _recruitee(company: str, slug: str, raw: dict) -> Job | None:
    ext = raw.get("id")
    title = raw.get("title")
    if ext is None or not title:
        return None
    location = raw.get("location") or ", ".join(
        p for p in (raw.get("city"), raw.get("country")) if p
    )
    workplace = "unknown"
    if raw.get("remote"):
        workplace = "remote"
    elif raw.get("hybrid"):
        workplace = "hybrid"
    elif raw.get("on_site"):
        workplace = "onsite"
    return Job(
        id=f"recruitee:{slug}:{ext}",
        company=company,
        title=title,
        location_raw=location,
        workplace=workplace,
        url=raw.get("careers_apply_url") or raw.get("careers_url") or "",
        posted_at=raw.get("published_at") or raw.get("created_at") or "",
        description=strip_html(raw.get("description")),
        source_ats="recruitee",
    )


_NORMALIZERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
    "recruitee": _recruitee,
}


def normalize(ats: str, company: str, slug: str, raw: dict) -> Job | None:
    """Dispatch one raw posting to its ATS normalizer. None = skip this posting."""
    fn = _NORMALIZERS.get(ats)
    if fn is None:
        raise ValueError(f"no normalizer for ATS {ats!r}")
    try:
        return fn(company, slug, raw)
    except (AttributeError, TypeError):
        return None
