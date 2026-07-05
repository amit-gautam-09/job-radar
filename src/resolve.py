"""One-time ATS resolver (PLAN.md §Resolver, Phase 1).

Reads company names from data/GTM_Engineer_Companies_2026.md, dedupes them, applies the
skip rules (mega-caps + agencies), generates slug candidates, probes each public ATS in
order, and — for misses — greps the company careers page for an ATS URL. Writes
config/companies.yaml and prints a resolution report.

No browser automation (Ground Rule 1). Polite HTTP (Ground Rule 3): shared User-Agent,
15s timeout, 2 retries w/ exponential backoff, <=10 concurrent workers.

Run: python -m src.resolve
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import sys
import threading
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPANIES_DOC = ROOT / "data" / "GTM_Engineer_Companies_2026.md"
OUT_YAML = ROOT / "config" / "companies.yaml"

UA = "job-radar/1.0 (personal job alerts)"
TIMEOUT = 15
RETRIES = 2
MAX_WORKERS = 10

# Section 4 mega-caps to skip (better covered by LinkedIn/HiringCafe alerts). Matched by
# normalized name so "Amazon Web Services" / "Google Cloud" collapse correctly.
MEGACAP_NAMES = [
    "Salesforce", "Microsoft", "SAP", "ServiceNow", "Oracle", "Adobe",
    "Workday", "IBM", "NVIDIA", "Amazon Web Services", "Google Cloud",
]

ATS_ORDER = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"]

# Careers-page fallback: regex -> (ats, capture slug). Order matters (workday sniff last).
CAREERS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("ashby", re.compile(r"(?:jobs\.ashbyhq\.com|ashbyhq\.com)/([A-Za-z0-9_-]+)")),
    # exclude job-link paths (apply.workable.com/j/<id>) — the account slug is not "j"
    ("workable", re.compile(r"apply\.workable\.com/(?!j/|api/|widget/)([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"https?://([A-Za-z0-9_-]+)\.recruitee\.com")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workday", re.compile(r"([A-Za-z0-9_-]+)\.wd\d+\.myworkdayjobs\.com")),
]


# ---------------------------------------------------------------------------------------
# Step 1 — extract & dedupe company names
# ---------------------------------------------------------------------------------------
def _norm(name: str) -> str:
    """Normalized dedupe/skip key: lowercase, parentheticals dropped, alphanumerics only."""
    name = re.sub(r"\(.*?\)", "", name)
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _clean_display(cell: str) -> str:
    """Human-facing canonical name: strip markdown bold + parentheticals + whitespace."""
    cell = cell.replace("**", "").strip()
    cell = re.sub(r"\s*\(.*?\)\s*$", "", cell).strip()
    return cell


def extract_companies() -> list[dict]:
    """Parse the markdown tables in sections 1-12. Returns deduped list of
    {name, section, status} where status is 'skip' for agencies/mega-caps else ''."""
    megacaps = {_norm(n) for n in MEGACAP_NAMES}
    header_cells = {"company", "agency / firm", "source", "your goal", "role",
                    "current background", "badge", "dimension", "tier", "agency/firm"}

    section: int | None = None
    seen: dict[str, dict] = {}
    order: list[str] = []

    for line in COMPANIES_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\d+)\.\s", line)
        if m:
            section = int(m.group(1))
            continue
        if line.startswith("## "):        # a non-numbered section — stop collecting
            section = None
            continue
        if section is None or section < 1 or section > 12:
            continue
        if not line.lstrip().startswith("|"):
            continue

        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        # skip separator rows (|---|---|) and header rows
        if re.fullmatch(r":?-{2,}:?", first):
            continue
        if first.lower() in header_cells:
            continue
        name = _clean_display(first)
        if not name:
            continue

        key = _norm(name)
        if not key:
            continue
        status = ""
        if section == 9 or key in megacaps:
            status = "skip"
        if key in seen:
            # if any occurrence is skip, keep it skip; otherwise keep first display name
            if status == "skip":
                seen[key]["status"] = "skip"
            continue
        seen[key] = {"name": name, "section": section, "status": status}
        order.append(key)

    return [seen[k] for k in order]


# ---------------------------------------------------------------------------------------
# Step 2 — slug candidates
# ---------------------------------------------------------------------------------------
def slug_candidates(name: str) -> tuple[list[str], list[str]]:
    """Return (candidates, tokens). Candidates ordered most- to least-likely."""
    base = re.sub(r"\(.*?\)", "", name).lower().strip()
    raw_tokens = re.findall(r"[a-z0-9]+", base)                       # incl. tld tokens
    stripped = re.sub(r"\.(io|ai|com|co|xyz|dev|so|app|hq)\b", "", base)
    tokens = re.findall(r"[a-z0-9]+", stripped)

    cands: list[str] = []

    def add(s: str) -> None:
        if s and s not in cands:
            cands.append(s)

    add("".join(tokens))                     # dbtlabs, paloaltonetworks
    add("".join(raw_tokens))                 # apolloio, characterai, snovio
    add("-".join(tokens))                    # dbt-labs, palo-alto-networks
    if len(tokens) > 1 and tokens[-1] in ("ai", "io", "labs", "inc"):
        trimmed = tokens[:-1]
        add("".join(trimmed))                # Scale AI->scale, dbt Labs->dbt
        add("-".join(trimmed))
    # NOTE: no bare first-token for other multi-word names (e.g. "Common Room"->"common"):
    # a generic slug risks matching an unrelated board. Under-resolve, don't mis-resolve.
    return cands, tokens


def _sr_variants(cand: str, tokens: list[str]) -> list[str]:
    """SmartRecruiters slugs are often PascalCase (e.g. 'Visa'). Add cased variants."""
    out = [cand, cand.capitalize()]
    if tokens:
        out.append("".join(t.capitalize() for t in tokens))
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ---------------------------------------------------------------------------------------
# Step 3 — probe an ATS endpoint. Returns posting count if valid, else None.
# ---------------------------------------------------------------------------------------
def _endpoint(ats: str, slug: str) -> str:
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=10",
        "recruitee": f"https://{slug}.recruitee.com/api/offers/",
    }[ats]


def _valid_shape(ats: str, data) -> int | None:
    """Validate the top-level shape. Returns posting count if the board is genuinely valid,
    else None. Rules confirmed against live garbage-slug tests (2026-07-05)."""
    try:
        if ats == "greenhouse":
            return len(data["jobs"]) if isinstance(data.get("jobs"), list) else None
        if ats == "lever":
            return len(data) if isinstance(data, list) else None
        if ats == "ashby":
            return len(data["jobs"]) if isinstance(data.get("jobs"), list) else None
        if ats == "workable":
            return len(data["jobs"]) if isinstance(data.get("jobs"), list) else None
        if ats == "smartrecruiters":
            # garbage slug returns 200 + totalFound:0 -> require >=1 posting to trust it
            if isinstance(data.get("content"), list) and int(data.get("totalFound", 0)) >= 1:
                return int(data["totalFound"])
            return None
        if ats == "recruitee":
            return len(data["offers"]) if isinstance(data.get("offers"), list) else None
    except (KeyError, TypeError, ValueError):
        return None
    return None


def probe(session: requests.Session, ats: str, slug: str) -> int | None:
    url = _endpoint(ats, slug)
    for attempt in range(RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        except requests.RequestException:
            if attempt < RETRIES:
                threading.Event().wait(0.5 * (2 ** attempt))
                continue
            return None
        if r.status_code == 404:
            return None                       # definitive miss — no retry
        if r.status_code >= 500 and attempt < RETRIES:
            threading.Event().wait(0.5 * (2 ** attempt))
            continue
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        return _valid_shape(ats, data)
    return None


# ---------------------------------------------------------------------------------------
# Step 4 — careers-page fallback (no browser; grep HTML for ATS URLs)
# ---------------------------------------------------------------------------------------
DOMAIN_OVERRIDES = {
    "notion": "notion.so", "monday.com": "monday.com", "dbtlabs": "getdbt.com",
    "supabase": "supabase.com", "linear": "linear.app", "retool": "retool.com",
    "railway": "railway.app", "fly.io": "fly.io", "loom": "loom.com",
}


def careers_fallback(session: requests.Session, name: str, tokens: list[str]):
    """Return (ats, slug) or ('workday', None) or None."""
    concat = "".join(tokens)
    domains = []
    if concat in DOMAIN_OVERRIDES:
        domains.append(DOMAIN_OVERRIDES[concat])
    domains += [f"{concat}.com", f"{concat}.io", f"{concat}.ai"]
    for domain in dict.fromkeys(domains):
        for path in ("/careers", "/jobs"):
            try:
                r = session.get(f"https://{domain}{path}", timeout=8,
                                headers={"User-Agent": UA}, allow_redirects=True)
            except requests.RequestException:
                continue
            if r.status_code != 200 or not r.text:
                continue
            for ats, pat in CAREERS_PATTERNS:
                mm = pat.search(r.text)
                if mm:
                    return (ats, None) if ats == "workday" else (ats, mm.group(1))
    return None


# ---------------------------------------------------------------------------------------
# Resolve one company
# ---------------------------------------------------------------------------------------
def resolve_one(company: dict) -> dict:
    name = company["name"]
    result = {"name": name, "ats": None, "slug": None, "status": "unresolved"}
    with requests.Session() as session:
        candidates, tokens = slug_candidates(name)
        for cand in candidates:
            for ats in ATS_ORDER:
                slugs = _sr_variants(cand, tokens) if ats == "smartrecruiters" else [cand]
                for slug in slugs:
                    count = probe(session, ats, slug)
                    if count is not None:
                        result.update(ats=ats, slug=slug, status="resolved",
                                      _count=count)
                        return result
        # misses -> careers-page grep
        fb = careers_fallback(session, name, tokens)
        if fb:
            ats, slug = fb
            if ats == "workday":
                result.update(status="workday")
            else:
                result.update(ats=ats, slug=slug, status="resolved", _count=-1)
    return result


# ---------------------------------------------------------------------------------------
# Step 5 — orchestrate + write + report
# ---------------------------------------------------------------------------------------
STATUS_RANK = {"resolved": 0, "workday": 1, "unresolved": 2, "skip": 3}

YAML_HEADER = (
    "# The watchlist. GENERATED by `python -m src.resolve` (PLAN.md §Resolver), then\n"
    "# hand-edited. status: resolved | unresolved | workday | skip.\n"
    "#   skip  = intentionally excluded (mega-caps -> LinkedIn alerts; agencies rarely run\n"
    "#           an ATS). Flip to resolved + fill ats/slug to enable.\n"
    "#   workday = on Workday (fetcher is Phase 5); skipped in v1.\n\n"
)


def write_yaml(entries: list[dict]) -> None:
    ordered = sorted(entries, key=lambda e: (STATUS_RANK.get(e["status"], 9),
                                             e.get("ats") or "", e["name"].lower()))
    clean = [{"name": e["name"], "ats": e.get("ats"), "slug": e.get("slug"),
              "status": e["status"]} for e in ordered]
    OUT_YAML.write_text(
        YAML_HEADER + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def report(companies: list[dict], resolved: list[dict]) -> None:
    skipped = [c for c in companies if c["status"] == "skip"]
    probed = [r for r in resolved]
    by_status: dict[str, list[dict]] = {}
    for r in probed:
        by_status.setdefault(r["status"], []).append(r)

    res = by_status.get("resolved", [])
    per_ats: dict[str, int] = {}
    for r in res:
        per_ats[r["ats"]] = per_ats.get(r["ats"], 0) + 1

    print("\n" + "=" * 70)
    print("  job-radar — RESOLUTION REPORT")
    print("=" * 70)
    print(f"  Companies in doc (deduped) : {len(companies) + 0}")
    print(f"  Skipped (mega-cap/agency)  : {len(skipped)}")
    print(f"  Probed (non-skip)          : {len(probed)}")
    print("-" * 70)
    print(f"  RESOLVED                   : {len(res)}")
    for ats in ATS_ORDER:
        if per_ats.get(ats):
            names = sorted(r["name"] for r in res if r["ats"] == ats)
            print(f"    {ats:16} {per_ats[ats]:>3}  | {', '.join(names)}")
    wd = by_status.get("workday", [])
    unres = by_status.get("unresolved", [])
    print("-" * 70)
    print(f"  WORKDAY ({len(wd)}): {', '.join(sorted(w['name'] for w in wd)) or '-'}")
    print("-" * 70)
    print(f"  UNRESOLVED ({len(unres)}): {', '.join(sorted(u['name'] for u in unres)) or '-'}")
    print("=" * 70)
    rate = (len(res) / len(probed) * 100) if probed else 0
    print(f"  Resolution rate (of non-skip): {rate:.0f}%   "
          f"[Phase 1 acceptance: >=60 resolved -> {'PASS' if len(res) >= 60 else 'CHECK'}]")
    print("=" * 70 + "\n")


def main() -> int:
    companies = extract_companies()
    to_probe = [c for c in companies if c["status"] != "skip"]
    print(f"Extracted {len(companies)} companies "
          f"({len(companies) - len(to_probe)} skip, {len(to_probe)} to probe). Probing...",
          file=sys.stderr)

    resolved: list[dict] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(resolve_one, c): c for c in to_probe}
        for fut in cf.as_completed(futures):
            r = fut.result()
            resolved.append(r)
            done += 1
            tag = r["status"] if r["status"] != "resolved" else f"{r['ats']}/{r['slug']}"
            print(f"  [{done:>3}/{len(to_probe)}] {r['name']:<28} -> {tag}", file=sys.stderr)

    all_entries = resolved + [c for c in companies if c["status"] == "skip"]
    write_yaml(all_entries)
    report(companies, resolved)
    print(f"Wrote {OUT_YAML.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
