import tempfile
import unittest
from datetime import date

from fastapi.testclient import TestClient

from jobagent.agents import documents, market, matcher, outreach, sourcing
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_JOBS, SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile, Experience, JobListing

P = CandidateProfile(**SAMPLE_PROFILE)


def J(desc, title="Backend Engineer", **kw):
    return JobListing(id="j", source="t", url="", title=title, company="Acme", description=desc, fingerprint="f", **kw)


def V(job, p=P, why=None, salary=None):
    reqs = matcher.parse_jd(job)
    return market.verdict(p, job, reqs, matcher.score_parts(p, job, reqs), matcher.score(p, job, reqs), why, salary)


class Verdict(unittest.TestCase):
    def test_years(self):
        p = P.model_copy(update={"experience": [Experience(company="A", title="Engineer", start="Jan 2022", end="Jan 2024", bullets=["x"]),
                                                Experience(company="B", title="Engineer", start="Jul 2023", end="Present", bullets=["y"])]})
        self.assertEqual(market.years_of_experience(p, date(2026, 1, 15)), 4.1)          # overlap counted once
        self.assertEqual(market.years_asked("Requires 5+ years of Python. We are a 20 year old company."), 5)
        self.assertEqual(market.years_asked("3-5 years experience; 8 yrs preferred"), 3)
        self.assertIsNone(market.years_asked("Great team"))

    def test_calls(self):
        skills = " ".join(P.skills[:6])
        good = V(J(f"Requirements: {skills}. " * 6))
        self.assertEqual(good["call"], "apply"); self.assertTrue(good["strengths"]); self.assertFalse(good["blockers"])
        years = market.years_of_experience(P)
        far = V(J(f"Requirements: {skills}. {int(years) + 6}+ years of experience required. " * 4))
        self.assertEqual(far["call"], "skip"); self.assertIn("years", far["blockers"][0])
        self.assertEqual(V(J("Requirements: " + skills + ". " * 5), why="on-site outside targets: Paris")["call"], "skip")
        poor = V(J("Requirements: Kotlin, Django, Flask, Ansible, Jenkins, Golang and Azure for our lovely team and world. " * 5))
        self.assertEqual(poor["call"], "skip"); self.assertIn("Not in your profile", " ".join(poor["cautions"]))
        self.assertNotIn("World", " ".join(poor["cautions"])); self.assertNotIn("Team", " ".join(poor["cautions"]))   # everyday words aren't "requirements"


class ExperienceWeight(unittest.TestCase):
    BODY = "Requirements: " + ", ".join(P.skills[:6]) + ". You will build and run services. "

    def test_fit_meets_or_falls_by_the_missing_year(self):
        have = market.years_of_experience(P)
        meets = matcher.experience_fit(P, J(self.BODY + f"{int(have)}+ years of experience."))
        self.assertEqual((meets["asked"], meets["fit"]), (int(have), 1.0))
        far = matcher.experience_fit(P, J(self.BODY + f"{int(have) + 4}+ years of experience."))
        self.assertAlmostEqual(far["fit"], round(1 - 0.18 * (int(have) + 4 - have), 2))
        self.assertIsNone(matcher.experience_fit(P, J(self.BODY))["fit"])                # nothing stated: it doesn't count

    def test_experience_is_the_heaviest_part_of_the_score(self):
        have = int(market.years_of_experience(P))
        ok, steep = J(self.BODY * 3 + f"{have}+ years."), J(self.BODY * 3 + f"{have + 9}+ years.")        # same wording and skills
        so, ss = matcher.score(P, ok, matcher.parse_jd(ok)), matcher.score(P, steep, matcher.parse_jd(steep))
        self.assertGreater(so - ss, 0.3)                      # a 9-year gap costs most of the 45% weight
        reqs = matcher.parse_jd(ok); x = matcher.experience_fit(P, ok); parts = matcher.score_parts(P, ok, reqs)
        self.assertEqual(so, round(0.45 * x["fit"] + 0.35 * parts["coverage"] + 0.20 * parts["similarity"], 3))

    def test_lite_runs_carry_it_for_sorting(self):
        c = client(); c.post("/api/clip", json={"title": "Platform Engineer", "company": "Initech", "location": "Remote", "description": self.BODY * 3 + "6+ years of experience."})
        runs = c.get("/api/runs?lite=1").json()
        self.assertTrue(all("exp" in r for r in runs if r.get("job")))
        r = next(r for r in runs if r["exp"]["asked"] is not None); self.assertEqual(r["exp"]["asked"], 6)
        self.assertEqual(set(r["exp"]), {"asked", "have", "fit"})
        d = c.get(f"/api/runs/{r['id']}").json()
        self.assertEqual(d["breakdown"]["years"]["asked"], r["exp"]["asked"])


class Keywords(unittest.TestCase):
    def test_have_missing_and_where(self):
        j = J(f"Requirements: {P.skills[0]}, {P.skills[1]}, Kotlin and Django. Join our passionate team and change the world. " * 3)
        r = market.keyword_report(P, j, matcher.parse_jd(j))
        have, missing = {x["key"] for x in r["have"]}, {x["key"] for x in r["missing"]}
        self.assertTrue({"kotlin", "django"} <= missing); self.assertFalse(have & missing)
        self.assertFalse({"passionate", "team", "world", "join"} & (have | missing))                  # only real skills and technical terms
        self.assertTrue(all(x["where"] for x in r["have"])); self.assertTrue(0 < r["coverage"] < 1)
        self.assertEqual(r["total"], len(r["have"]) + len(r["missing"]))


class LinkedIn(unittest.TestCase):
    def test_review_scores_and_rewrites_only_from_the_profile(self):
        demand = [{"skill": s.lower(), "have": True} for s in P.skills[:6]]
        weak = market.linkedin_review(P, "Aspiring engineer seeking opportunities", "", [], demand, ["engineer"])
        self.assertLess(weak["score"], 40); self.assertTrue(weak["add_skills"])
        self.assertEqual(outreach.ungrounded(weak["headline"] + " " + weak["about"], P), [])         # no invented tools or numbers
        self.assertIn(P.email, weak["about"])
        strong = market.linkedin_review(P, weak["headline"], weak["about"], P.skills + ["x"] * 10, demand, ["engineer"])
        self.assertGreater(strong["score"], weak["score"] + 30)


def client():
    d = tempfile.mkdtemp()
    c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
    c.post("/api/sweep")
    return c


class Api(unittest.TestCase):
    def setUp(self):
        self.c = client()
        self.runs = self.c.get("/api/runs").json()

    def fresh_job(self):
        """A matched job that hasn't been prepared yet."""
        r = self.c.post("/api/clip", json={"title": "Platform Engineer", "company": "Initech", "location": "Remote",
                                           "description": "Requirements: " + ", ".join(P.skills[:6]) + ". You will build and run services. " * 4}).json()
        self.assertEqual(r["status"], "scored", r)
        return r["run_id"]

    def test_run_detail_has_verdict_and_keywords(self):
        d = self.c.get(f"/api/runs/{self.runs[0]['id']}").json()
        self.assertIn(d["verdict"]["call"], ("apply", "maybe", "skip")); self.assertIn("coverage", d["keywords"])
        self.assertEqual(d["profile_version"], "")

    def test_job_insights_are_one_grounded_sentence_each(self):
        ids = [r["id"] for r in self.runs[:3]]
        out = self.c.get("/api/insights/jobs?ids=" + ",".join(ids + ["nope"])).json()
        self.assertEqual(set(out), set(ids))                                       # unknown ids are skipped
        d = self.c.get(f"/api/runs/{ids[0]}").json()["verdict"]
        self.assertEqual(out[ids[0]]["call"], d["call"]); self.assertTrue(out[ids[0]]["line"].startswith(d["why"]))
        self.assertEqual(self.c.get("/api/insights/jobs?ids=" + ",".join(ids)).json(), out)    # cached, same answer

    def test_salary_explorer(self):
        for i, (lo, hi, city) in enumerate([(10, 14, "Bengaluru"), (18, 22, "Bangalore, India"), (30, 40, "Pune"), (8, 12, "Remote")]):
            self.c.post("/api/clip", json={"title": f"Backend Engineer {i}", "company": f"Co{i}", "location": city,
                                           "description": f"Salary: ₹{lo}-{hi} LPA. Python, AWS and Postgres backend role with ownership. " * 3})
        s = self.c.get("/api/salary?role=backend").json()
        self.assertEqual(s["n"], 4); self.assertEqual((s["low"], s["high"]), (10, 35)); self.assertTrue(s["low"] <= s["p25"] <= s["median"] <= s["p75"] <= s["high"])
        self.assertEqual(next(c for c in s["cities"] if c["city"] == "Bengaluru")["n"], 2)             # Bangalore and Bengaluru are one city
        one = self.c.get("/api/salary?role=backend&city=Pune").json()
        self.assertEqual(one["n"], 1); self.assertNotIn("median", one)                                # too few to quote a range
        self.assertEqual(self.c.get("/api/salary?role=zzzz").json()["n"], 0); self.assertEqual(len(s["links"]), 3)

    def test_contacts(self):
        a = self.c.post("/api/contacts", json={"name": "Priya Sharma", "company": "Acme", "relationship": "referrer", "next_follow_up": "2020-01-01", "referral": "asked"}).json()
        b = self.c.post("/api/contacts", json={"name": "Sam Lee", "company": "Zed", "next_follow_up": "2999-01-01"}).json()
        self.assertTrue(a["due"]); self.assertFalse(b["due"])
        self.assertEqual(self.c.post("/api/contacts", json={"name": "X", "email": "bad"}).status_code, 422)
        self.assertEqual(self.c.post("/api/contacts", json={"name": "X", "last_contact": "yesterday"}).status_code, 422)
        self.assertEqual(self.c.put(f"/api/contacts/{a['id']}", json={"referral": "submitted"}).json()["referral"], "submitted")
        self.assertEqual([c["name"] for c in self.c.get("/api/contacts").json()], ["Priya Sharma", "Sam Lee"])
        self.c.delete(f"/api/contacts/{b['id']}"); self.assertEqual(len(self.c.get("/api/contacts").json()), 1)

    def test_resume_versions_switch_and_per_job(self):
        v1 = self.c.post("/api/profile/versions", json={"name": "Backend"}).json()
        self.assertEqual(len(v1["versions"]), 1); self.assertEqual(v1["active"], v1["versions"][0]["id"])
        self.assertEqual(self.c.post("/api/profile/versions", json={"name": "backend"}).status_code, 409)
        self.assertEqual(self.c.post("/api/profile/versions", json={"name": ""}).status_code, 422)
        prof = self.c.get("/api/profile").json()
        prof["summary"] = "Full-stack engineer who ships product end to end."; prof["full_name"] = "Alex Morgan"
        self.assertEqual(self.c.put("/api/profile", json=prof).status_code, 200)
        v2 = self.c.post("/api/profile/versions", json={"name": "Full-stack"}).json()
        b_id, f_id = v2["versions"][0]["id"], v2["versions"][1]["id"]
        self.assertEqual(self.c.delete(f"/api/profile/versions/{f_id}").status_code, 409)             # can't delete the one in use
        back = self.c.post(f"/api/profile/versions/{b_id}/activate").json()
        self.assertEqual(back["active"], b_id); self.assertIn("rescored", back)
        self.assertNotIn("Full-stack engineer", self.c.get("/api/profile").json()["summary"])
        # one job uses the other version without switching
        rid = self.fresh_job()
        self.assertEqual(self.c.put(f"/api/runs/{rid}/version", json={"version": "nope"}).status_code, 404)
        self.c.put(f"/api/runs/{rid}/version", json={"version": f_id})
        self.c.post(f"/api/runs/{rid}/tailor")
        d = self.c.get(f"/api/runs/{rid}").json()
        self.assertEqual(d["profile_version"], f_id); self.assertIn("Full-stack engineer", d["adaptation"]["tailored_summary"])
        self.assertEqual(self.c.delete(f"/api/profile/versions/{f_id}").status_code, 200)

    def test_templates_preview_and_setting(self):
        t = self.c.get("/api/resume/templates").json()
        self.assertEqual(t["active"], "classic"); self.assertEqual(len(t["templates"]), 4)
        self.assertIn("Georgia", self.c.get("/api/resume/preview?template=elegant").text)
        self.assertEqual(self.c.get("/api/resume/preview?template=nope").status_code, 404)
        self.c.put("/api/settings", json={**self.c.get("/api/settings").json(), "resume_template": "modern"})
        rid = self.fresh_job()
        self.c.post(f"/api/runs/{rid}/tailor")
        self.assertIn("0b5c8a", self.c.get(f"/api/runs/{rid}").json()["resume_html"])                # the prepared resume uses it
        self.assertEqual(self.c.put("/api/settings", json={**self.c.get("/api/settings").json(), "resume_template": "comic"}).status_code, 422)
        for name, (_, css) in documents.TEMPLATES.items():
            self.assertNotIn("table", css); self.assertNotIn("column", css, name)                    # one column, no tables: ATS-safe

    def test_dismiss_and_restore(self):
        rid = self.fresh_job()
        self.assertEqual(self.c.post(f"/api/runs/{rid}/dismiss").json()["status"], "rejected")
        self.assertEqual(self.c.post(f"/api/runs/{rid}/dismiss").status_code, 409)
        self.assertEqual(self.c.post(f"/api/runs/{rid}/restore").json()["status"], "scored")
        sent = next(r["id"] for r in self.c.get("/api/runs").json() if r["status"] == "awaiting_approval")
        self.assertEqual(self.c.post(f"/api/runs/{sent}/dismiss").status_code, 409)                  # prepared work is never thrown away here

    def test_autofill_never_exposes_sensitive_answers(self):
        a = self.c.get("/api/autofill").json()
        self.assertEqual(set(a["values"]), {"email", "phone", "first_name", "last_name", "full_name", "linkedin", "location", "website",
                                            "current_company", "current_title"})
        self.assertTrue(a["values"]["email"])


if __name__ == "__main__":
    unittest.main()
