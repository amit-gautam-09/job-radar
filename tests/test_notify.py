"""Notification tests (PLAN.md §Notifications). Ground Rule 5.

Covers the alert/digest/drop partition, HTML-safe formatting, chunking, the max-alerts
overflow, env-based construction, and the Telegram POST payload + retry (no real network).
"""
from __future__ import annotations

import pytest

from src import notify
from src.normalize import Job

POLICY = {
    "alert_eligibilities": ["INDIA_ELIGIBLE", "GLOBAL_REMOTE", "SPONSORSHIP_POSITIVE"],
    "digest_eligibilities": ["US_REMOTE_ONLY", "UNKNOWN"],
    "drop_eligibilities": ["SPONSORSHIP_NEGATIVE_ONSITE"],
    "include_tier3_in_digest": True,
    "max_alerts_per_run": 15,
}


def mkjob(jid="a", company="Acme", title="GTM Engineer", tier=1,
          elig="GLOBAL_REMOTE", location="Remote (Global)", score=None,
          score_reason="", flags=None) -> Job:
    return Job(id=jid, company=company, title=title, location_raw=location,
               workplace="remote", url=f"https://jobs/{jid}", posted_at="",
               description="", source_ats="ashby", eligibility=elig,
               title_tier=tier, flags=flags or [], score=score, score_reason=score_reason)


# --- formatting -------------------------------------------------------------------------
def test_format_match_has_all_lines():
    text = notify.format_match(mkjob(company="Clay", title="GTM Engineer",
                                     location="Remote (Global)", elig="GLOBAL_REMOTE"))
    assert "<b>Clay</b>" in text
    assert "GTM Engineer" in text
    assert "GLOBAL_REMOTE" in text and "Tier 1" in text
    assert "https://jobs/a" in text
    assert "⭐" not in text                        # no score line when score is None


def test_format_match_escapes_html():
    text = notify.format_match(mkjob(company="A & B <Inc>", title="C/D & E"))
    assert "&amp;" in text and "&lt;Inc&gt;" in text
    assert "<Inc>" not in text                     # raw angle brackets must not leak


def test_format_match_includes_score_line_when_scored():
    text = notify.format_match(mkjob(score=82, score_reason="IST overlap OK"))
    assert "⭐ 82" in text and "IST overlap OK" in text


def test_format_match_falls_back_when_location_blank():
    text = notify.format_match(mkjob(location="", ))
    assert "location n/a" in text or "remote" in text.lower()


# --- partition --------------------------------------------------------------------------
def test_partition_routes_by_tier_and_eligibility():
    jobs = [
        mkjob("alert", tier=1, elig="INDIA_ELIGIBLE"),
        mkjob("digest_elig", tier=2, elig="US_REMOTE_ONLY"),
        mkjob("tier3", tier=3, elig="GLOBAL_REMOTE"),          # tier3 -> digest, not alert
        mkjob("dropped", tier=1, elig="SPONSORSHIP_NEGATIVE_ONSITE"),
    ]
    alerts, digest = notify.partition(jobs, POLICY)
    assert {j.id for j in alerts} == {"alert"}
    assert {j.id for j in digest} == {"digest_elig", "tier3"}


def test_partition_excludes_tier3_when_disabled():
    policy = {**POLICY, "include_tier3_in_digest": False}
    alerts, digest = notify.partition([mkjob("t3", tier=3, elig="GLOBAL_REMOTE")], policy)
    assert not alerts and not digest


def test_partition_orders_most_reachable_first():
    jobs = [mkjob("u", tier=1, elig="SPONSORSHIP_POSITIVE"),
            mkjob("i", tier=1, elig="INDIA_ELIGIBLE")]
    alerts, _ = notify.partition(jobs, POLICY)
    assert [j.id for j in alerts] == ["i", "u"]     # INDIA before SPONSORSHIP_POSITIVE


# --- send_new_matches: capping + message counts -----------------------------------------
class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> int:
        self.sent.append(text)
        return 1


def test_send_new_matches_one_alert_one_message():
    fake = FakeNotifier()
    sent = notify.send_new_matches(fake, [mkjob("a", tier=1, elig="INDIA_ELIGIBLE")], POLICY)
    assert sent == 1 and len(fake.sent) == 1
    assert "<b>Acme</b>" in fake.sent[0]


def test_send_new_matches_nothing_when_no_new():
    fake = FakeNotifier()
    assert notify.send_new_matches(fake, [], POLICY) == 0
    assert fake.sent == []


def test_send_new_matches_caps_alerts_and_overflows_to_digest():
    policy = {**POLICY, "max_alerts_per_run": 2}
    jobs = [mkjob(f"j{i}", company=f"Co{i}", tier=1, elig="GLOBAL_REMOTE") for i in range(5)]
    fake = FakeNotifier()
    sent = notify.send_new_matches(fake, jobs, policy)
    assert sent == 3                                # 2 individual + 1 overflow digest
    assert "job-radar digest" in fake.sent[-1]
    assert "3 more" in fake.sent[-1]                # 5 - 2 = 3 in the digest


# --- chunking ---------------------------------------------------------------------------
def test_chunk_short_text_is_one_piece():
    assert notify.chunk("hello") == ["hello"]


def test_chunk_splits_on_blank_lines_under_limit():
    blocks = "\n\n".join("X" * 1000 for _ in range(6))   # 6 KB across 6 blocks
    pieces = notify.chunk(blocks, limit=3800)
    assert len(pieces) > 1
    assert all(len(p) <= 3800 for p in pieces)


# --- Notifier.from_env ------------------------------------------------------------------
def test_from_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.Notifier.from_env() is None


def test_from_env_builds_when_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    n = notify.Notifier.from_env()
    assert n is not None and n.token == "T" and n.chat_id == "42"


# --- Notifier.send: payload + retry (fake session, no network) --------------------------
class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, data, timeout):
        self.calls.append({"url": url, "data": data, "timeout": timeout})
        return self.responses.pop(0)


def test_send_posts_expected_payload():
    sess = FakeSession([FakeResp(200, {"ok": True})])
    n = notify.Notifier("TOK", "42", session=sess)
    assert n.send("hi <b>there</b>") == 1
    call = sess.calls[0]
    assert call["url"].endswith("/botTOK/sendMessage")
    assert call["data"]["chat_id"] == "42"
    assert call["data"]["parse_mode"] == "HTML"
    assert call["data"]["disable_web_page_preview"] == "true"
    assert call["data"]["text"] == "hi <b>there</b>"


def test_send_retries_then_raises(monkeypatch):
    monkeypatch.setattr(notify.time, "sleep", lambda *_: None)   # no real backoff wait
    sess = FakeSession([FakeResp(400, {"ok": False, "description": "bad"})] * 3)
    n = notify.Notifier("TOK", "42", session=sess)
    with pytest.raises(notify.NotifyError):
        n.send("x")
    assert len(sess.calls) == 3                     # 1 + 2 retries
