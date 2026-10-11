import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from jobagent.agents import triage
from jobagent.db import Store
from jobagent.mail import APPLIED_QUERY, GmailReader, RECRUITER_QUERY
from jobagent.schemas import InboundClass as C, InboundEmail


def mail(sender, subject, body="", name=""):
    return triage.classify(InboundEmail(id="gmail:x", sender=sender, sender_name=name, subject=subject, body=body))


class Classify(unittest.TestCase):
    def test_application_confirmations_from_real_subject_lines(self):
        cases = [("jobs-noreply@linkedin.com", "Your application was sent to Acme Corp", "Acme Corp"),
                 ("jobs-noreply@linkedin.com", "Your application was viewed by Globex", "Globex"),
                 ("no-reply@us.greenhouse-mail.io", "AlphaSense - Thank You for Applying", "AlphaSense"),
                 ("careers@mail.volvo.com", "Volvo Group - Thank you for your application!", "Volvo Group"),
                 ("noreply@messages.naukri.com", "Your application for AI Engineer with G2", "G2")]
        for sender, subject, company in cases:
            m = mail(sender, subject, "Hello Aditya, we will review your profile.")
            self.assertEqual((m.label, m.company), (C.ACK, company), subject)

    def test_status_updates_count_as_applications_and_can_still_be_rejections(self):
        m = mail("jobs@recruitment.americanexpress.com", "Update on Your Application", "Thank you for your interest. We will keep your profile.")
        self.assertEqual(m.label, C.ACK); self.assertEqual(m.company, "Americanexpress")
        m = mail("jobs@recruitment.americanexpress.com", "Update on Your Application", "Unfortunately we are not moving forward.")
        self.assertEqual(m.label, C.REJECTION)

    def test_unfinished_applications_and_reminders_are_not_applications(self):
        for subject in ("Your application is still incomplete", "Continue Your Application with EY GDS - Cyber Security",
                        "Hurry, complete your application now."):
            self.assertEqual(mail("x@jobs.example.com", subject, "Thank you for applying. We have received your details.").label, C.OTHER, subject)

    def test_short_company_domains_and_marketing_senders(self):
        m = mail("talent@ey.com", "ADITYA SAPRA | EY Interview | MS Teams", "We would like to schedule an interview with you.")
        self.assertEqual((m.label, m.company), (C.INTERVIEW, "EY"))
        self.assertEqual(mail("hello@mail.hackajob.com", "Make sure you're set up for the best matches", "Complete your profile").label, C.OTHER)

    def test_linkedin_recruiter_message_and_offer(self):
        m = mail("messages-noreply@linkedin.com", "Priya Sharma sent you a message", "Hi Aditya, I'm hiring for a Senior Detection Engineer role at Acme.")
        self.assertEqual(m.label, C.SCREENING); self.assertIn("LinkedIn", m.action)
        self.assertEqual(mail("messages-noreply@linkedin.com", "New on LinkedIn: your weekly digest", "Top stories in your network").label, C.OTHER)
        o = mail("hr@acme.com", "Offer of employment", "We are pleased to offer you the position of Security Engineer. Please find the offer letter attached.")
        self.assertEqual(o.label, C.SCREENING); self.assertIn("Offers", o.action)
        self.assertEqual(mail("noreply@glassdoor.com", "Job at Nike is still available. Apply Soon.", "Unsubscribe | manage preferences").label, C.OTHER)


class FakeAuth:
    """Gmail transport stub: serves paged message lists keyed by the query."""
    def __init__(self):
        self.calls = []
        self.pages = {"A": [["a1", "a2"], ["a3"]], "R": [["a2", "r1"]]}
    def _access_token(self, force=False): return "t"
    def http(self, method, url, headers, body):
        import json
        q = parse_qs(urlparse(url).query)
        self.calls.append(q)
        key = "A" if "subject:(application" in q["q"][0] else "R"
        page = int(q.get("pageToken", ["0"])[0]) if "pageToken" in q else 0
        pages = self.pages[key]
        out = {"messages": [{"id": i} for i in pages[page]]}
        if page + 1 < len(pages):
            out["nextPageToken"] = str(page + 1)
        return 200, json.dumps(out).encode()


class Queries(unittest.TestCase):
    def test_both_searches_are_paged_deduped_and_not_limited_to_the_inbox(self):
        auth = FakeAuth()
        ids = GmailReader(auth).list_ids(days=60)
        self.assertEqual(ids, ["a1", "a2", "a3", "r1"])                       # 2 pages merged, duplicate a2 once
        qs = [c["q"][0] for c in auth.calls]
        self.assertTrue(any("newer_than:60d" in q for q in qs))
        for q in (APPLIED_QUERY, RECRUITER_QUERY):
            self.assertNotIn("in:inbox", q); self.assertIn("-in:spam", q)
        self.assertIn("jobs-noreply@linkedin.com", APPLIED_QUERY)

    def test_first_scan_looks_back_further_then_settles(self):
        seen = []
        class R:
            def list_ids(self, days=14, limit=150): seen.append(days); return []
        store = Store(tempfile.mkdtemp() + "/s.db")
        triage.poll_inbox(store, R(), "me@x.com"); triage.poll_inbox(store, R(), "me@x.com")
        self.assertEqual(seen, [60, 14])

    def test_old_confirmation_becomes_a_tracked_application(self):
        store = Store(tempfile.mkdtemp() + "/s.db")
        class R:
            def list_ids(self, days=14, limit=150): return ["1"]
            def fetch(self, mid): return InboundEmail(id="gmail:1", sender="no-reply@us.greenhouse-mail.io", subject="AlphaSense - Thank You for Applying",
                                                      body="We received your application for Security Engineer.")
        stats = triage.poll_inbox(store, R(), "me@x.com")
        self.assertEqual(stats["imported"], 1)
        runs = store.list_runs()
        self.assertEqual(store.get_job(runs[0].job_id).company, "AlphaSense"); self.assertEqual(runs[0].status.value, "submitted")


if __name__ == "__main__":
    unittest.main()


class Sources(unittest.TestCase):
    def test_boards_search_for_the_users_own_titles(self):
        from jobagent.agents import feeds
        sw = feeds.default_sources(["python", "software", "developer"])
        self.assertEqual(sw[0].searches, ("python", "software", "developer"))
        self.assertIn("dev", sw[1].tags); self.assertNotIn("security", sw[1].tags)
        self.assertTrue(any("programming" in s.url for s in sw[2:])); self.assertFalse(any("sysadmin" in s.url for s in sw[2:]))
        sec = feeds.default_sources(["detection", "security"])
        self.assertIn("security", sec[1].tags); self.assertTrue(any("sysadmin" in s.url for s in sec[2:]))
        self.assertEqual(feeds.default_sources()[0].searches[0], "security")                     # no preferences: old defaults
        self.assertEqual(feeds.remote_sources(["python", "software"])[1].tags, ["python", "software"])
