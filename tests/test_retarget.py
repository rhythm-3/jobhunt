import tempfile
import unittest

from fastapi.testclient import TestClient

from jobagent.agents import retarget as rt, sourcing
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile, Experience

BASE = CandidateProfile(**SAMPLE_PROFILE)


def P(title, summary, skills, extra_titles=()):
    exp = [Experience(company="A", title=title, start="Jan 2024", end="Present", bullets=["Did the work well"])]
    exp += [Experience(company=f"B{i}", title=t, start="Jan 2022", end="Dec 2023", bullets=["Did more work"]) for i, t in enumerate(extra_titles)]
    return BASE.model_copy(update={"experience": exp, "summary": summary, "skills": skills, "preferences": {}})


SEC = P("Cybersecurity Engineer 1 — Detection Engineering", "Security engineer automating SOC triage and incident response.", ["Splunk", "SOAR", "Python"], ["Cybersecurity Intern"])
SW = P("Software Engineer – Associate", "Software engineer with backend and full-stack experience.", ["Python", "Java", "React"])
DATA = P("Data Scientist", "Data scientist building machine learning models and analytics.", ["Python", "SQL", "Pandas"])


class Titles(unittest.TestCase):
    def test_field_and_titles_follow_the_resume(self):
        self.assertEqual(rt.search_titles(SEC), (["security", "detection", "soc", "threat", "incident"], "security"))
        t, f = rt.search_titles(SW); self.assertEqual(f, "software"); self.assertIn("developer", t)
        self.assertEqual(rt.search_titles(DATA)[1], "data")
        odd = P("Senior Florist", "I arrange flowers.", ["Roses"])
        self.assertEqual(rt.search_titles(odd), (["florist"], "general"))                    # unknown field: the title's own words

    def test_when_to_retarget(self):
        self.assertTrue(rt.needs_retarget(SEC, ["python", "software", "developer"], SW))      # resume changed field
        self.assertTrue(rt.needs_retarget(SW, [], None))                                      # nothing set yet
        self.assertFalse(rt.needs_retarget(SEC, ["security", "soar"], SEC))                   # your own titles for this field are kept
        self.assertFalse(rt.needs_retarget(SEC, ["detection engineer"], SEC))
        self.assertTrue(rt.needs_retarget(SW, ["security"], SW))                              # titles describe nothing in this resume

    def test_skill_groups_are_split(self):
        s = rt.split_skill_groups(["Security Operations: SOAR Engineering, Incident Response, Alert Triage", "Development: Python, REST APIs",
                                   "Compliance & Frameworks: MITRE ATT&CK", "Python", "Kubernetes"])
        self.assertEqual(s, ["SOAR Engineering", "Incident Response", "Alert Triage", "Python", "REST APIs", "Compliance & Frameworks: MITRE ATT&CK", "Kubernetes"])
        self.assertEqual(rt.split_skill_groups(["C++", "Node.js: the runtime"]), ["C++", "Node.js: the runtime"])   # ordinary skills untouched


class Api(unittest.TestCase):
    def test_saving_a_different_resume_moves_the_search(self):
        d = tempfile.mkdtemp()
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        c.post("/api/sweep")
        c.put("/api/settings", json={**c.get("/api/settings").json(), "target_titles": ["python", "software", "developer"], "min_salary_lpa": 12})
        body = {**SEC.model_dump(mode="json"), "skills": ["Security Operations: Splunk, SOAR, Incident Response", "Python"]}
        body.pop("preferences")
        out = c.put("/api/profile", json=body).json()
        self.assertEqual(out["retargeted"]["to"][0], "security"); self.assertEqual(out["retargeted"]["from"], ["python", "software", "developer"])
        s = c.get("/api/settings").json()
        self.assertEqual(s["target_titles"][:2], ["security", "detection"]); self.assertEqual(s["min_salary_lpa"], 12)   # other settings untouched
        self.assertEqual(out["profile"]["skills"], ["Splunk", "SOAR", "Incident Response", "Python"])
        # editing the same resume again does not overwrite titles you then choose yourself
        c.put("/api/settings", json={**s, "target_titles": ["detection engineer"]})
        again = c.put("/api/profile", json={**body, "summary": SEC.summary + " Also threat hunting."}).json()
        self.assertIsNone(again["retargeted"]); self.assertEqual(c.get("/api/settings").json()["target_titles"], ["detection engineer"])


if __name__ == "__main__":
    unittest.main()
