import base64
import email
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path

from jobagent.agents import sourcing
from jobagent.agents.dispatch import Blocked, EmailSubmitter, RateLimited, RateLimiter, Transient
from jobagent.mail import GmailSender, build_message, clean_addr
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile
from tests.test_system import make

PROFILE = CandidateProfile(**SAMPLE_PROFILE)


class Secrets:
    def __init__(self, **kw): self.kw = kw
    def get(self, n): return self.kw.get(n)


FULL = Secrets(GMAIL_CLIENT_ID="id", GMAIL_CLIENT_SECRET="s", GMAIL_REFRESH_TOKEN="r")


class FakeHttp:
    """Scripted responses; each item is (status, dict|bytes) or an Exception to raise."""
    def __init__(self, *script): self.script, self.calls = list(script), []

    def __call__(self, method, url, headers, body):
        self.calls.append((url, headers, body))
        r = self.script.pop(0)
        if isinstance(r, Exception): raise r
        st, data = r
        return st, data if isinstance(data, bytes) else json.dumps(data).encode()


TOK = (200, {"access_token": "AT", "expires_in": 3600})
OK = (200, {"id": "m123"})


def msg():
    return build_message("alex@example.com", "jobs@acme.example", "alex@example.com", "Application", "hello", None, "x")


class Message(unittest.TestCase):
    def test_header_injection_rejected(self):
        for bad in ("a@b.co\nBcc: evil@x.com", "a@b.co, c@d.co", "not-an-email", "a@b.co>"):
            with self.assertRaises(Blocked):
                clean_addr(bad)

    def test_subject_newlines_stripped_and_attachment_named_safely(self):
        d = tempfile.mkdtemp(); f = Path(d, "resume.pdf"); f.write_bytes(b"%PDF-1.4 x")
        m = build_message("a@b.co", "c@d.co", "a@b.co", "Hi\r\nBcc: x@y.z", "body", str(f), "Alex ../Morgan_Resume")
        self.assertNotIn("\n", m["Subject"]); self.assertIsNone(m["Bcc"])
        part = [p for p in email.message_from_bytes(m.as_bytes()).walk() if p.get_filename()][0]
        self.assertEqual(part.get_filename(), "Alex_.._Morgan_Resume.pdf".replace("..", ".."))
        self.assertNotIn("/", part.get_filename())


class Sender(unittest.TestCase):
    def test_not_configured_fails_closed(self):
        with self.assertRaises(Blocked):
            GmailSender(Secrets(), FakeHttp()).send(msg())

    def test_success_sends_raw_rfc822_and_caches_token(self):
        h = FakeHttp(TOK, OK, OK)
        s = GmailSender(FULL, h)
        self.assertEqual(s.send(msg()), "m123"); s.send(msg())
        self.assertEqual(len(h.calls), 3)                        # one token fetch, two sends
        raw = base64.urlsafe_b64decode(json.loads(h.calls[1][2])["raw"])
        self.assertIn(b"jobs@acme.example", raw)
        self.assertEqual(h.calls[1][1]["Authorization"], "Bearer AT")

    def test_401_refreshes_once_then_sends(self):
        h = FakeHttp(TOK, (401, {"error": {"message": "expired"}}), TOK, OK)
        self.assertEqual(GmailSender(FULL, h).send(msg()), "m123")

    def test_revoked_refresh_token_is_blocked_not_retried(self):
        with self.assertRaises(Blocked):
            GmailSender(FULL, FakeHttp((400, {"error": "invalid_grant"}))).send(msg())

    def test_rate_limit_and_5xx_mapping(self):
        with self.assertRaises(RateLimited):
            GmailSender(FULL, FakeHttp(TOK, (429, {}))).send(msg())
        with self.assertRaises(RateLimited):
            GmailSender(FULL, FakeHttp(TOK, (403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}))).send(msg())
        with self.assertRaises(Transient):
            GmailSender(FULL, FakeHttp(TOK, (503, {}))).send(msg())
        with self.assertRaises(Blocked):
            GmailSender(FULL, FakeHttp(TOK, (400, {"error": {"message": "bad"}}))).send(msg())

    def test_ambiguous_timeout_is_never_retryable(self):
        with self.assertRaises(Blocked) as c:
            GmailSender(FULL, FakeHttp(TOK, socket.timeout("timed out"))).send(msg())
        self.assertIn("Sent folder", str(c.exception))

    def test_provable_non_delivery_is_transient(self):
        e = urllib.error.URLError(ConnectionRefusedError())
        with self.assertRaises(Transient):
            GmailSender(FULL, FakeHttp(TOK, e)).send(msg())


class Submitter(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store, _ = make(dry_run=False)
        sourcing.run_sourcing(self.store, [sourcing.FixtureSource()], PROFILE)
        self.job = self.store.get_job("fx-1")
        self.lim = RateLimiter(self.store, self.cfg)

    def sub(self, h):
        return EmailSubmitter(self.cfg, self.lim, self.store, lambda: PROFILE, GmailSender(FULL, h))

    def test_live_send_then_duplicate_blocked(self):
        s = self.sub(FakeHttp(TOK, OK))
        self.assertIn("m123", s.submit(self.job, "", "cover"))
        with self.assertRaises(Blocked):
            s.submit(self.job, "", "cover")

    def test_live_without_sender_fails_closed(self):
        with self.assertRaises(Blocked):
            EmailSubmitter(self.cfg, self.lim, self.store, lambda: PROFILE, None).submit(self.job, "", "c")

    def test_failed_send_is_not_marked_sent(self):
        s = self.sub(FakeHttp(TOK, (503, {}), (503, {})))
        with self.assertRaises(Transient):
            s.submit(self.job, "", "c")
        self.assertIsNone(self.store.kv_get(f"sent:{self.job.id}"))

    def test_dry_run_sends_nothing(self):
        cfg, store, _ = make(dry_run=True)
        store.add_job(self.job)
        h = FakeHttp()
        out = EmailSubmitter(cfg, RateLimiter(store, cfg), store, lambda: PROFILE, GmailSender(FULL, h)).submit(self.job, "", "c")
        self.assertIn("dry-run", out); self.assertEqual(h.calls, [])


if __name__ == "__main__":
    unittest.main()
