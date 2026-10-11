import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from jobagent.agents import outreach as out, sourcing
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.mail import GmailSender
from jobagent.schemas import CandidateProfile, InboundEmail, Outreach

P = CandidateProfile(**{**SAMPLE_PROFILE, "links": ["https://linkedin.com/in/alex"]})
JD = "We need a detection engineer. Requirements: Python, Splunk, Sigma rules and AWS. You will build detections. " * 2
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def O(**kw):
    return Outreach(**{"id": "o1", "company": "Acme", "role": "Detection Engineer", "contact_name": "Priya Sharma",
                       "email": "priya@acme.com", "subject": "s", "body": "b", **kw})


class Rules(unittest.TestCase):
    def test_draft_is_personal_grounded_and_has_opt_out(self):
        o = O(job_text=JD, note="I've followed Acme's detection-as-code work for a while.")
        subject, body, method, warns = out.draft(Settings(), P, o)
        self.assertEqual(method, "template")
        self.assertIn("Hi Priya,", body); self.assertIn("Detection Engineer", body); self.assertIn("Acme", body)
        self.assertIn("followed Acme's detection-as-code", body)            # the user's own sentence, verbatim
        self.assertIn(out.OPT_OUT, body); self.assertIn(P.full_name, body); self.assertIn("linkedin.com/in/alex", body)
        self.assertEqual(out.ungrounded(body, P, f"{o.company} {o.role} {o.job_text} {o.note} {o.contact_name}"), [])
        self.assertIn(P.full_name, subject)
        self.assertEqual(warns, [])
        _, _, _, warns2 = out.draft(Settings(), P, O())
        self.assertEqual(len(warns2), 2)                                      # no posting, no personal sentence: nudges

    def test_ungrounded_catches_invented_numbers_and_tools(self):
        bad = out.ungrounded("I cut costs by 93% using QRadar and Jenkins.", P)
        self.assertIn("93", bad); self.assertTrue({"qradar", "jenkins"} <= set(bad))     # incl. a tool ending the sentence
        self.assertEqual(out.ungrounded("Hello there, I would love to chat.", P), [])

    def test_tailoring_guard_catches_an_invented_tool_ending_a_sentence(self):
        from jobagent.agents import matcher
        a = matcher.RuleTailorer().tailor(P, out.jd_job(O(job_text=JD)), matcher.parse_jd(out.jd_job(O(job_text=JD))))
        matcher.verify_grounded(P, a)
        a.cover_letter = "I'm keen to join. I have also run pipelines on Jenkins."
        with self.assertRaises(matcher.HallucinationError):
            matcher.verify_grounded(P, a)

    def test_blockers(self):
        a = O(id="a", sent_at=NOW - timedelta(days=3), status="sent")
        self.assertEqual(out.blockers(O(id="b"), [a], NOW)[0], "You already emailed this person in the last 30 days.")
        self.assertEqual(out.blockers(O(id="b"), [], NOW), [])
        self.assertIn("placeholders", " ".join(out.blockers(O(body="Hi [name]"), [], NOW)))
        self.assertIn("email address", out.blockers(O(email=""), [], NOW)[0])
        dnc = O(id="c", status="do_not_contact")
        self.assertIn("not to be contacted", out.blockers(O(id="b"), [dnc], NOW)[0])
        two = [O(id="x1", email="a@acme.com", sent_at=NOW - timedelta(days=2), status="sent"),
               O(id="x2", email="b@acme.com", sent_at=NOW - timedelta(days=1), status="sent")]
        self.assertIn("2 people at Acme", out.blockers(O(id="n", email="c@acme.com"), two, NOW)[0])
        self.assertEqual(out.blockers(O(id="n", email="c@other.com", company="Other"), two, NOW), [])

    def test_followup_rules_and_view(self):
        o = O(status="sent", sent_at=NOW - timedelta(days=6), receipt="gmail")
        self.assertTrue(out.view(o, NOW)["follow_up_due"]); self.assertEqual(out.followup_blockers(o, NOW), [])
        self.assertTrue(out.followup_blockers(O(status="sent", sent_at=NOW - timedelta(days=1)), NOW))
        self.assertIn("once", out.followup_blockers(O(status="sent", sent_at=NOW - timedelta(days=9), followups_sent=1), NOW)[0])
        self.assertFalse(out.view(O(status="sent", sent_at=NOW - timedelta(days=9), receipt="dry-run: not sent"), NOW)["follow_up_due"])
        s, b = out.followup_draft(P, o)
        self.assertTrue(s.startswith("Re:")); self.assertIn("won't follow up again", b)

    def test_stats(self):
        items = [O(id="1", status="sent", sent_at=NOW - timedelta(hours=2), receipt="g"),
                 O(id="2", status="replied", sent_at=NOW - timedelta(days=2), receipt="g", replied_at=NOW),
                 O(id="3", status="draft")]
        s = out.stats(items, 10, NOW)
        self.assertEqual((s["sent"], s["replied"], s["drafts"], s["sent_today"], s["cap_left"], s["reply_rate"]), (2, 1, 1, 1, 9, 0.5))

    def test_links_open_in_the_users_browser_only(self):
        links = out.search_links("Wayne Security", "Detection Engineer")
        self.assertTrue(links["linkedin_recruiters"].startswith("https://www.linkedin.com/search/results/people/?keywords=Wayne"))
        self.assertIn("careers", links["careers_contact"])

    def test_reply_scan(self):
        class Reader:
            def __init__(self, msgs): self.msgs = msgs
            def search_ids(self, q, n): return list(self.msgs)
            def fetch(self, i): return self.msgs[i]
        mk = lambda sender, body, when=NOW: InboundEmail(id="x", sender=sender, subject="Re: hello", body=body, received_at=when)
        o = O(status="sent", sent_at=NOW - timedelta(days=3), receipt="g")
        classify = lambda m: m
        cases = {"Thanks, can we talk Tuesday?": "replied", "Please remove me from your list.": "do_not_contact",
                 "Not interested, sorry.": "declined"}
        for text, kind in cases.items():
            self.assertEqual(out.scan_replies(Reader({"1": mk("priya@acme.com", text)}), [o], classify)[0][1], kind, text)
        self.assertEqual(out.scan_replies(Reader({"1": mk("MAILER-DAEMON@google.com", "Address not found")}), [o], classify)[0][1], "bounced")
        self.assertEqual(out.scan_replies(Reader({"1": mk("priya@acme.com", "old", NOW - timedelta(days=9))}), [o], classify), [])   # before we sent


def client(**cfg):
    d = tempfile.mkdtemp()
    app = build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o", **cfg), [sourcing.FixtureSource()])
    app.state.outreach_delay = lambda: 0
    return TestClient(app)


class Api(unittest.TestCase):
    def setUp(self):
        self.c = client()

    def add(self, **kw):
        r = self.c.post("/api/outreach", json={"contact_name": "Priya Sharma", "email": "priya@acme.com", "company": "Acme",
                                               "role": "Detection Engineer", "job_text": JD, **kw})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_create_validate_and_duplicates(self):
        o = self.add()
        self.assertEqual(o["status"], "draft"); self.assertIn("Hi Priya,", o["body"]); self.assertEqual(o["channel"], "email")
        self.assertEqual(self.c.post("/api/outreach", json={"company": "Acme", "email": "priya@acme.com"}).status_code, 409)
        self.assertEqual(self.c.post("/api/outreach", json={"company": "X", "email": "not-an-email"}).status_code, 422)
        self.assertEqual(self.c.post("/api/outreach", json={"company": "X", "linkedin_url": "https://evil.com/in/x", "contact_name": "A"}).status_code, 422)
        self.assertEqual(self.c.post("/api/outreach", json={"company": "X"}).status_code, 422)
        li = self.c.post("/api/outreach", json={"company": "Initech", "contact_name": "Sam Lee", "linkedin_url": "https://www.linkedin.com/in/samlee/"}).json()
        self.assertEqual(li["channel"], "linkedin")                          # no email: message is for LinkedIn
        self.assertIn("email address", li["blockers"][0])
        self.assertEqual(self.c.post(f"/api/outreach/{li['id']}/approve").status_code, 422)
        self.assertEqual(self.c.get("/api/outreach/links?company=Initech").status_code, 200)
        self.assertEqual(self.c.get("/api/outreach/links?company=").status_code, 422)

    def test_approval_gate_and_practice_send(self):
        o = self.add()
        self.assertEqual(self.c.post("/api/outreach/send-approved").status_code, 409)            # nothing approved
        bad = self.c.put(f"/api/outreach/{o['id']}", json={"body": o["body"] + "\nI cut alert volume by 93%."}).json()
        self.assertEqual(self.c.post(f"/api/outreach/{o['id']}/approve").status_code, 422)       # invented number is refused
        self.c.put(f"/api/outreach/{o['id']}", json={"body": o["body"]})
        self.assertEqual(self.c.post(f"/api/outreach/{o['id']}/approve").json()["status"], "approved")
        ed = self.c.put(f"/api/outreach/{o['id']}", json={"subject": "New subject"}).json()
        self.assertEqual(ed["status"], "draft")                                                   # editing withdraws approval
        r = self.c.post(f"/api/outreach/{o['id']}/send").json()                                   # "Send now" approves that one email
        self.assertEqual((r["status"], r["practice"], r["dry_run"]), ("sent", True, True))
        self.assertEqual(self.c.put(f"/api/outreach/{o['id']}", json={"body": "x"}).status_code, 409)
        self.assertEqual(self.c.post(f"/api/outreach/{o['id']}/send").status_code, 409)
        st = self.c.get("/api/outreach").json()
        self.assertEqual((st["stats"]["sent"], st["stats"]["sent_today"]), (1, 1))
        self.assertEqual([e["event"] for e in st["items"][0]["events"]], ["created", "approved", "edited", "approved", "sent"])

    def test_import_and_cv(self):
        r = self.c.post("/api/outreach/import", json={"text": "Priya Sharma, priya@acme.com, Acme, Detection Engineer\n"
                                                              "Sam Lee, https://www.linkedin.com/in/samlee, Initech\nnonsense"}).json()
        self.assertEqual(r["created"], 2); self.assertEqual(len(r["skipped"]), 1)
        items = self.c.get("/api/outreach").json()["items"]
        acme = next(i for i in items if i["company"] == "Acme")
        cv = self.c.get(f"/api/outreach/{acme['id']}/cv")
        self.assertEqual(cv.status_code, 200); self.assertIn("_CV_Acme", cv.headers["content-disposition"])
        self.assertTrue(cv.content)

    def test_mark_delete_rules(self):
        o = self.add()
        m = self.c.post(f"/api/outreach/{o['id']}/mark", json={"status": "do_not_contact"}).json()
        self.assertEqual(m["status"], "do_not_contact")
        self.assertEqual(self.c.delete(f"/api/outreach/{o['id']}").status_code, 409)             # suppression can't be erased
        self.assertEqual(self.c.post(f"/api/outreach/{o['id']}/mark", json={"status": "nope"}).status_code, 422)
        o2 = self.add(email="b@acme.com", contact_name="Bo Li")
        self.assertEqual(self.c.delete(f"/api/outreach/{o2['id']}").status_code, 200)
        o3 = self.add(email="priya2@acme.com", contact_name="Priya Two")
        self.assertEqual(self.c.post(f"/api/outreach/{o3['id']}/contacted").json()["status"], "sent")   # sent it myself on LinkedIn


class Auto(unittest.TestCase):
    def setUp(self):
        self.c = client()
        self.c.post("/api/sweep")
        import time
        for _ in range(100):
            if not self.c.get("/api/sweep/status").json()["running"]:
                break
            time.sleep(0.05)

    def test_refresh_prepares_drafts_for_best_matches_and_sends_nothing(self):
        st = self.c.get("/api/outreach").json()
        autos = [i for i in st["items"] if i["auto"]]
        self.assertTrue(0 < len(autos) <= 5)
        self.assertEqual(len({i["company"] for i in autos}), len(autos))            # one per company
        self.assertTrue(all(i["status"] == "draft" and i["needs_contact"] and i["run_id"] and not i["reviewed"] for i in autos))
        self.assertEqual(st["stats"]["to_find"], len(autos)); self.assertEqual(st["stats"]["sent"], 0)
        again = self.c.post("/api/outreach/auto-draft", json={"limit": 20}).json()["created"]
        ids = [i["run_id"] for i in self.c.get("/api/outreach").json()["items"]]
        self.assertEqual(len(ids), len(set(ids)))                                   # never two drafts for the same job
        self.assertIsInstance(again, int)
        self.c.put("/api/settings", json={**self.c.get("/api/settings").json(), "auto_outreach": 0})
        self.assertEqual(self.c.post("/api/outreach/auto-draft", json={"limit": 0}).status_code, 200)

    def test_approve_and_send_only_takes_drafts_you_have_read(self):
        add = lambda n, e, co: self.c.post("/api/outreach", json={"contact_name": n, "email": e, "company": co, "role": "Analyst", "job_text": JD}).json()
        a, b, none = add("Ann Ray", "ann@one.com", "One"), add("Bob Ng", "bob@two.com", "Two"), self.c.get("/api/outreach").json()["items"][-1]
        self.assertFalse(a["reviewed"])
        r = self.c.post("/api/outreach/approve-and-send", json={"ids": [a["id"]]})
        self.assertEqual(r.status_code, 422); self.assertIn("read this one first", r.json()["detail"])      # unread: refused
        self.c.post(f"/api/outreach/{a['id']}/reviewed")
        r = self.c.post("/api/outreach/approve-and-send", json={"ids": [a["id"], b["id"], none["id"]]}).json()
        self.assertEqual(r["approved"], 1); self.assertEqual({x["id"] for x in r["skipped"]}, {b["id"], none["id"]})
        import time
        for _ in range(100):
            if not self.c.get("/api/outreach").json()["queue"]["running"]:
                break
            time.sleep(0.05)
        by = {i["id"]: i for i in self.c.get("/api/outreach").json()["items"]}
        self.assertEqual((by[a["id"]]["status"], by[a["id"]]["practice"]), ("sent", True))
        self.assertEqual(by[b["id"]]["status"], "draft")
        self.c.post(f"/api/outreach/{b['id']}/draft", json={"note": "New sentence."})                   # a rewrite needs reading again
        rb = next(i for i in self.c.get("/api/outreach").json()["items"] if i["id"] == b["id"])
        self.assertFalse(rb["reviewed"])


class Live(unittest.TestCase):
    """Real-send mode with Gmail mocked: attachments, spacing queue, daily cap, follow-ups, reply detection."""
    def setUp(self):
        self.c = client(dry_run=False)
        self.sent = []
        self.patches = [mock.patch.object(GmailSender, "configured", new_callable=mock.PropertyMock, return_value=True),
                        mock.patch.object(GmailSender, "send", autospec=True, side_effect=lambda s, msg, thread_id=None: (self.sent.append((msg, thread_id)), f"id{len(self.sent)}")[1])]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def add_approved(self, email, name, company="Acme"):
        o = self.c.post("/api/outreach", json={"contact_name": name, "email": email, "company": company, "role": "Detection Engineer", "job_text": JD}).json()
        self.assertEqual(self.c.post(f"/api/outreach/{o['id']}/approve").status_code, 200)
        return o["id"]

    def wait_queue(self):
        import time
        for _ in range(100):
            if not self.c.get("/api/outreach").json()["queue"]["running"]:
                return
            time.sleep(0.05)
        self.fail("queue did not finish")

    def test_queue_sends_with_tailored_cv_attached(self):
        a, b = self.add_approved("a@acme.com", "Ann Ray"), self.add_approved("b@other.com", "Bob Ng", "Other")
        self.c.post("/api/outreach/send-approved"); self.wait_queue()
        self.assertEqual(len(self.sent), 2)
        msg = self.sent[0][0]
        self.assertEqual(msg["To"], "a@acme.com"); self.assertIn("Detection Engineer at Acme", msg["Subject"])
        atts = [p for p in msg.iter_attachments()]
        self.assertEqual(len(atts), 1); self.assertIn("_CV_Acme", atts[0].get_filename())
        self.assertIn("Hi Ann,", msg.get_body().get_content()); self.assertIn("no thanks", msg.get_body().get_content())
        self.assertEqual({i["status"] for i in self.c.get("/api/outreach").json()["items"]}, {"sent"})

    def test_daily_cap_leaves_the_rest_approved(self):
        self.c.put("/api/settings", json={**self.c.get("/api/settings").json(), "outreach_daily_cap": 1})
        a, b = self.add_approved("a@acme.com", "Ann Ray"), self.add_approved("b@other.com", "Bob Ng", "Other")
        self.c.post("/api/outreach/send-approved"); self.wait_queue()
        st = self.c.get("/api/outreach").json()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(sorted(i["status"] for i in st["items"]), ["approved", "sent"])
        self.assertIn("Daily limit", st["queue"]["note"])
        self.assertEqual(self.c.post(f"/api/outreach/{b}/send").status_code, 429)

    def test_followup_goes_in_the_same_thread_once(self):
        a = self.add_approved("a@acme.com", "Ann Ray")
        self.c.post(f"/api/outreach/{a}/send")
        self.assertEqual(self.c.post(f"/api/outreach/{a}/followup/draft").status_code, 200)
        self.assertEqual(self.c.post(f"/api/outreach/{a}/followup/send").status_code, 422)       # too soon after the first email
        with mock.patch.object(out, "FOLLOWUP_AFTER_DAYS", 0), \
             mock.patch("jobagent.mail.GmailReader.headers", return_value={"message-id": "<m1@x>", "threadId": "T9"}):
            it = self.c.post(f"/api/outreach/{a}/followup/send").json()
            self.assertEqual(it["followups_sent"], 1)
            msg, thread = self.sent[-1]
            self.assertEqual((msg["In-Reply-To"], thread), ("<m1@x>", "T9"))
            self.assertEqual(len(list(msg.iter_attachments())), 0)
            self.assertEqual(self.c.post(f"/api/outreach/{a}/followup/send").status_code, 422)   # one follow-up is the limit

    def test_replies_update_the_tracker(self):
        a = self.add_approved("a@acme.com", "Ann Ray")
        self.c.post(f"/api/outreach/{a}/send")
        msg = InboundEmail(id="gmail:1", sender="a@acme.com", subject="Re: Detection Engineer at Acme", body="Thanks! Are you free for a call on Tuesday?",
                           received_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        with mock.patch("jobagent.mail.GmailReader.search_ids", return_value=["1"]), mock.patch("jobagent.mail.GmailReader.fetch", return_value=msg):
            self.assertEqual(self.c.post("/api/outreach/check-replies").json()["updated"], 1)
        it = self.c.get("/api/outreach").json()["items"][0]
        self.assertIn(it["status"], ("replied", "interview")); self.assertIn("call on Tuesday", it["reply_snippet"])
        self.assertEqual(self.c.get("/api/outreach").json()["stats"]["replied"], 1)


if __name__ == "__main__":
    unittest.main()
