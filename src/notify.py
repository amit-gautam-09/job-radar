"""Telegram sendMessage + match/seed/digest/health formatting (PLAN.md §Notifications).

Phase 3. Raw HTTPS POST to api.telegram.org/bot{TOKEN}/sendMessage (parse_mode=HTML,
disable_web_page_preview=true) — no telegram library. Split into two layers so the
message shapes are unit-testable without a network:

  format_*  -- pure str builders (HTML-escaped, Telegram 4096-char aware via chunking)
  partition -- new matches -> (instant alerts, digest) per config/policy.yaml
  Notifier  -- the only thing that touches the network; send() takes an injectable
               session so tests can assert on the payload.

Alert policy (PLAN.md §Eligibility / §Notifications): instant ping for tier-1/2 matches
whose eligibility is alert-grade; a single digest message for tier-1/2 digest-grade and
(optionally) tier-3 matches; drop onsite-no-sponsorship. The Sunday-only weekly rollup is
Phase 5 polish — this sends the digest in the same run.
"""
from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
_POLICY_YAML = ROOT / "config" / "policy.yaml"

TELEGRAM_LIMIT = 4096
_CHUNK_SOFT = 3800          # leave headroom for a header line
_TIMEOUT = 15
_RETRIES = 2

# Sort key for stable, most-reachable-first ordering in digests.
ELIGIBILITY_ORDER = [
    "INDIA_ELIGIBLE", "GLOBAL_REMOTE", "SPONSORSHIP_POSITIVE",
    "US_REMOTE_ONLY", "UNKNOWN", "SPONSORSHIP_NEGATIVE_ONSITE",
]


class NotifyError(RuntimeError):
    """Telegram send failed after retries (Ground Rule 6: surfaced, never swallowed)."""


def load_policy(path: Path = _POLICY_YAML) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# --- ordering / partition (pure) --------------------------------------------------------
def _sort_key(job):
    elig = ELIGIBILITY_ORDER.index(job.eligibility) if job.eligibility in ELIGIBILITY_ORDER \
        else len(ELIGIBILITY_ORDER)
    return (job.title_tier, elig, job.company.lower(), job.title.lower())


def partition(jobs, policy: dict) -> tuple[list, list]:
    """Split new matches into (instant alerts, digest) per policy. Drop-grade -> neither.

    - tier 1/2 + alert-grade eligibility  -> instant alert
    - tier 1/2 + digest-grade eligibility -> digest
    - tier 3 (any non-drop eligibility)   -> digest, if include_tier3_in_digest
    """
    alert_set = set(policy.get("alert_eligibilities") or [])
    digest_set = set(policy.get("digest_eligibilities") or [])
    drop_set = set(policy.get("drop_eligibilities") or [])
    include_t3 = policy.get("include_tier3_in_digest", True)

    alerts, digest = [], []
    for j in sorted(jobs, key=_sort_key):
        if j.eligibility in drop_set:
            continue
        if j.title_tier in (1, 2) and j.eligibility in alert_set:
            alerts.append(j)
        elif j.title_tier in (1, 2) and j.eligibility in digest_set:
            digest.append(j)
        elif j.title_tier == 3 and include_t3:
            digest.append(j)
    return alerts, digest


# --- formatting (pure) ------------------------------------------------------------------
def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_match(job) -> str:
    """One posting in the PLAN.md §Notifications shape. All dynamic text HTML-escaped."""
    loc = job.location_raw or (job.workplace if job.workplace != "unknown" else "") \
        or "location n/a"
    lines = [
        f"\U0001F3AF <b>{_esc(job.company)}</b> — {_esc(job.title)}",
        f"\U0001F4CD {_esc(loc)} · {job.eligibility} · Tier {job.title_tier}",
    ]
    if job.score is not None:
        reason = f" — {_esc(job.score_reason)}" if job.score_reason else ""
        lines.append(f"⭐ {job.score}{reason}")
    if job.flags:
        lines.append(f"\U0001F3F7 {_esc(', '.join(job.flags))}")
    lines.append(f"\U0001F517 {_esc(job.url)}")
    return "\n".join(lines)


def format_seed_summary(results, matches, alert_grade) -> str:
    """First-run baseline summary: counts + a digest of current alert-grade tier-1/2 roles."""
    ok = [r for r in results if not r.error]
    failed = [r for r in results if r.error]
    postings = sum(r.scanned for r in ok)
    header = (
        f"\U0001F6F0 <b>job-radar seeded</b>\n"
        f"Baseline set from {len(ok)} companies "
        f"({len(failed)} failed) · {postings} postings scanned.\n"
        f"{len(matches)} title matches · {len(alert_grade)} alert-grade "
        f"(India / global-remote / sponsorship).\n"
        f"No pings fired for existing postings — new matches from now on will alert."
    )
    if not alert_grade:
        return header
    body = "\n\n".join(format_match(j) for j in sorted(alert_grade, key=_sort_key))
    return f"{header}\n\n── current alert-grade roles ──\n\n{body}"


def format_digest(jobs, header: str) -> str:
    body = "\n\n".join(format_match(j) for j in sorted(jobs, key=_sort_key))
    return f"{header}\n\n{body}"


def format_health(details: str) -> str:
    return f"⚠️ <b>job-radar unhealthy</b>\n{_esc(details)}"


def chunk(text: str, limit: int = _CHUNK_SOFT) -> list[str]:
    """Split an over-long message on blank-line boundaries, keeping each piece < limit.

    A single block longer than the hard Telegram limit is truncated (should not happen for
    a normal posting, but never let the API 400 on us)."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for block in text.split("\n\n"):
        if len(block) > TELEGRAM_LIMIT:
            block = block[:TELEGRAM_LIMIT - 1] + "…"
        if cur and len(cur) + 2 + len(block) > limit:
            out.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out


# --- network ----------------------------------------------------------------------------
@dataclass
class Notifier:
    token: str
    chat_id: str
    session: requests.Session | None = None

    @classmethod
    def from_env(cls) -> "Notifier | None":
        """Build from TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID; None if either is unset."""
        token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        if not token or not chat_id:
            return None
        return cls(token, chat_id)

    def _url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send(self, text: str) -> int:
        """Send `text`, splitting if needed. Returns the number of messages delivered."""
        sess = self.session or requests
        sent = 0
        for piece in chunk(text):
            self._post(sess, piece)
            sent += 1
        return sent

    def _post(self, sess, text: str) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        last: Exception | None = None
        for attempt in range(_RETRIES + 1):
            try:
                resp = sess.post(self._url(), data=payload, timeout=_TIMEOUT)
                body = resp.json()
                if resp.status_code == 200 and body.get("ok"):
                    return
                last = NotifyError(
                    f"telegram {resp.status_code}: {body.get('description', body)}")
            except (requests.RequestException, ValueError) as exc:
                last = exc
            if attempt < _RETRIES:
                time.sleep(1.5 * (attempt + 1))
        raise NotifyError(f"sendMessage failed after {_RETRIES + 1} attempts: {last}")


# --- orchestration (network; thin wrappers over the pure builders) ----------------------
def send_seed_summary(notifier: Notifier, results, matches, policy: dict) -> int:
    alert_grade, _ = partition(matches, policy)
    return notifier.send(format_seed_summary(results, matches, alert_grade))


def send_new_matches(notifier: Notifier, new_jobs, policy: dict) -> int:
    """Instant pings for alert-grade (capped), a single digest for the rest. Returns
    messages sent."""
    alerts, digest = partition(new_jobs, policy)
    cap = int(policy.get("max_alerts_per_run", 15))
    overflow = alerts[cap:]
    alerts = alerts[:cap]
    digest = digest + overflow

    sent = 0
    for job in alerts:
        sent += notifier.send(format_match(job))
    if digest:
        header = f"\U0001F4EC <b>job-radar digest</b> — {len(digest)} more role(s)"
        sent += notifier.send(format_digest(digest, header))
    return sent


def send_health(notifier: Notifier, details: str) -> int:
    return notifier.send(format_health(details))
