import tempfile
import unittest
from fastapi.testclient import TestClient

from jobagent.agents import notify, sourcing, triage
from jobagent.agents.dispatch import (Blocked, EmailSubmitter, FormSubmitter, RateLimiter, Transient,
                                      dispatch_with_fallback)
from jobagent.agents.matcher import HallucinationError, RuleTailorer, parse_jd, verify_grounded
from jobagent.app import build_app
from jobagent.config import Settings
from jobagent.db import Store
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.orchestrator import Ctx, Orchestrator
from jobagent.schemas import (ApplicationRun, CandidateProfile, Channel, InboundClass, InboundEmail, JobListing,
                              RunStatus)

PROFILE = CandidateProfile(**SAMPLE_PROFILE)


def make(**kw):
    d = tempfile.mkdtemp()
    cfg = Settings(db_path=f"{d}/t.db", out_dir=f"{d}/out", **kw)
    store = Store(cfg.db_path)
    lim = RateLimiter(store, cfg)
    ctx = Ctx(store, cfg, PROFILE, RuleTailorer(), [EmailSubmitter(cfg, lim), FormSubmitter(cfg, lim)],
              sleep=lambda s: None)
    return cfg, store, ctx


class Sourcing(unittest.TestCase):
    def test_dedup_and_filters(self):
        _, store, _ = make()
        new = sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        ids = {j.id for j in new}
        self.assertNotIn("fx-5", ids)        # cross-board duplicate of fx-1
        self.assertNotIn("fx-6", ids)        # excluded keyword
        self.assertIn("fx-1", ids)
        self.assertEqual(sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE), [])   # idempotent


class Guard(unittest.TestCase):
    def setUp(self):
        _, self.store, self.ctx = make()
        sourcing.run_sourcing(self.store, [sourcing.FixtureSource()], PROFILE)
        self.job = self.store.get_job("fx-1")
        self.a = RuleTailorer().tailor(PROFILE, self.job, parse_jd(self.job))

    def test_honest_output_passes(self):
        verify_grounded(PROFILE, self.a)

    def test_fabricated_skill_blocked(self):
        self.a.ordered_skills.append("Rust")
        with self.assertRaises(HallucinationError):
            verify_grounded(PROFILE, self.a)

    def test_injected_tech_in_bullet_blocked(self):
        self.a.bullets[0].rewritten += " using Kubernetes and Spark"
        with self.assertRaises(HallucinationError):
            verify_grounded(PROFILE, self.a)

    def test_invented_years_blocked(self):
        self.a.tailored_summary += " With 15 years of experience."
        with self.assertRaises(HallucinationError):
            verify_grounded(PROFILE, self.a)

    def test_missing_reqs_reported_not_claimed(self):
        job = self.store.get_job("fx-1")
        job2 = job.model_copy(update={"description": "Requirements\nRust and Kubernetes"})
        a = RuleTailorer().tailor(PROFILE, job2, parse_jd(job2))
        self.assertIn("rust", a.missing_requirements)
        verify_grounded(PROFILE, a)


class Flow(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store, self.ctx = make()
        self.orch = Orchestrator(self.ctx)
        sourcing.run_sourcing(self.store, [sourcing.FixtureSource()], PROFILE)

    def test_parks_at_gate_and_never_sends_without_approval(self):
        run = self.orch.start("fx-1")
        self.assertEqual(run.status, RunStatus.AWAITING_APPROVAL)
        self.assertEqual(run.attempts, 0)
        self.assertFalse([e for e in self.store.audit_log(run.id) if e["event"] == "submitted"])

    def test_low_score_skipped(self):
        self.assertEqual(self.orch.start("fx-3").status, RunStatus.SKIPPED)

    def test_approve_dispatches_email_first(self):
        run = self.orch.start("fx-1")
        run = self.orch.resume(run.id, "approve")
        self.assertEqual((run.status, run.channel), (RunStatus.SUBMITTED, Channel.EMAIL))

    def test_reject_is_terminal(self):
        run = self.orch.resume(self.orch.start("fx-1").id, "reject")
        self.assertEqual(run.status, RunStatus.REJECTED)
        with self.assertRaises(ValueError):
            self.orch.resume(run.id, "approve")

    def test_double_approve_rejected(self):
        run = self.orch.start("fx-1")
        self.orch.resume(run.id, "approve")
        with self.assertRaises(ValueError):
            self.orch.resume(run.id, "approve")

    def test_start_is_idempotent(self):
        self.assertEqual(self.orch.start("fx-1").id, self.orch.start("fx-1").id)

    def test_dispatch_node_refuses_unapproved(self):
        from jobagent.orchestrator import n_dispatch
        run = self.orch.start("fx-1")
        with self.assertRaises(PermissionError):
            n_dispatch(self.ctx, run)


class Fallback(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store, self.ctx = make()
        self.job = JobListing(id="j", source="t", url="u", title="t", company="c", description="d")
        self.store.add_job(self.job)

    def run_with(self, *subs):
        run = ApplicationRun(id="r", job_id="j", status=RunStatus.APPROVED)
        return dispatch_with_fallback(run, self.job, self.store, self.cfg, list(subs), sleep=lambda s: None)

    def sub(self, ch, behaviour):
        calls = []
        class S:
            channel = ch
            def submit(s, *a):
                calls.append(1)
                r = behaviour(len(calls))
                if isinstance(r, Exception): raise r
                return r
        s = S(); s.calls = calls
        return s

    def test_blocked_falls_through_without_retry(self):
        a, b = self.sub(Channel.FORM, lambda n: Blocked("captcha")), self.sub(Channel.EMAIL, lambda n: "ok")
        run = self.run_with(a, b)
        self.assertEqual((len(a.calls), run.status, run.channel), (1, RunStatus.SUBMITTED, Channel.EMAIL))

    def test_transient_retries_then_succeeds(self):
        a = self.sub(Channel.FORM, lambda n: Transient("503") if n < 3 else "ok")
        run = self.run_with(a)
        self.assertEqual((len(a.calls), run.status), (3, RunStatus.SUBMITTED))

    def test_all_fail_escalates_to_human(self):
        run = self.run_with(self.sub(Channel.FORM, lambda n: Blocked("captcha")),
                            self.sub(Channel.EMAIL, lambda n: Transient("down")))
        self.assertEqual((run.status, run.channel), (RunStatus.NEEDS_MANUAL, Channel.MANUAL))

    def test_email_rate_limit_enforced(self):
        cfg, store, ctx = make(max_emails_per_hour=1)
        store.add_job(self.job.model_copy(update={"apply_email": "x@y.z"}))
        job = store.get_job("j")
        s = EmailSubmitter(cfg, RateLimiter(store, cfg))
        s.submit(job, "p", "c")
        from jobagent.agents.dispatch import RateLimited
        with self.assertRaises(RateLimited):
            s.submit(job, "p", "c")


class Triage(unittest.TestCase):
    def c(self, subject, body):
        return triage.classify(InboundEmail(id="x", sender="a@b.c", subject=subject, body=body))

    def test_interview_with_link_and_slot(self):
        m = self.c("Next steps", "Please book https://calendly.com/x/30 or Tue Oct 7 at 2pm PT")
        self.assertEqual(m.label, InboundClass.INTERVIEW)
        self.assertEqual(m.calendar_links, ["https://calendly.com/x/30"])
        self.assertEqual(len(m.proposed_slots), 1)

    def test_rejection_outranks_ack(self):
        self.assertEqual(self.c("Application", "Thank you for applying. Unfortunately we will not be proceeding.").label,
                         InboundClass.REJECTION)

    def test_screening(self):
        self.assertEqual(self.c("Quick q", "Please answer: salary expectations and notice period").label,
                         InboundClass.SCREENING)

    def test_idempotent_and_updates_run(self):
        cfg, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        o = Orchestrator(ctx)
        run = o.resume(o.start("fx-1").id, "approve")
        m = InboundEmail(id="m9", sender="hr@acmecloud.com", subject="Acme Cloud interview",
                         body="We'd like to schedule an interview")
        triage.process_inbound(store, m); triage.process_inbound(store, m)
        self.assertEqual(len(store.list_emails()), 1)
        self.assertEqual(store.get_run(run.id).status, RunStatus.INTERVIEW)


class SignedLinks(unittest.TestCase):
    def test_verify(self):
        sig = notify.sign("s", "r1", "approve", 2000)
        self.assertTrue(notify.verify("s", "r1", "approve", 2000, sig, now=1000))
        self.assertFalse(notify.verify("s", "r1", "reject", 2000, sig, now=1000))   # action tampering
        self.assertFalse(notify.verify("s", "r1", "approve", 2000, sig, now=3000))  # expired
        self.assertFalse(notify.verify("x", "r1", "approve", 2000, sig, now=1000))  # wrong secret


class Api(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.cfg = Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o", api_token="tok")
        self.c = TestClient(build_app(self.cfg, [sourcing.FixtureSource()]))
        self.h = {"Authorization": "Bearer tok"}

    def test_auth_required(self):
        self.assertEqual(self.c.get("/api/runs").status_code, 401)

    def test_end_to_end(self):
        r = self.c.post("/api/sweep", headers=self.h).json()
        self.assertGreaterEqual(r["discovered"], 3)
        pending = self.c.get("/api/runs?status=awaiting_approval", headers=self.h).json()
        self.assertTrue(pending)
        rid = next(r["id"] for r in pending if r["job"]["apply_email"])
        detail = self.c.get(f"/api/runs/{rid}", headers=self.h).json()
        self.assertIn("<h1>", detail["resume_html"])
        out = self.c.post(f"/api/runs/{rid}/decision", headers=self.h,
                          json={"decision": "approve", "cover_letter": "Edited letter"}).json()
        self.assertEqual(out["status"], "submitted")
        self.assertEqual(out["adaptation"]["cover_letter"], "Edited letter")
        self.assertEqual(self.c.post(f"/api/runs/{rid}/decision", headers=self.h,
                                     json={"decision": "approve"}).status_code, 409)

    def test_test_send_dry_run_and_validation(self):
        r = self.c.post("/api/test-send", headers=self.h, json={"to": "me@example.com"})
        self.assertEqual(r.status_code, 200); self.assertTrue(r.json()["dry_run"])
        self.assertEqual(self.c.post("/api/test-send", headers=self.h, json={"to": "a@b.co\nBcc: x@y.z"}).status_code, 502)

    def test_signed_link_endpoint(self):
        self.c.post("/api/sweep", headers=self.h)
        rid = self.c.get("/api/runs?status=awaiting_approval", headers=self.h).json()[0]["id"]
        url = notify.action_url(self.cfg, rid, "reject").replace(self.cfg.public_url, "")
        self.assertEqual(self.c.get(url).status_code, 200)
        self.assertEqual(self.c.get(url.replace("sig=", "sig=0")).status_code, 403)


if __name__ == "__main__":
    unittest.main()


class SameCompanyRoles(unittest.TestCase):
    def test_bullets_from_repeated_company_trace_to_the_right_role(self):
        from jobagent.schemas import Experience
        p = PROFILE.model_copy(update={"experience": [
            Experience(company="FICO", title="Senior", start="2026", bullets=["Built Python SOAR automation on AWS"]),
            Experience(company="FICO", title="Associate", start="2024", bullets=["Wrote Python modules for Splunk"])]})
        self.assertEqual(set(p.roles()), {"FICO (Senior)", "FICO (Associate)"})
        job = JobListing(id="j", source="t", url="u", title="SOAR Engineer", company="X",
                         description="Requirements\nPython and AWS\nSplunk")
        a = RuleTailorer().tailor(p, job, parse_jd(job))
        verify_grounded(p, a)
        self.assertEqual({b.source_company for b in a.bullets}, {"FICO (Senior)", "FICO (Associate)"})


class Regenerate(unittest.TestCase):
    def test_retailor_only_for_unsent_runs(self):
        cfg, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        o = Orchestrator(ctx)
        run = o.start("fx-1")
        again = o.retailor(run.id)
        self.assertEqual(again.status, RunStatus.AWAITING_APPROVAL)
        o.resume(run.id, "approve")
        with self.assertRaises(ValueError):
            o.retailor(run.id)


class BulkMail(unittest.TestCase):
    def c(self, sender, subject, body):
        return triage.classify(InboundEmail(id="x", sender=sender, subject=subject, body=body))

    def test_marketing_mentioning_interviews_is_not_an_interview(self):
        self.assertEqual(self.c("hi@crio.in", "SDE Hiring Insights", "Mock interview session starts 8:30 PM").label,
                         InboundClass.OTHER)
        self.assertEqual(self.c("x@glassdoor.com", "Role at Acme: great fit", "Interview tips... Unsubscribe").label,
                         InboundClass.OTHER)
        self.assertEqual(self.c("news@someco.com", "Career advice", "interview tips. Unsubscribe here").label,
                         InboundClass.OTHER)

    def test_bare_word_interview_no_longer_enough(self):
        self.assertEqual(self.c("a@b.co", "Newsletter", "5 interview mistakes to avoid").label, InboundClass.OTHER)

    def test_real_invites_still_detected(self):
        for body in ("We'd like to schedule a call with you next week", "Please pick a time that works for you",
                     "Could you share your availability?", "I'd love to speak with you about the role",
                     "Book a slot: https://calendly.com/x/30"):
            self.assertEqual(self.c("rec@acme.co", "Next steps", body).label, InboundClass.INTERVIEW, body)

    def test_ats_ack_and_rejection_survive_unsubscribe_footer(self):
        self.assertEqual(self.c("no-reply@ats.com", "Thank you for applying", "We have received your application. Unsubscribe").label,
                         InboundClass.ACK)
        self.assertEqual(self.c("no-reply@ats.com", "Update", "Unfortunately we will not be moving forward. Unsubscribe").label,
                         InboundClass.REJECTION)


class ScoreNowTailorLater(unittest.TestCase):
    def test_start_until_parks_scored_then_continue_finishes(self):
        cfg, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        o = Orchestrator(ctx)
        good, bad = o.start("fx-1", until="tailor"), o.start("fx-3", until="tailor")
        self.assertEqual((good.status, bad.status), (RunStatus.SCORED, RunStatus.SKIPPED))
        self.assertIsNone(good.adaptation)
        self.assertEqual(o.continue_run(good.id).status, RunStatus.AWAITING_APPROVAL)
        self.assertEqual(o.continue_run(bad.id).status, RunStatus.SKIPPED)       # no-op for non-parked runs


class Recovery(unittest.TestCase):
    def test_recover_leaves_parked_scored_runs_alone(self):
        cfg, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        o = Orchestrator(ctx)
        r = o.start("fx-1", until="tailor")
        self.assertEqual(o.recover(), 0)
        self.assertEqual(store.get_run(r.id).status, RunStatus.SCORED)


class Concurrency(unittest.TestCase):
    def test_parallel_reads_and_writes_never_mix_rows(self):
        import threading
        cfg, store, ctx = make()
        sourcing.run_sourcing(store, [sourcing.FixtureSource()], PROFILE)
        o = Orchestrator(ctx)
        for j in ("fx-1", "fx-2", "fx-3", "fx-4"):
            o.start(j)
        errors = []

        def reader():
            try:
                for _ in range(300):
                    store.list_runs(); store.audit_log(limit=50); store.list_emails()
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(300):
                    store.audit(__import__("jobagent.schemas", fromlist=["AuditEvent"]).AuditEvent(run_id=None, actor="t", event=f"e{i}"))
                    store.kv_set(f"k{i % 5}", str(i))
            except Exception as e:
                errors.append(e)

        ts = [threading.Thread(target=f) for f in (reader, reader, writer, writer)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errors, [])


class JdNoise(unittest.TestCase):
    def test_company_city_salary_are_not_requirements(self):
        j = JobListing(id="g", source="glassdoor", url="u", title="Security Operations Analyst", company="Comscore",
                       location="Pune", description="Security Operations Analyst\nComscore\nPune\n₹4L - ₹7L (Glassdoor Est.)")
        r = parse_jd(j)
        for bad in ("comscore", "pune", "glassdoor", "est"):
            self.assertNotIn(bad, r.must_have + r.keywords)
