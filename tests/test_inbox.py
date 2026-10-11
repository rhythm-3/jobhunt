import base64
import json
import unittest

from jobagent.agents import sourcing, triage
from jobagent.agents.dispatch import Blocked
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.mail import GmailReader, GmailSender, extract_body
from jobagent.orchestrator import Orchestrator
from jobagent.schemas import CandidateProfile, InboundClass, RunStatus
from tests.test_mail import FULL, TOK, FakeHttp
from tests.test_system import make

PROFILE = CandidateProfile(**SAMPLE_PROFILE)
b64 = lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def gmsg(mid, sender, subject, body, ts="1790000000000"):
    return (200, {"id": mid, "internalDate": ts, "payload": {"mimeType": "multipart/alternative", "headers": [
        {"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
        "parts": [{"mimeType": "text/plain", "body": {"data": b64(body)}}]}})


class Body(unittest.TestCase):
    def test_plain_preferred_html_fallback_nested(self):
        self.assertEqual(extract_body({"mimeType": "text/plain", "body": {"data": b64("hi")}}), "hi")
        nested = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<p>Book <b>now</b></p>")}}]}]}
        self.assertIn("Book now", extract_body(nested))


class Poll(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store, self.ctx = make()
        sourcing.run_sourcing(self.store, [sourcing.FixtureSource()], PROFILE)

    def reader(self, *script):
        return GmailReader(GmailSender(FULL, FakeHttp(TOK, *script)))

    def test_keeps_job_mail_ignores_unrelated_and_never_stores_it(self):
        r = self.reader((200, {"messages": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}), (200, {}),       # applied-search, recruiter-search
                        gmsg("a", "Jo <jo@acmecloud.com>", "Interview", "Please book https://calendly.com/jo/30"),
                        gmsg("b", "news@shop.com", "Sale", "50% off shoes"),
                        gmsg("c", "adityasapra25@gmail.com", "Note to self", "interview prep"))
        stats = triage.poll_inbox(self.store, r, own_address="adityasapra25@gmail.com")
        self.assertEqual(stats, {"seen": 3, "kept": 1, "ignored": 1, "imported": 0})
        self.assertEqual([m.id for m in self.store.list_emails()], ["gmail:a"])
        self.assertEqual(self.store.list_emails()[0].label, InboundClass.INTERVIEW)

    def test_second_poll_skips_seen_ids_without_refetching(self):
        h = FakeHttp(TOK, (200, {"messages": [{"id": "a"}]}), (200, {}), gmsg("a", "x@y.co", "Interview", "schedule a call"),
                     (200, {"messages": [{"id": "a"}]}), (200, {}))
        rd = GmailReader(GmailSender(FULL, h))
        triage.poll_inbox(self.store, rd); n = len(h.calls)
        self.assertEqual(triage.poll_inbox(self.store, rd), {"seen": 0, "kept": 0, "ignored": 0, "imported": 0})
        self.assertEqual(len(h.calls), n + 2)                     # only the two list calls, no per-message fetch

    def test_reply_advances_the_matching_run(self):
        o = Orchestrator(self.ctx)
        run = o.resume(o.start("fx-1").id, "approve")
        r = self.reader((200, {"messages": [{"id": "z"}]}), (200, {}),
                        gmsg("z", "hr@acmecloud.com", "Acme Cloud interview", "We'd like to schedule an interview"))
        triage.poll_inbox(self.store, r)
        self.assertEqual(self.store.get_run(run.id).status, RunStatus.INTERVIEW)

    def test_missing_scope_gives_actionable_error(self):
        r = self.reader((403, {"error": {"message": "Request had insufficient authentication scopes."}}))
        with self.assertRaises(Blocked) as c:
            triage.poll_inbox(self.store, r)
        self.assertIn("gmail_auth.py", str(c.exception))


if __name__ == "__main__":
    unittest.main()
