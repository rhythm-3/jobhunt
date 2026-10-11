import tempfile
import unittest
from fastapi.testclient import TestClient

from jobagent.agents.formfill import classify_field, profile_values
from jobagent.app import build_app
from jobagent.agents import sourcing
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile


class Classify(unittest.TestCase):
    def test_standard_fields(self):
        cases = {"First Name": "first_name", "Last name *": "last_name", "Email address": "email", "E-mail": "email",
                 "Phone number": "phone", "Mobile": "phone", "LinkedIn Profile URL": "linkedin",
                 "Full name": "full_name", "Name": "full_name", "Current location": "location", "City": "location",
                 "Your first_name": "first_name"}
        for label, key in cases.items():
            self.assertEqual(classify_field(label), key, label)

    def test_sensitive_and_unknown_fields_are_never_filled(self):
        for label in ["Current company", "Expected salary", "Are you authorized to work in the US?",
                      "Will you require visa sponsorship", "Gender", "Race / Ethnicity", "Veteran status",
                      "Notice period", "Current CTC", "Password", "Date of birth", "How did you hear about us",
                      "Why do you want to work here?", "University name", "Referral name", "Years of experience"]:
            self.assertIsNone(classify_field(label), label)

    def test_type_gates(self):
        self.assertIsNone(classify_field("Email", "checkbox"))
        self.assertIsNone(classify_field("Email", "hidden"))
        self.assertIsNone(classify_field("Resume", "file"))
        self.assertEqual(classify_field("Cover letter", "text", "textarea"), "cover_letter")
        self.assertIsNone(classify_field("Anything else we should know?", "text", "textarea"))

    def test_profile_values(self):
        v = profile_values(CandidateProfile(**{**SAMPLE_PROFILE, "links": ["linkedin.com/in/x"]}))
        self.assertEqual((v["first_name"], v["last_name"]), ("Alex", "Morgan"))
        self.assertEqual(v["linkedin"], "https://www.linkedin.com/in/x")


class Endpoints(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.launched = []
        self.c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()],
                                      launcher=self.launched.append))
        self.c.post("/api/sweep")
        self.runs = {r["job"]["id"]: r for r in self.c.get("/api/runs").json()}

    def test_no_email_job_goes_to_manual_then_assisted_flow(self):
        rid = self.runs["fx-2"]["id"]                   # fx-2 has no apply email
        self.assertEqual(self.c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"}).json()["status"], "needs_manual")
        self.assertEqual(self.c.post(f"/api/runs/{rid}/open-form").status_code, 200)
        self.assertEqual(self.launched, [rid])
        self.assertEqual(self.c.post(f"/api/runs/{rid}/manual", json={"outcome": "applied"}).status_code, 422)   # must confirm
        out = self.c.post(f"/api/runs/{rid}/manual", json={"outcome": "applied", "confirmed": True}).json()
        self.assertEqual((out["status"], out["channel"]), ("submitted", "form"))
        self.assertEqual(self.c.post(f"/api/runs/{rid}/manual", json={"outcome": "applied", "confirmed": True}).status_code, 409)

    def test_drop_and_validation(self):
        rid = self.runs["fx-2"]["id"]
        self.c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"})
        self.assertEqual(self.c.post(f"/api/runs/{rid}/manual", json={"outcome": "x"}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/runs/{rid}/manual", json={"outcome": "dropped"}).json()["status"], "closed")

    def test_cannot_open_form_for_submitted_or_skipped(self):
        skipped = next(r for r in self.runs.values() if r["status"] == "skipped")
        self.assertEqual(self.c.post(f"/api/runs/{skipped['id']}/open-form").status_code, 409)
        self.assertEqual(self.launched, [])


if __name__ == "__main__":
    unittest.main()


class JobBoardsNeverAutomated(unittest.TestCase):
    def test_glassdoor_linkedin_naukri_open_in_users_browser(self):
        import tempfile
        from jobagent.schemas import JobListing
        d = tempfile.mkdtemp(); launched = []
        class Src:
            name = "t"
            def fetch(self_):
                return [JobListing(id=f"b{i}", source="glassdoor", url=u, title="Security Engineer", company=f"C{i}", description="Python",
                                   remote=True, fingerprint=f"f{i}") for i, u in enumerate(
                    ["https://www.glassdoor.co.in/partner/jobListing.htm?x=1", "https://www.linkedin.com/jobs/view/1/", "https://boards.greenhouse.io/acme/jobs/1"])]
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [Src()], launcher=launched.append))
        c.post("/api/sweep")
        modes = {}
        for r in c.get("/api/runs").json():
            c.post(f"/api/runs/{r['id']}/regenerate", json={}) if r["status"] != "awaiting_approval" else None
            modes[r["job"]["url"].split("/")[2]] = c.post(f"/api/runs/{r['id']}/open-form").json()["mode"]
        self.assertEqual(modes["www.glassdoor.co.in"], "browser")
        self.assertEqual(modes["www.linkedin.com"], "browser")
        self.assertEqual(modes["boards.greenhouse.io"], "prefill")
