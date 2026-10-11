import tempfile
import unittest
from fastapi.testclient import TestClient

from jobagent.agents import sourcing, triage
from jobagent.agents.llm_tailor import ClaudeTailorer
from jobagent.agents.matcher import parse_jd
from jobagent.agents.sourcing import passes_filters
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.orchestrator import Orchestrator
from jobagent.schemas import CandidateProfile, InboundClass, InboundEmail, JobListing, RunStatus
from tests.test_llm_tailor import FakeClient, draft
from tests.test_system import make

P = CandidateProfile(**SAMPLE_PROFILE)


def with_prefs(**kw):
    return P.model_copy(update={"preferences": {**P.preferences, **kw}})


def job(**kw):
    return JobListing(**{"id": "j", "source": "t", "url": "u", "title": "Backend Engineer", "company": "Acme",
                         "description": "Python", "remote": True, **kw})


class Filters(unittest.TestCase):
    def test_company_exclusion_and_work_modes(self):
        self.assertIn("excluded company", passes_filters(job(company="Acme Corp"), with_prefs(exclude_companies=["acme"])))
        only_remote = with_prefs(work_modes=["remote"])
        self.assertIsNone(passes_filters(job(), only_remote))
        self.assertIn("onsite", passes_filters(job(remote=False, location="Bengaluru"), only_remote))
        self.assertIn("hybrid", passes_filters(job(remote=False, description="Hybrid, 3 days in office"), only_remote))


class Autopilot(unittest.TestCase):
    def test_off_by_default_parks_at_gate(self):
        _, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], P)
        self.assertEqual(Orchestrator(ctx).start("fx-1").status, RunStatus.AWAITING_APPROVAL)

    def test_enabled_sends_only_strong_email_matches_within_cap(self):
        _, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], P)
        ctx.profile = with_prefs(autopilot={"enabled": True, "min_score": 0.5, "daily_cap": 1})
        o = Orchestrator(ctx)
        first = o.start("fx-1")                                 # strong match with apply email
        self.assertEqual(first.status, RunStatus.SUBMITTED)
        self.assertTrue(any(e["event"] == "auto_approved" for e in store.audit_log(first.id)))
        second = o.start("fx-4")                                # also has email, but daily cap reached
        self.assertEqual(second.status, RunStatus.AWAITING_APPROVAL)

    def test_no_email_never_autopilots(self):
        _, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], P)
        ctx.profile = with_prefs(autopilot={"enabled": True, "min_score": 0.5, "daily_cap": 5})
        r = Orchestrator(ctx).start("fx-2")                     # fx-2 has no apply email
        self.assertIn(r.status, (RunStatus.AWAITING_APPROVAL, RunStatus.SKIPPED))


class Tone(unittest.TestCase):
    def test_tone_reaches_prompt(self):
        c = FakeClient(draft())
        t = ClaudeTailorer(c); t.tone = "impact"
        j = job(description="Requirements\nPython\nFastAPI")
        t.tailor(P, j, parse_jd(j))
        self.assertIn("Startup-style", c.prompts[0])


class GmailInfo(unittest.TestCase):
    def e(self, **kw):
        return triage.classify(InboundEmail(**{"id": "x", "sender": "a@b.co", "subject": "", "body": "", **kw}))

    def test_company_guessing(self):
        self.assertEqual(self.e(sender="no-reply@talent.autodesk.com", subject="Aditya, we have received your application").company, "Autodesk")
        self.assertEqual(self.e(sender="gauri@messages.naukri.com", subject="Your application for AI Engineer with G2").company, "G2")
        self.assertEqual(self.e(sender="jane@gmail.com", sender_name="Jane at Rubrik", subject="hi").company, "Rubrik")
        self.assertEqual(self.e(sender="x@ey.com", subject="Thank you for applying to EY").company, "EY")

    def test_meeting_links_and_action(self):
        m = self.e(subject="Interview", body="Join https://teams.microsoft.com/l/meetup-join/abc or https://acme.zoom.us/j/123 . "
                                             "We'd like to schedule an interview.")
        self.assertEqual(len(m.calendar_links), 2)
        self.assertEqual(m.label, InboundClass.INTERVIEW)
        self.assertIn("schedule", m.action.lower())

    def test_ack_imports_external_application_and_rejection_links_to_it(self):
        _, store, _ = make()
        class R:
            def __init__(s, msgs): s.msgs = msgs
            def list_ids(s, days=14): return [m.id for m in s.msgs]
            def fetch(s, mid): return next(m for m in s.msgs if m.id == mid)
        ack = InboundEmail(id="a1", sender="x@ey.com", subject="Thank you for applying to EY", body="We have received your application.")
        rej = InboundEmail(id="a2", sender="x@ey.com", subject="Update on your EY application",
                           body="Unfortunately we will not be moving forward.")
        stats = triage.poll_inbox(store, R([ack]))
        self.assertEqual(stats["imported"], 1)
        run = store.list_runs()[0]
        self.assertEqual((run.status, run.channel.value), (RunStatus.SUBMITTED, "external"))
        triage.poll_inbox(store, R([ack, rej]))
        self.assertEqual(store.get_run(run.id).status, RunStatus.CLOSED)
        self.assertEqual(len(store.list_runs()), 1)                   # no duplicate import


class SettingsApi(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))

    def test_roundtrip_validation_and_agents(self):
        s = self.c.get("/api/settings").json()
        self.assertEqual(s["tone"], "technical"); self.assertFalse(s["autopilot"]["enabled"])
        s.update(tone="narrative", exclude_companies=["Initech"], watch_companies=["lever:acme"])
        out = self.c.put("/api/settings", json=s).json()
        self.assertEqual((out["tone"], out["exclude_companies"]), ("narrative", ["Initech"]))
        self.assertEqual(self.c.put("/api/settings", json={**s, "tone": "wild"}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings", json={**s, "watch_companies": ["evil:x"]}).status_code, 422)
        self.assertEqual(self.c.put("/api/settings", json={**s, "min_match": 3}).status_code, 422)
        a = self.c.get("/api/agents").json()
        self.assertEqual(set(a), {"sourcing", "tailoring", "triage", "dispatch"})

    def test_run_view_has_follow_up_fields(self):
        self.c.post("/api/sweep")
        r = self.c.get("/api/runs").json()[0]
        self.assertIn("follow_up_due", r); self.assertIn("emails", r)


if __name__ == "__main__":
    unittest.main()


class CompanyMatching(unittest.TestCase):
    def test_short_names_need_whole_words(self):
        from jobagent.agents.triage import same_company
        m = lambda **kw: InboundEmail(**{"id": "x", "sender": "updates@indmoney.com", "subject": "", "body": "", **kw})
        self.assertFalse(same_company("EY", m(subject="Two New IPOs Open Today", company="Indmoney")))
        self.assertTrue(same_company("EY", m(sender="x@ey.com", subject="Your EY application")))
        self.assertTrue(same_company("Rubrik", m(sender="jobs@rubrik.com", subject="Update")))
        self.assertTrue(same_company("Acme Pvt Ltd", m(company="Acme")))
        self.assertFalse(same_company("", m(subject="anything")))

    def test_subject_and_ats_domains(self):
        c = lambda **kw: triage.classify(InboundEmail(**{"id": "x", "subject": "", "body": "", **kw})).company
        self.assertEqual(c(sender="a@gsconsulting.in", subject="Your application to [United Airlines]"), "United Airlines")
        self.assertEqual(c(sender="x@fa.oraclecloud.com", sender_name="Pearson Talent Acquisition",
                           subject="Your recent job application for Specialist"), "Pearson")


class MoreImports(unittest.TestCase):
    def test_recruiter_subject_company_and_rejection_import(self):
        c = triage.classify(InboundEmail(id="x", sender="a@careernet.in", sender_name="Aayushi Singh (Careernet)",
                                         subject="Job Opportunity for Cashfree Payments_ Security Engineer", body=""))
        self.assertEqual(c.company, "Cashfree Payments")
        _, store, _ = make()
        class R:
            def list_ids(s, days=14): return ["r"]
            def fetch(s, mid): return InboundEmail(id="r", sender="a@gsconsulting.in", subject="Your application to [United Airlines]",
                                                   body="Unfortunately we are not moving forward.")
        triage.poll_inbox(store, R())
        self.assertEqual(store.list_runs()[0].status, RunStatus.CLOSED)


class CoverAndUi(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        self.c.post("/api/sweep")

    def test_save_cover_letter(self):
        rid = self.c.get("/api/runs?status=awaiting_approval").json()[0]["id"]
        self.assertEqual(self.c.put(f"/api/runs/{rid}/cover", json={"cover_letter": "New text"}).status_code, 200)
        self.assertEqual(self.c.get(f"/api/runs/{rid}").json()["adaptation"]["cover_letter"], "New text")
        self.assertEqual(self.c.put(f"/api/runs/{rid}/cover", json={"cover_letter": "  "}).status_code, 422)

    def test_skipped_job_can_be_tailored_on_request(self):
        rid = next(r["id"] for r in self.c.get("/api/runs").json() if r["status"] == "skipped")
        self.assertEqual(self.c.post(f"/api/runs/{rid}/regenerate", json={}).json()["status"], "awaiting_approval")

    def test_ui_assets_served(self):
        self.assertIn("/static/app.js", self.c.get("/").text)
        self.assertEqual(self.c.get("/static/app.js").status_code, 200)
        self.assertEqual(self.c.get("/static/deck.css").status_code, 200)


class RoleTitles(unittest.TestCase):
    def t(self, subject, body):
        return triage.role_title(InboundEmail(id="x", sender="a@b.co", subject=subject, body=body))

    def test_titles_from_subject_and_body(self):
        self.assertEqual(self.t("Aditya, we have received your application",
                                "Hello Aditya, We're thrilled to have received your application for Principal Network Security Engineer, and are excited"),
                         "Principal Network Security Engineer")
        self.assertEqual(self.t("Thank you for applying to EY", "Thank you for your interest in EY and the SIEM Security Engineer role. We are"),
                         "SIEM Security Engineer")
        self.assertEqual(self.t("Your recent job application for Specialist, Application Security - 24964", ""),
                         "Specialist, Application Security - 24964")
        self.assertEqual(self.t("Thanks", "Thank you for your interest in the position."), "")


class LiveRefilter(unittest.TestCase):
    """Saving preferences must change jobs already in the list, not only future searches."""
    def setUp(self):
        d = tempfile.mkdtemp()
        from jobagent.fixtures import SAMPLE_JOBS
        jobs = [dict(j) for j in SAMPLE_JOBS]
        jobs[0]["description"] += "\nSalary ₹6L - ₹8L"            # fx-1: known low salary
        jobs[3]["description"] += "\nSalary ₹25L - ₹40L"          # fx-4: known high salary

        class Src:
            name = "t"
            def fetch(self_):
                from jobagent.text import fingerprint
                return [JobListing(**{**j, "fingerprint": fingerprint(j["title"], j["company"], j.get("location", ""))}) for j in jobs]
        self.c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [Src()]))
        self.c.post("/api/sweep")

    def status(self, jid):
        return next(r for r in self.c.get("/api/runs").json() if r["job"]["id"] == jid)

    def save(self, **kw):
        s = self.c.get("/api/settings").json(); s.update(kw)
        out = self.c.put("/api/settings", json=s).json()
        self.assertNotIn("_applied", self.c.get("/api/settings").json())      # response-only key never stored
        return out["_applied"]

    def test_min_salary_hides_then_restores(self):
        self.assertEqual(self.status("fx-1")["status"], "awaiting_approval")
        applied = self.save(min_salary_lpa=10)
        self.assertEqual(applied.get("hidden"), 1)
        r = self.status("fx-1")
        self.assertEqual(r["status"], "filtered"); self.assertIn("salary below 10", r["last_error"])
        self.assertEqual(self.status("fx-4")["status"], "awaiting_approval")   # high salary stays
        self.assertNotEqual(self.status("fx-2")["status"], "filtered")         # unknown salary is kept
        applied = self.save(min_salary_lpa=0)
        self.assertEqual(applied.get("restored"), 1)
        r = self.status("fx-1")
        self.assertEqual(r["status"], "awaiting_approval"); self.assertIsNotNone(r["adaptation"])   # documents kept

    def test_company_exclusion_and_threshold_apply_immediately(self):
        self.save(exclude_companies=["Acme"])
        self.assertEqual(self.status("fx-1")["status"], "filtered")
        self.save(exclude_companies=[], min_match=0.0)
        self.assertEqual(self.status("fx-3")["status"], "scored")               # was a low match, now shown as new
        self.save(min_match=0.95)
        self.assertEqual(self.status("fx-3")["status"], "skipped")

    def test_sent_applications_are_never_touched(self):
        rid = self.status("fx-1")["id"]
        self.c.post(f"/api/runs/{rid}/decision", json={"decision": "approve"})
        self.save(min_salary_lpa=50, exclude_companies=["Acme"])
        self.assertEqual(self.status("fx-1")["status"], "submitted")


class AutoPrepareCount(unittest.TestCase):
    def test_only_best_n_prepared_without_a_model_too(self):
        d = tempfile.mkdtemp()
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        s = c.get("/api/settings").json(); s["auto_tailor_top"] = 1; c.put("/api/settings", json=s)
        c.post("/api/sweep")
        runs = c.get("/api/runs").json()
        self.assertEqual(sum(r["status"] == "awaiting_approval" for r in runs), 1)
        self.assertGreaterEqual(sum(r["status"] == "scored" for r in runs), 1)
        best = max((r for r in runs if r["status"] in ("scored", "awaiting_approval")), key=lambda r: r["match_score"])
        self.assertEqual(best["status"], "awaiting_approval")                  # the prepared one is the best match
