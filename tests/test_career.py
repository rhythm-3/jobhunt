import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from jobagent.agents import career, sourcing
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile, Experience, Interview, JobListing, Offer

P = CandidateProfile(**{**SAMPLE_PROFILE, "links": ["linkedin.com/in/alex"]})
IST = ZoneInfo("Asia/Kolkata")


class Health(unittest.TestCase):
    def test_flags_are_specific_and_grounded(self):
        p = P.model_copy(update={"experience": [Experience(company="Acme", title="Engineer", start="Jan 2022", end="Present", bullets=[
            "Responsible for the Splunk dashboards used by the SOC team", "I helped with things",
            "Built Kafka pipelines on AWS cutting latency by 40%"])]})
        h = career.resume_health(p, [{"skill": "azure", "jobs": 5, "have": False}, {"skill": "python", "jobs": 7, "have": True}])
        texts = " ".join(i["text"] for i in h["issues"])
        self.assertIn("Starts with “Responsible", texts)
        self.assertIn("personal pronouns", texts)
        self.assertIn("No measurable result", texts)
        self.assertIn("Splunk", h["add_skills"])                 # used in a bullet, missing from skills
        self.assertEqual(h["market_gaps"], ["Azure"])
        self.assertTrue(0 <= h["score"] <= 100)
        good = [i for i in h["issues"] if isinstance(i.get("target"), dict) and "40%" in i["target"]["text"]]
        self.assertFalse(any("measurable" in i["text"] for i in good))   # the bullet with a number isn't flagged for it

    def test_gap_detection(self):
        p = P.model_copy(update={"experience": [
            Experience(company="A", title="X", start="Jan 2020", end="Jan 2021", bullets=["Built a thing that saved 10 hours", "Led a thing across 3 teams"]),
            Experience(company="B", title="Y", start="Jan 2023", end="Present", bullets=["Designed a thing for 2 regions", "Shipped 4 releases on time"])]})
        self.assertTrue(any("gap" in i["text"] for i in career.resume_health(p)["issues"]))

    def test_rewrite_rejects_new_facts(self):
        opts = ["Owned Splunk dashboards for the SOC team", "Owned Splunk dashboards for 12 SOC analysts",
                "Owned Splunk and Kubernetes dashboards for the SOC"]
        with mock.patch("jobagent.agents.llm_tailor.llm_json", return_value=career.BulletRewrite(options=opts)):
            out = career.rewrite_bullet(Settings(), "Responsible for Splunk dashboards used by the SOC team")
        self.assertEqual(out, ["Owned Splunk dashboards for the SOC team"])   # no new number, no new tool


class Practice(unittest.TestCase):
    def test_star_detection_and_evidence(self):
        a = ("When our pipeline kept failing at my previous team, I was responsible for fixing it. I built a Kafka consumer with retries "
             "and I added alerts on AWS. As a result failures dropped by 90% and on-call pages fell sharply.")
        f = career.practice_feedback(Settings(), P, "Tell me about a time you fixed a reliability problem", a)
        self.assertEqual(f["parts"], {"situation": True, "action": True, "result": True})
        self.assertTrue(f["metrics"]); self.assertEqual(f["method"], "rules")
        all_b = {b for e in P.experience for b in e.bullets}
        self.assertTrue(f["evidence"] and set(f["evidence"]) <= all_b)      # only real bullets suggested

    def test_short_we_heavy_filler_answer(self):
        f = career.practice_feedback(Settings(), P, "Biggest achievement?", "Um we basically like did the migration and we shipped it, you know.")
        joined = " ".join(f["improve"])
        self.assertIn("words", joined); self.assertIn("filler", joined.lower())
        self.assertFalse(f["parts"]["action"])
        self.assertLess(f["score"], 5)


class Times(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 9, 0, tzinfo=IST)

    def t(self, s):
        return career.parse_times(s, now=self.NOW, local_tz=IST)

    def test_formats_and_zones(self):
        self.assertEqual(self.t("Tue Oct 7 at 2pm PT"), ["2026-10-07T14:00:00-07:00"])
        self.assertEqual(self.t("8th October at 11:30 am IST"), ["2026-10-08T11:30:00+05:30"])
        self.assertEqual(self.t("tomorrow at 4 pm"), ["2026-10-02T16:00:00+05:30"])
        self.assertEqual(self.t("next Monday at 10am"), ["2026-10-12T10:00:00+05:30"])
        self.assertEqual(self.t("Monday at 10am"), ["2026-10-05T10:00:00+05:30"])

    def test_past_and_nonsense_ignored(self):
        self.assertEqual(self.t("Sep 3 at 2pm"), [])               # next year's Sep 3 is > 60 days away
        self.assertEqual(self.t("Oct 32 at 2pm"), [])
        self.assertEqual(self.t("call me at 25pm"), [])


class Ics(unittest.TestCase):
    def test_valid_calendar(self):
        iv = Interview(id="x1", company="Acme, Inc.", role="SRE; Platform", starts_at=datetime(2026, 10, 8, 11, 30, tzinfo=IST),
                       link="https://meet.google.com/abc-defg-hij", notes="Line one\nLine two, with comma " + "é" * 60)
        s = career.interview_ics(iv)
        self.assertTrue(s.startswith("BEGIN:VCALENDAR\r\n") and s.endswith("END:VCALENDAR\r\n"))
        self.assertIn("DTSTART:20261008T060000Z", s); self.assertIn("DTEND:20261008T061500Z".replace("0615", "0645"), s)   # default 45 minutes
        self.assertIn("Acme\\, Inc.", s); self.assertIn("SRE\\; Platform", s); self.assertIn("\\n", s)
        self.assertTrue(all(len(l.encode()) <= 75 for l in s.split("\r\n")))
        self.assertIn("TRIGGER:-PT30M", s)


class Negotiation(unittest.TestCase):
    def test_never_invents_a_competing_offer(self):
        o = Offer(id="a", company="Acme", role="SRE", base=2_000_000)
        body, _, warns = career.negotiation_draft(Settings(), P, o, [o], 2_400_000, True, ["experience"], None)
        self.assertNotIn("another offer", body); self.assertTrue(warns)
        self.assertIn("₹24 LPA", body)

    def test_mentions_only_a_real_higher_offer(self):
        o = Offer(id="a", company="Acme", base=2_000_000); other = Offer(id="b", company="Globex", base=2_500_000, bonus=100_000)
        body, _, _ = career.negotiation_draft(Settings(), P, o, [o, other], 2_600_000, True, [], None)
        self.assertIn("₹26 LPA", body)
        self.assertNotIn("Globex", body)                              # the other company is never named
        lower = Offer(id="c", company="Initech", base=1_000_000)
        body2, _, w2 = career.negotiation_draft(Settings(), P, o, [o, lower], 2_300_000, True, [], None)
        self.assertNotIn("another offer", body2); self.assertTrue(w2)

    def test_market_reason_needs_data(self):
        o = Offer(id="a", company="Acme", base=2_000_000)
        body, _, w = career.negotiation_draft(Settings(), P, o, [o], 2_200_000, False, ["market"], {"n": 1})
        self.assertNotIn("market", body.lower()); self.assertTrue(w)


def client(**cfg):
    d = tempfile.mkdtemp()
    c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o", **cfg), [sourcing.FixtureSource()]))
    c.post("/api/sweep")
    return c


class Api(unittest.TestCase):
    def setUp(self):
        self.c = client()
        self.runs = {r["job"]["id"]: r for r in self.c.get("/api/runs").json()}

    def test_clip_create_duplicate_and_validation(self):
        desc = "We need a detection engineer. Requirements: Python, Splunk, Sigma rules and AWS. " * 3
        r = self.c.post("/api/clip", json={"url": "https://www.linkedin.com/jobs/view/123/", "title": "Detection Engineer",
                                           "company": "Wayne Security", "location": "Remote, India", "description": desc}).json()
        self.assertFalse(r["duplicate"]); self.assertIn(r["status"], ("scored", "skipped"))
        run = self.c.get(f"/api/runs/{r['run_id']}").json()
        self.assertEqual(run["job"]["source"], "saved:linkedin.com"); self.assertTrue(run["job"]["remote"])
        self.assertIsNone(run["job"]["apply_url"])                    # LinkedIn isn't an application page we automate
        again = self.c.post("/api/clip", json={"title": "Detection Engineer", "company": "Wayne Security", "description": desc + " More."}).json()
        self.assertTrue(again["duplicate"]); self.assertEqual(again["run_id"], r["run_id"])
        self.assertEqual(self.c.post("/api/clip", json={"title": "X", "description": "short"}).status_code, 422)
        self.assertEqual(self.c.post("/api/clip", json={"title": "Role", "url": "javascript:alert(1)", "description": desc}).status_code, 422)
        prep = self.c.post("/api/clip", json={"title": "Backend Engineer", "company": "Stark", "description": "Python FastAPI Postgres Kafka AWS. " * 5,
                                              "prepare": True}).json()
        self.assertEqual(prep["status"], "awaiting_approval")

    def test_downloads_notes_and_checks(self):
        rid = self.runs["fx-1"]["id"]
        d = self.c.get(f"/api/runs/{rid}/files/resume"); self.assertEqual(d.status_code, 200)
        self.assertIn("Alex_Morgan_Resume_Acme_Cloud", d.headers["content-disposition"])
        cl = self.c.get(f"/api/runs/{rid}/files/cover-letter"); self.assertEqual(cl.status_code, 200)
        self.assertEqual(self.c.get(f"/api/runs/{rid}/files/../../etc").status_code, 404)
        self.c.put(f"/api/runs/{rid}/note", json={"note": "Ask about on-call", "starred": True})
        det = self.c.get(f"/api/runs/{rid}").json()
        self.assertEqual((det["note"], det["starred"]), ("Ask about on-call", True))
        self.assertTrue(det["checks"]); self.assertTrue(any("Acme Cloud" in c["text"] for c in det["checks"]))

    def test_placeholder_blocks_and_duplicate_warns(self):
        rid = self.runs["fx-1"]["id"]
        self.c.put(f"/api/runs/{rid}/cover", json={"cover_letter": "Dear team, I love [company name]. " * 20})
        checks = self.c.get(f"/api/runs/{rid}").json()["checks"]
        self.assertTrue(any(c["level"] == "block" for c in checks))

    def test_interviews_flow(self):
        rid = self.runs["fx-4"]["id"]
        self.c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"})
        start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        iv = self.c.post("/api/interviews", json={"run_id": rid, "company": "Umbrella Labs", "role": "Backend Engineer",
                                                   "starts_at": start, "kind": "video", "link": "https://zoom.us/j/1"}).json()
        self.assertEqual(self.c.get(f"/api/runs/{rid}").json()["status"], "interview")
        ics = self.c.get(f"/api/interviews/{iv['id']}/ics"); self.assertEqual(ics.status_code, 200)
        self.assertIn("text/calendar", ics.headers["content-type"])
        self.assertEqual(self.c.post("/api/interviews", json={"company": "X", "starts_at": "2026-10-10T10:00:00"}).status_code, 422)   # no tz
        self.assertEqual(self.c.post("/api/interviews", json={"company": "X", "starts_at": start, "link": "javascript:x"}).status_code, 422)
        up = self.c.put(f"/api/interviews/{iv['id']}", json={"status": "done"}).json(); self.assertEqual(up["status"], "done")
        dr = self.c.post(f"/api/interviews/{iv['id']}/thank-you/draft", json={}).json()
        self.assertIn("[something specific you discussed]", dr["body"])
        self.assertEqual(self.c.post(f"/api/interviews/{iv['id']}/thank-you/send", json={"body": dr["body"], "to": "a@b.co"}).status_code, 422)
        ok = self.c.post(f"/api/interviews/{iv['id']}/thank-you/send", json={"body": dr["body"].replace("[something specific you discussed]", "the platform team"),
                                                                              "to": "hr@umbrella.example"}).json()
        self.assertTrue(ok["dry_run"])
        self.assertTrue(self.c.get("/api/interviews").json()[0]["thank_you_sent_at"])
        self.c.post("/api/demo/inbox")
        sug = self.c.get("/api/inbox/m1/interview-suggestion").json()
        self.assertEqual(sug["booking_link"], "https://calendly.com/acme/intro")

    def test_offers_flow(self):
        rid = self.runs["fx-1"]["id"]
        o = self.c.post("/api/offers", json={"run_id": rid, "company": "Acme Cloud", "role": "Senior Backend Engineer", "base": 3_000_000,
                                             "bonus": 300_000, "ratings": {"growth": 5}}).json()
        self.assertEqual((o["recurring"], o["first_year"]), (3_300_000, 3_300_000))
        self.assertEqual(self.c.get(f"/api/runs/{rid}").json()["status"], "offer")
        self.assertEqual(self.c.post(f"/api/offers/{o['id']}/negotiation", json={"target_base": 2_000_000}).status_code, 422)
        n = self.c.post(f"/api/offers/{o['id']}/negotiation", json={"target_base": 3_400_000, "mention_competing": True}).json()
        self.assertIn("₹34 LPA", n["body"]); self.assertTrue(n["warnings"])
        self.assertEqual(self.c.post("/api/offers", json={"company": "X", "base": -5}).status_code, 422)
        o2 = self.c.post("/api/offers", json={"company": "Beta Labs", "base": 2_800_000}).json()
        self.assertEqual(self.c.put(f"/api/offers/{o['id']}", json={"status": "accepted"}).json()["status"], "accepted")
        self.assertEqual([x["id"] for x in self.c.get("/api/offers").json()], [o["id"], o2["id"]])   # editing keeps the column order
        self.assertIn("n", self.c.get("/api/offers/market?role=Backend").json())

    def test_practice_health_skills_progress_export_digest(self):
        rid = self.runs["fx-1"]["id"]
        self.assertEqual(self.c.post("/api/practice", json={"question": "Q?", "answer": "too short"}).status_code, 422)
        fb = self.c.post("/api/practice", json={"run_id": rid, "question": "Tell me about yourself.", "answer": "I built Kafka pipelines on AWS. " * 10}).json()
        self.assertIn("score", fb)
        self.assertEqual(len(self.c.get(f"/api/practice?run_id={rid}").json()["history"]), 1)
        h = self.c.get("/api/profile/health").json(); self.assertIn("score", h)
        before = self.c.get(f"/api/runs/{rid}").json()
        self.c.post("/api/profile/skills", json={"add": ["Splunk"]})
        after = self.c.get(f"/api/runs/{rid}").json()
        self.assertEqual(after["status"], before["status"]); self.assertIsNotNone(after["adaptation"])   # documents kept
        self.assertIn("Splunk", self.c.get("/api/profile").json()["skills"])
        self.c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"})
        self.assertEqual(len(self.c.get("/api/progress").json()["applied_at"]), 1)
        ex = self.c.get("/api/export"); self.assertEqual(ex.status_code, 200)
        data = json.loads(ex.content); self.assertTrue(data["applications"]); self.assertNotIn("GMAIL", ex.text)
        dg = self.c.post("/api/digest/send").json(); self.assertFalse(dg["sent"]); self.assertIn("preview", dg)


if __name__ == "__main__":
    unittest.main()


class Visuals(unittest.TestCase):
    def test_trends_and_breakdown(self):
        c = client()
        t = c.get("/api/trends?days=14").json()
        self.assertEqual(len(t["days"]), 14); self.assertEqual(t["days"], sorted(t["days"]))
        for k in ("found", "applied", "interviews", "offers", "outreach"):
            self.assertEqual(len(t[k]), 14)
        self.assertEqual(sum(t["found"]), len(c.get("/api/runs").json()))            # everything was found today
        self.assertEqual(c.get("/api/trends?days=3").status_code, 422)
        rid = c.get("/api/runs").json()[0]["id"]
        b = c.get(f"/api/runs/{rid}").json()["breakdown"]
        self.assertTrue(0 <= b["experience"] <= 1 and b["location"] in (0.0, 1.0)); self.assertLessEqual(b["met"], b["asked"])

    def test_score_is_unchanged_by_the_breakdown_refactor(self):
        from jobagent.agents import matcher
        from jobagent.fixtures import SAMPLE_JOBS
        j = JobListing(**{**SAMPLE_JOBS[0], "fingerprint": "x"}); reqs = matcher.parse_jd(j)
        p = matcher.score_parts(P, j, reqs)
        self.assertEqual(matcher.score(P, j, reqs), round(0.35 * p["similarity"] + 0.65 * p["coverage"], 3))

    def test_lite_list_is_small_but_keeps_what_list_screens_need(self):
        c = client()
        rid = c.get("/api/runs").json()[0]["id"]
        c.post(f"/api/runs/{rid}/tailor")
        full, lite = c.get("/api/runs").json(), c.get("/api/runs?lite=1").json()
        self.assertEqual([r["id"] for r in full], [r["id"] for r in lite])
        f0 = next(r for r in full if r["job"]["description"])
        l0 = next(r for r in lite if r["id"] == f0["id"])
        self.assertEqual((l0["job"]["description"], l0["job"]["desc_len"]), ("", len(f0["job"]["description"])))
        self.assertEqual(l0["match_score"], f0["match_score"]); self.assertEqual(l0["job"]["title"], f0["job"]["title"])
        for r in lite:
            if r.get("adaptation"):
                self.assertEqual(set(r["adaptation"]), {"matched_requirements", "missing_requirements"})
        self.assertTrue(c.get(f"/api/runs/{f0['id']}").json()["job"]["description"])            # the job panel still gets everything

    def test_pulse_changes_only_when_something_changes(self):
        c = client()
        a = c.get("/api/pulse").json()["sig"]
        self.assertEqual(a, c.get("/api/pulse").json()["sig"])
        rid = c.get("/api/runs").json()[0]["id"]
        c.put(f"/api/runs/{rid}/note", json={"starred": True})                      # notes/stars don't touch list data
        c.post("/api/clip", json={"title": "Platform Engineer", "company": "Initech", "description": "Python Kubernetes AWS Terraform. " * 6})
        self.assertNotEqual(a, c.get("/api/pulse").json()["sig"])
