"""Title tiers, seniority, and the eligibility classifier (regex).

Implements PLAN.md §Eligibility and the title schema in config/titles.yaml.
Every rule here has a case in tests/test_filters.py (Ground Rule 5).

classify_title(title) -> TitleResult(tier, flags)
    - hard_exclude wins over everything: tier 0 + ["hard_exclude"].
    - tiers are checked 1 -> 2 -> 3 against the title AND comma-rotated variants
      ("Software Engineer, Growth" also tries "Growth Software Engineer" and
      "Growth Engineer"), making the match order-insensitive.
    - soft_downrank adds flags like "senior_downrank" — unless the downranked word
      sits inside the tier match itself ("Technical Growth Lead" is tier2 via a
      pattern that contains "lead", so no lead_downrank).
    - also_match_intern: an intern/graduate/associate title with a tier-2/3 match
      is promoted to tier 1 (early-career is the target profile).

classify_eligibility(location_raw, description, workplace="unknown") -> str
    PLAN.md §Eligibility enum, evaluated in order, first confident match wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_TITLES_YAML = Path(__file__).resolve().parents[1] / "config" / "titles.yaml"


@dataclass
class TitleResult:
    tier: int                       # 1/2/3, or 0 = no match / excluded
    flags: list[str] = field(default_factory=list)


class _TitleConfig:
    def __init__(self, path: Path = _TITLES_YAML):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        compile_all = lambda pats: [re.compile(p, re.I) for p in pats]  # noqa: E731
        self.tiers: list[tuple[int, list[re.Pattern]]] = [
            (n, compile_all(data[f"tier{n}"])) for n in (1, 2, 3)
        ]
        self.hard_exclude = compile_all(data["hard_exclude"])
        self.soft_downrank = compile_all(data["soft_downrank"])
        self.also_match_intern = bool(data.get("also_match_intern"))


_cfg: _TitleConfig | None = None


def _config() -> _TitleConfig:
    global _cfg
    if _cfg is None:
        _cfg = _TitleConfig()
    return _cfg


_INTERN = re.compile(r"\b(intern(ship)?|graduate|associate)\b", re.I)


def _candidates(title: str) -> list[str]:
    """Order-insensitive variants: 'Software Engineer, Growth' also yields
    'Growth Software Engineer' and 'Growth Engineer' (qualifier + head noun)."""
    out = [title]
    if "," in title:
        head, tail = (s.strip() for s in title.split(",", 1))
        if head and tail:
            out.append(f"{tail} {head}")
            head_noun = head.split()[-1]
            if head_noun.lower() != tail.lower():
                out.append(f"{tail} {head_noun}")
    return out


def classify_title(title: str) -> TitleResult:
    cfg = _config()
    if any(p.search(title) for p in cfg.hard_exclude):
        return TitleResult(0, ["hard_exclude"])

    tier = 0
    span: tuple[int, int] | None = None   # match span on the ORIGINAL title, if any
    for tier_n, patterns in cfg.tiers:
        for pat in patterns:
            m = pat.search(title)
            if m:
                tier, span = tier_n, m.span()
                break
            if any(pat.search(c) for c in _candidates(title)[1:]):
                tier, span = tier_n, None
                break
        if tier:
            break
    if tier == 0:
        return TitleResult(0, [])

    flags: list[str] = []
    for pat in cfg.soft_downrank:
        m = pat.search(title)
        if not m:
            continue
        inside_tier_match = span is not None and span[0] <= m.start() and m.end() <= span[1]
        if not inside_tier_match:
            flags.append(f"{m.group(0).strip().lower()}_downrank")

    if cfg.also_match_intern and tier in (2, 3) and _INTERN.search(title):
        tier = 1
        flags.append("intern_match")
    return TitleResult(tier, flags)


# ---------------------------------------------------------------------------------------
# Eligibility (PLAN.md §Eligibility) — regex over location_raw + description.
# Evaluated in order; first confident match wins.
# ---------------------------------------------------------------------------------------
_NEG_SPONSOR = [re.compile(p, re.I) for p in (
    r"unable\s+to\s+(?:provide\s+|offer\s+)?sponsor",
    r"no\s+(?:visa\s+)?sponsorship",
    r"without\s+(?:the\s+need\s+for\s+)?sponsorship",
    r"must\s+be\s+(?:legally\s+)?authorized\s+to\s+work\s+in\s+the\s+(?:US|U\.S\.|United\s+States)",
    r"(?:do(?:es)?\s+not|don'?t|cannot|can'?t|won'?t|will\s+not)\s+(?:currently\s+)?"
    r"(?:offer|provide|sponsor)(?:ing)?(?:\s+(?:visa|work|employment)\w*\s+sponsorship)?",
    r"not\s+(?:able|eligible)\s+to\s+sponsor",
)]
_POS_SPONSOR = [re.compile(p, re.I) for p in (
    r"(?:will|can|do(?:es)?|happy\s+to|able\s+to)\s+(?:provide\s+|offer\s+)?sponsor",
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided|possible)",
)]
_H1B = re.compile(r"h-?1b", re.I)
_NEG_NEARBY = re.compile(r"\b(?:no|not|unable|cannot|can'?t|won'?t|without|don'?t)\b", re.I)

_REMOTE = re.compile(r"\bremote\b|work\s+from\s+anywhere|\bdistributed\s+team\b", re.I)
_INDIA_LOC = re.compile(
    r"\b(?:india|bengaluru|bangalore|new\s+delhi|delhi|gurgaon|gurugram|noida|mumbai|"
    r"pune|hyderabad|chennai)\b", re.I)
_REMOTE_INDIA = re.compile(r"remote\W*(?:in\s+)?(?:india|apac)", re.I)
# In a location string, any global keyword counts. In a description, "global"/
# "worldwide" is usually marketing copy ("our global team") — only count it within
# a clause of a "remote" mention, or the unambiguous "work from anywhere".
_GLOBAL = re.compile(r"\banywhere\b|\bglobal(?:ly)?\b|\bworldwide\b|work\s+from\s+anywhere", re.I)
_GLOBAL_DESC = re.compile(
    r"remote[^.\n]{0,60}(?:\banywhere\b|\bglobal(?:ly)?\b|\bworldwide\b)|"
    r"(?:\banywhere\b|\bglobal(?:ly)?\b|\bworldwide\b)[^.\n]{0,60}remote|"
    r"work\s+from\s+anywhere", re.I)
# A location that doesn't itself restrict anything ("Remote", "", "Fully Remote").
# Only such locations may be upgraded to GLOBAL_REMOTE by description text —
# "Sweden (Remote)" + "we are a remote-first global company" must NOT land there.
_BARE_REMOTE_LOC = re.compile(r"^\W*(?:fully\s+)?remote\W*$", re.I)
_TZ_ONLY = re.compile(r"overlap\s+with\s+(?:ET|PT|CT|MT|EST|PST|CST|MST|UTC|GMT|CET)\b", re.I)
_US_LOC = re.compile(r"\b(?:USA?|U\.S\.A?\.?|United\s+States)\b", re.I)
_US_AUTH = re.compile(
    r"authoriz(?:ed|ation)\s+to\s+work\s+in\s+the\s+(?:US|U\.S\.|United\s+States)|"
    r"(?:US|U\.S\.)\s+work\s+authorization|"
    r"eligib(?:le|ility)\s+to\s+work\s+in\s+the\s+(?:US|U\.S\.|United\s+States)", re.I)


def _h1b_affirmative(text: str) -> bool:
    """H-1B mention counts as sponsorship-positive only when no negation sits nearby
    ("we do not sponsor H-1B" must never land here — PLAN.md)."""
    for m in _H1B.finditer(text):
        window = text[max(0, m.start() - 80):m.end() + 80]
        if not _NEG_NEARBY.search(window):
            return True
    return False


def classify_eligibility(location_raw: str, description: str,
                         workplace: str = "unknown") -> str:
    text = f"{location_raw}\n{description}"
    negated = any(p.search(text) for p in _NEG_SPONSOR)
    remote = workplace == "remote" or bool(_REMOTE.search(text))

    # 1. onsite/hybrid + negated sponsorship -> unreachable, drop-grade
    if not remote and negated:
        return "SPONSORSHIP_NEGATIVE_ONSITE"
    # 2. India cities in the location, or Remote(India|APAC) anywhere
    if _INDIA_LOC.search(location_raw) or _REMOTE_INDIA.search(text):
        return "INDIA_ELIGIBLE"
    # 3. genuinely global remote (timezone-only constraints still count)
    if remote and not _US_LOC.search(location_raw):
        if _GLOBAL.search(location_raw) or _TZ_ONLY.search(location_raw):
            return "GLOBAL_REMOTE"
        loc_unrestricted = not location_raw.strip() or _BARE_REMOTE_LOC.match(location_raw)
        if loc_unrestricted and (_GLOBAL_DESC.search(description)
                                 or _TZ_ONLY.search(description)):
            return "GLOBAL_REMOTE"
    # 4. affirmative sponsorship, never when a negation appears anywhere
    if not negated and (any(p.search(text) for p in _POS_SPONSOR) or _h1b_affirmative(text)):
        return "SPONSORSHIP_POSITIVE"
    # 5. remote but fenced to the US
    if remote and (_US_LOC.search(location_raw) or _US_AUTH.search(text) or negated):
        return "US_REMOTE_ONLY"
    return "UNKNOWN"
