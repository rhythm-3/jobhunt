import base64
import tempfile
import unittest
from fastapi.testclient import TestClient

from jobagent.agents import sourcing
from jobagent.agents.assist import rule_prep, template_reply
from jobagent.agents.resume_parse import extract_text, heuristic_parse, verify
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.mail import build_reply
from jobagent.salary import parse_salary
from jobagent.schemas import CandidateProfile, InboundClass, InboundEmail, JobListing

P = CandidateProfile(**SAMPLE_PROFILE)
RESUME = """JANE DOE
Pune, India • +91 90000 00000 • jane@example.com
linkedin.com/in/jane-doe
SUMMARY
Security engineer building detection pipelines with Python and Splunk.
EXPERIENCE
Acme Corp Pune, India
Security Engineer Jan 2023 – Present
• Built Splunk detections covering 120 MITRE techniques, cutting
missed alerts by 40%.
• Automated phishing triage in Python.
SKILLS
Languages: Python, SQL
Security: Splunk, Sigma, Incident Response
EDUCATION
Pune University, B.Tech Computer Science (2019 – 2023)
"""


class Resume(unittest.TestCase):
    def test_heuristic_parse_and_wrapped_bullets(self):
        p, titles = heuristic_parse(RESUME)
        self.assertEqual((p.full_name, p.email, p.location), ("Jane Doe", "jane@example.com", "Pune, India"))
        self.assertEqual(p.experience[0].company, "Acme Corp")
        self.assertEqual(p.experience[0].title, "Security Engineer")
        self.assertIn("cutting missed alerts by 40%.", p.experience[0].bullets[0])
        self.assertEqual(set(p.skills), {"Python", "SQL", "Splunk", "Sigma", "Incident Response"})
        self.assertEqual(verify(p, RESUME), {"skills": [], "bullets": [], "numbers": []})

    def test_verify_flags_invented_facts(self):
        p, _ = heuristic_parse(RESUME)
        p.skills.append("Kubernetes")
        p.experience[0].bullets.append("Led a team of 30 engineers across 5 countries.")
        v = verify(p, RESUME)
        self.assertEqual(v["skills"], ["Kubernetes"])
        self.assertEqual(len(v["bullets"]), 1)
        self.assertIn("30", v["numbers"])

    def test_file_types(self):
        self.assertIn("Splunk", extract_text("cv.txt", RESUME.encode()))
        with self.assertRaises(ValueError):
            extract_text("cv.exe", b"x" * 500)
        with self.assertRaises(ValueError):
            extract_text("cv.txt", b"too short")
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<w:document>" + "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in RESUME.splitlines()) + "</w:document>")
        self.assertIn("Acme Corp", extract_text("cv.docx", buf.getvalue()))


class Salary(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_salary("₹4L - ₹7L (Glassdoor Est.)")["label"], "₹4–7 LPA")
        self.assertEqual(parse_salary("25.0 lacs - 40.0 lacs")["max"], 40)
        self.assertEqual(parse_salary("$120k - $150k")["label"], "$120k–150k")
        self.assertIsNone(parse_salary("2 - 7 years experience"))
        self.assertIsNone(parse_salary("no pay info"))

    def test_min_salary_filter(self):
        from jobagent.agents.sourcing import passes_filters
        p = P.model_copy(update={"preferences": {**P.preferences, "min_salary_lpa": 10}})
        j = lambda d: JobListing(id="j", source="t", url="u", title="Backend Engineer", company="c", description=d, remote=True)
        self.assertIn("salary", passes_filters(j("₹4L - ₹7L"), p))
        self.assertIsNone(passes_filters(j("₹12L - ₹20L"), p))
        self.assertIsNone(passes_filters(j("pay not stated"), p))


class Assist(unittest.TestCase):
    def test_template_reply_uses_placeholders_not_invented_facts(self):
        m = InboundEmail(id="x", sender="r@acme.co", sender_name="Priya Shah", subject="Chat?", body="", company="Acme",
                         label=InboundClass.SCREENING)
        body = template_reply(P, m)
        self.assertIn("Hi Priya", body); self.assertIn("[your notice period]", body); self.assertIn(P.full_name, body)

    def test_reply_threading_headers_and_injection(self):
        orig = {"from": "Priya <priya@acme.co>", "subject": "Interview", "message-id": "<abc@acme.co>", "references": "<z@x>"}
        m = build_reply("me@gmail.com", orig, "Thanks!")
        self.assertEqual((m["To"], m["Subject"], m["In-Reply-To"]), ("priya@acme.co", "Re: Interview", "<abc@acme.co>"))
        self.assertEqual(m["References"], "<z@x> <abc@acme.co>")
        from jobagent.agents.dispatch import Blocked
        with self.assertRaises(Blocked):
            build_reply("me@gmail.com", {"from": "x@y.co\nBcc: evil@z.co", "subject": "s"}, "b")

    def test_rule_prep_is_grounded(self):
        j = JobListing(id="j", source="t", url="u", title="Backend Engineer", company="Acme",
                       description="Requirements\nPython and FastAPI\nRust\n")
        kit = rule_prep(P, j)
        all_b = {b for e in P.experience for b in e.bullets}
        for q in kit["questions"]:
            self.assertTrue(set(q["talking_points"]) <= all_b)
        self.assertTrue(any("rust" in q["question"].lower() and not q["talking_points"] for q in kit["questions"]))


class Api(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        self.c.post("/api/sweep")

    def test_parse_then_save_profile_rescores_everything(self):
        out = self.c.post("/api/profile/parse", json={"filename": "cv.txt", "data_b64": base64.b64encode(RESUME.encode()).decode()}).json()
        self.assertEqual(out["method"], "rules"); self.assertEqual(out["profile"]["full_name"], "Jane Doe")
        before = {r["job"]["id"]: r["match_score"] for r in self.c.get("/api/runs").json()}
        saved = self.c.put("/api/profile", json=out["profile"]).json()
        self.assertTrue(saved["rescored"])
        after = {r["job"]["id"]: r["match_score"] for r in self.c.get("/api/runs").json()}
        self.assertNotEqual(before, after)                       # new resume -> new scores
        self.assertEqual(self.c.get("/api/profile").json()["full_name"], "Jane Doe")
        self.assertTrue(self.c.get("/api/settings").json()["target_titles"])   # preferences preserved

    def test_parse_rejects_bad_input(self):
        self.assertEqual(self.c.post("/api/profile/parse", json={"filename": "a.pdf", "data_b64": "!!"}).status_code, 422)
        self.assertEqual(self.c.put("/api/profile", json={**SAMPLE_PROFILE, "experience": []}).status_code, 422)

    def test_insights_prep_salary_and_reply_guards(self):
        ins = self.c.get("/api/insights").json()
        self.assertEqual([f["stage"] for f in ins["funnel"]], ["Discovered", "Prepared", "Applied", "Heard back", "Interview", "Offer"])
        self.assertEqual(len(ins["timeline"]), 21); self.assertEqual(len(ins["score_hist"]), 10)
        rid = self.c.get("/api/runs").json()[0]["id"]
        kit = self.c.post(f"/api/runs/{rid}/prep").json()
        self.assertEqual(kit["method"], "rules"); self.assertEqual(self.c.get(f"/api/runs/{rid}/prep").json(), kit)
        self.c.post("/api/demo/inbox")
        self.assertEqual(self.c.post("/api/inbox/m1/draft", json={}).status_code, 200)
        self.assertEqual(self.c.post("/api/inbox/m1/reply", json={"body": "I'm free [your available times]"}).status_code, 422)
        self.assertEqual(self.c.post("/api/inbox/m1/reply", json={"body": "Tuesday works."}).status_code, 409)   # demo mail isn't Gmail
        self.assertIn("salary", self.c.get("/api/runs").json()[0])

    def test_gmail_connect_requires_client_and_callback_rejects_unknown_state(self):
        st = self.c.get("/api/gmail/status").json()
        self.assertIn("connected", st)
        r = self.c.get("/?code=abc&state=forged", follow_redirects=False)
        self.assertEqual(r.status_code, 307); self.assertIn("expired", r.headers["location"])
        self.assertEqual(self.c.post("/api/gmail/client", json={"client_id": "x", "client_secret": "y"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()


class FollowUp(unittest.TestCase):
    def test_followup_draft_and_guards(self):
        d = tempfile.mkdtemp()
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        c.post("/api/sweep")
        rid = next(r["id"] for r in c.get("/api/runs").json() if r["job"]["id"] == "fx-1")
        self.assertEqual(c.post(f"/api/runs/{rid}/followup/send", json={"body": "hi"}).status_code, 409)   # not sent yet
        c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"})
        dr = c.post(f"/api/runs/{rid}/followup/draft").json()
        self.assertEqual(dr["to"], "jobs@acme.example"); self.assertIn("Senior Backend Engineer", dr["body"])
        self.assertEqual(c.post(f"/api/runs/{rid}/followup/send", json={"body": "Checking in [your note]"}).status_code, 422)
        out = c.post(f"/api/runs/{rid}/followup/send", json={"body": dr["body"]}).json()
        self.assertTrue(out["dry_run"])


class FunnelNesting(unittest.TestCase):
    def test_every_stage_is_a_subset(self):
        from jobagent.agents import triage
        from jobagent.agents.assist import insights
        from tests.test_system import make
        _, store, _ = make()
        class R:
            def list_ids(s, days=14): return ["a"]
            def fetch(s, mid): return InboundEmail(id="a", sender="x@ey.com", subject="Thank you for applying to EY", body="received")
        triage.poll_inbox(store, R())                       # an imported application with no tailored documents
        f = [s["n"] for s in insights(store, P)["funnel"]]
        self.assertTrue(all(a >= b for a, b in zip(f, f[1:])), f)
