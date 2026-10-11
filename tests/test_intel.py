"""OSINT module with the network mocked: deterministic and offline."""
import json
import tempfile
import unittest
from unittest import mock

from jobagent.agents import intel
from jobagent.db import Store
from jobagent.schemas import JobListing


def J(title, desc="x" * 400, company="Acme", url="https://boards.greenhouse.io/acme/jobs/1", loc="Bengaluru, India"):
    return JobListing(id=title, source="greenhouse:acme", url=url, title=title, company=company, location=loc, description=desc)


class FullDescription(unittest.TestCase):
    def test_matches_same_role_on_company_board(self):
        board = [J("Senior Security Engineer, Detection"), J("Account Executive"), J("Security Engineer - Detection & Response")]
        thin = JobListing(id="g", source="glassdoor", url="https://www.glassdoor.co.in/x", title="Security Engineer Detection & Response",
                          company="Acme", description="Security Engineer\nAcme\nBengaluru")
        with mock.patch.object(intel.GreenhouseSource, "fetch", return_value=board), \
             mock.patch.object(intel.LeverSource, "fetch", side_effect=OSError), \
             mock.patch.object(intel.AshbySource, "fetch", side_effect=OSError), \
             mock.patch.object(intel.SmartRecruitersSource, "fetch", side_effect=OSError):
            hit = intel.find_full_description(thin)
        self.assertEqual(hit["url"], "https://boards.greenhouse.io/acme/jobs/1"); self.assertGreaterEqual(hit["similarity"], 0.85)

    def test_rejects_weak_matches(self):
        thin = JobListing(id="g", source="glassdoor", url="u", title="Payroll Specialist", company="Acme", description="short")
        with mock.patch.object(intel.GreenhouseSource, "fetch", return_value=[J("Security Engineer")]), \
             mock.patch.object(intel.LeverSource, "fetch", side_effect=OSError), mock.patch.object(intel.AshbySource, "fetch", side_effect=OSError), \
             mock.patch.object(intel.SmartRecruitersSource, "fetch", side_effect=OSError), mock.patch.object(intel.HimalayasSource, "fetch", return_value=[]):
            self.assertIsNone(intel.find_full_description(thin))

    def test_slugs(self):
        self.assertEqual(intel.slug_candidates("Deutsche Bank", "db.com")[:3], ["db", "deutschebank", "deutsche-bank"])
        self.assertEqual(intel.norm("Rubrik, Inc."), "rubrik")


class Signals(unittest.TestCase):
    def test_email_and_web_signals_parsed(self):
        dns = {("acme.com", "MX"): ["10 aspmx.l.google.com."], ("acme.com", "TXT"): ["v=spf1 include:_spf.google.com include:sendgrid.net ~all"],
               ("_dmarc.acme.com", "TXT"): ["v=DMARC1; p=quarantine; rua=mailto:x@acme.com"]}
        def get(url, timeout=10, head=False):
            if url.endswith("security.txt"):
                return 200, {}, b"Contact: mailto:security@acme.com"
            return 200, {"Strict-Transport-Security": "max-age=1", "Server": "cloudflare"}, b"<script src=/_next/x.js></script>"
        with mock.patch.object(intel, "_dns", side_effect=lambda n, t: dns.get((n, t), [])), mock.patch.object(intel, "_get", side_effect=get):
            s = intel.security_signals("acme.com")
        self.assertEqual((s["mail"], s["dmarc"], s["spf"], s["hsts"], s["security_txt"]), ("Google Workspace", "quarantine", True, True, True))
        self.assertEqual(s["spf_services"], ["Google", "SendGrid"]); self.assertIn("Next.js", s["stack"]); self.assertIn("Cloudflare", s["stack"])

    def test_missing_dmarc(self):
        with mock.patch.object(intel, "_dns", return_value=[]), mock.patch.object(intel, "_get", side_effect=OSError):
            s = intel.security_signals("nomail.example")
        self.assertEqual((s["mail"], s["dmarc"], s["security_txt"]), ("none found", "missing", None))   # couldn't check != "no"


class Cache(unittest.TestCase):
    def test_company_intel_cached_and_domain_remembered(self):
        store = Store(tempfile.mkdtemp() + "/c.db")
        calls = []
        with mock.patch.object(intel, "identity", side_effect=lambda c: calls.append(c) or {"domain": "acme.com"}), \
             mock.patch.object(intel, "wiki", return_value={}), mock.patch.object(intel, "security_signals", return_value={"dmarc": "reject"}), \
             mock.patch.object(intel, "github_org", return_value={}), mock.patch.object(intel, "news", return_value=[]), \
             mock.patch.object(intel, "hiring", return_value={"open_roles": 3}):
            a = intel.company_intel(store, "Acme Inc"); b = intel.company_intel(store, "Acme Inc")
        self.assertEqual(len(calls), 1); self.assertEqual(a["security"]["dmarc"], "reject")
        self.assertEqual(store.kv_get("domain:acme"), "acme.com")


class Api(unittest.TestCase):
    def test_research_endpoint_enriches_and_rescores(self):
        from fastapi.testclient import TestClient
        from jobagent.agents import sourcing
        from jobagent.app import build_app
        from jobagent.config import Settings
        d = tempfile.mkdtemp()
        thin = JobListing(id="g1", source="glassdoor", url="https://www.glassdoor.co.in/x", title="Backend Engineer", company="Acme",
                          remote=True, description="Backend Engineer\nAcme", fingerprint="g1")
        class Src:
            name = "t"
            def fetch(self): return [thin]
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [Src()]))
        c.post("/api/sweep")
        rid = c.get("/api/runs").json()[0]["id"]
        full = {"description": "Requirements\nPython and FastAPI\nPostgreSQL and Redis\nKafka\nAWS and Docker\n" * 3,
                "url": "https://boards.greenhouse.io/acme/jobs/9", "source": "greenhouse:acme", "similarity": 1.0}
        with mock.patch("jobagent.agents.intel.find_full_description", return_value=full), \
             mock.patch("jobagent.agents.intel.company_intel", return_value={"company": "Acme"}):
            out = c.post(f"/api/runs/{rid}/research").json()
        self.assertTrue(out["jd"]["found"]); self.assertGreater(out["jd"]["score_after"], out["jd"]["score_before"])
        run = c.get(f"/api/runs/{rid}").json()
        self.assertEqual(run["job"]["apply_url"], "https://boards.greenhouse.io/acme/jobs/9")
        self.assertEqual(run["job"]["enriched_from"], "greenhouse:acme")
        self.assertEqual(c.get("/api/companies").json()[0]["company"], "Acme")


if __name__ == "__main__":
    unittest.main()


class FromLink(unittest.TestCase):
    def test_refuses_account_job_boards(self):
        for u in ("https://www.linkedin.com/jobs/view/1", "https://www.glassdoor.co.in/job-listing/x", "https://www.naukri.com/job-listings-x"):
            with self.assertRaises(ValueError):
                intel.description_from_link(u)

    def test_jsonld_jobposting_extraction(self):
        page = b"""<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"X"},
          {"@type":"JobPosting","title":"Detection Engineer","description":"&lt;p&gt;Build Splunk detections with Python&lt;/p&gt;",
           "hiringOrganization":{"@type":"Organization","name":"Acme"},"jobLocation":{"@type":"Place","address":{"addressLocality":"Pune","addressCountry":"IN"}}}]}</script></html>"""
        with mock.patch.object(intel, "_get", return_value=(200, {}, page)):
            d = intel.description_from_link("https://careers.acme.com/jobs/123")
        self.assertEqual((d["title"], d["company"], d["location"], d["source"]), ("Detection Engineer", "Acme", "Pune, IN", "link:careers.acme.com"))
        self.assertIn("Splunk detections", d["description"])

    def test_workday_uses_public_job_api(self):
        seen = []
        def fake(url, timeout=10):
            seen.append(url)
            return {"jobPostingInfo": {"title": "SOC Analyst", "jobDescription": "<p>Monitor SIEM</p>", "location": "Bengaluru"}}
        with mock.patch.object(intel, "_json", side_effect=fake):
            d = intel.description_from_link("https://dxctechnology.wd1.myworkdayjobs.com/en-US/DXCJobs/job/Bangalore/SOC-Analyst_52000")
        self.assertEqual(seen[0], "https://dxctechnology.wd1.myworkdayjobs.com/wday/cxs/dxctechnology/DXCJobs/job/Bangalore/SOC-Analyst_52000")
        self.assertEqual((d["title"], d["source"]), ("SOC Analyst", "workday:dxctechnology"))
