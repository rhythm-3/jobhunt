"""FastAPI service: REST API + static HITL dashboard."""
from __future__ import annotations

import hmac
import threading
from concurrent.futures import ThreadPoolExecutor
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import documents, notify, sourcing, triage
from .agents.feeds import html_to_text
from .agents.intel import norm as _norm
from .agents.dispatch import EmailSubmitter, FormSubmitter, RateLimiter
from .agents.llm_tailor import ClaudeTailorer, OllamaTailorer, ResilientTailorer
from .agents.matcher import RuleTailorer
from .config import Settings
from .mail import GmailSender
from .db import Store
from .fixtures import SAMPLE_EMAILS, SAMPLE_JOBS, SAMPLE_PROFILE
from .orchestrator import Ctx, Orchestrator
from .schemas import Preferences, utcnow, ApplicationRun, AuditEvent, Channel, CandidateProfile, InboundEmail, JobListing, RunStatus

STATIC = Path(__file__).parent / "static"


class ResumeUpload(BaseModel):
    filename: str
    data_b64: str


class GmailClient(BaseModel):
    client_id: str
    client_secret: str


class ReplyBody(BaseModel):
    body: str


class Note(BaseModel):
    note: str = ""


class Cover(BaseModel):
    cover_letter: str


class Regen(BaseModel):
    note: str | None = None


class Manual(BaseModel):
    outcome: str        # "applied" | "dropped"
    confirmed: bool = False   # "applied" requires the user to confirm they pressed Submit on the company's site


class TestSend(BaseModel):
    to: str


class ClipIn(BaseModel):
    url: str = ""
    title: str
    company: str = ""
    location: str = ""
    description: str
    prepare: bool = False


class PracticeIn(BaseModel):
    question: str
    answer: str
    run_id: str | None = None


class NoteIn(BaseModel):
    note: str | None = None
    starred: bool | None = None


class NegotiationIn(BaseModel):
    target_base: float
    mention_competing: bool = False
    reasons: list[str] = []


class ThanksIn(BaseModel):
    body: str
    to: str


class Decision(BaseModel):
    decision: str
    cover_letter: str | None = None


def build_app(cfg: Settings | None = None, job_sources: list | None = None, launcher=None) -> FastAPI:
    cfg = cfg or Settings()
    store = Store(cfg.db_path)
    if not store.kv_get("profile"):
        store.kv_set("profile", CandidateProfile(**SAMPLE_PROFILE).model_dump_json())
    profile = lambda: CandidateProfile.model_validate_json(store.kv_get("profile"))
    limiter = RateLimiter(store, cfg)
    gmail = GmailSender()
    from .agents.feeds import ATS, DEFAULT_WATCHLIST, company_sources, default_sources
    from .agents.mail_jobs import GmailAlertSource

    def current_sources() -> list:
        """Rebuilt on every refresh so preference changes (watchlist, toggles) apply immediately."""
        if job_sources is not None:
            return job_sources
        if os.getenv("JOBAGENT_DEMO") == "1":
            return [sourcing.FixtureSource()]
        prefs = profile().preferences
        on = {"feeds": True, "companies": True, "gmail_alerts": True, **prefs.get("sources", {})}
        from .agents.feeds import remote_sources
        out = (default_sources(prefs.get("target_titles")) + remote_sources(prefs.get("target_titles"))) if on["feeds"] else []
        if on["companies"]:
            out += company_sources(prefs.get("watch_companies", DEFAULT_WATCHLIST))
        if on["gmail_alerts"] and gmail.configured:
            from .mail import GmailReader
            out.append(GmailAlertSource(GmailReader(gmail), store))
        return out

    def make_tailorer():
        if not cfg.use_llm:
            return RuleTailorer()
        primary = (OllamaTailorer(cfg.ollama_model, cfg.ollama_host) if cfg.llm_provider == "ollama"
                   else ClaudeTailorer(model=cfg.llm_model))
        primary.tone = profile().prefs.tone
        return ResilientTailorer(primary, on_fallback=lambda e: store.audit(
            AuditEvent(run_id=None, actor="tailor", event="llm_fallback", detail={"error": repr(e)})))

    def versions() -> list[dict]:
        import json as _json
        return _json.loads(store.kv_get("profiles") or "[]")

    def profile_for(run_id: str | None) -> CandidateProfile:
        """The resume version chosen for this job, else the active profile."""
        vid = store.kv_get(f"runprofile:{run_id}") if run_id else None
        v = next((x for x in versions() if x["id"] == vid), None) if vid else None
        if not v:
            return profile()
        vp = CandidateProfile.model_validate(v["profile"])
        vp.preferences = profile().preferences            # filters and settings always come from the active profile
        return vp

    def orch(run_id: str | None = None) -> Orchestrator:
        return Orchestrator(Ctx(store, cfg, profile_for(run_id), make_tailorer(),
                                [EmailSubmitter(cfg, limiter, store, profile, gmail), FormSubmitter(cfg, limiter)]))

    stop = threading.Event()

    def poll_loop():
        while not stop.wait(cfg.poll_interval_s):
            poll_once()

    def sweep_loop():
        """Scheduled refresh (Settings -> every N hours). Checked each minute so setting changes apply live."""
        import time as _t
        while not stop.wait(60):
            h = profile().prefs.sweep_hours
            last = float(store.kv_get("agent:sourcing:last", "0") or 0)
            if h and _t.time() - last >= h * 3600 and sweep_lock.acquire(blocking=False):
                sweep_state.update(running=True, started_at=utcnow().isoformat(), finished_at=None, result=None)
                sweep_bg()
            from datetime import datetime as _now
            dh, today = profile().prefs.digest_hour, _now.now()
            if dh >= 0 and today.hour == dh and store.kv_get("digest:last") != today.date().isoformat():
                store.kv_set("digest:last", today.date().isoformat())       # at most once a day, even if sending fails
                try:
                    app.state.send_digest()
                except Exception as e:   # noqa: BLE001
                    store.audit(AuditEvent(run_id=None, actor="digest", event="digest_failed", detail={"error": repr(e)[:200]}))

    def migrate_scores():
        """Scores before 2026-10-02 ignored the years of experience a posting asks for; refresh them once."""
        if store.kv_get("scoring:v2"):
            return
        n = orch().rescore_scores()
        store.kv_set("scoring:v2", "1")
        store.audit(AuditEvent(run_id=None, actor="orchestrator", event="rescored_for_experience", detail={"changed": n}))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        pool.submit(migrate_scores)
        if cfg.use_llm:
            pool.submit(lambda: orch().recover())     # may call the slow model: never block startup
        else:
            orch().recover()
        if cfg.poll_inbox and gmail.configured:
            threading.Thread(target=poll_loop, daemon=True, name="inbox-poller").start()
        if job_sources is None:
            threading.Thread(target=sweep_loop, daemon=True, name="sweep-scheduler").start()
        yield
        stop.set()

    app = FastAPI(title="JobAgent", version="0.1.0", lifespan=lifespan)

    def auth(authorization: str | None = Header(default=None)):
        if cfg.api_token and not hmac.compare_digest(authorization or "", f"Bearer {cfg.api_token}"):
            raise HTTPException(401, "invalid token")

    api = Depends(auth)

    def view(run, emails: list | None = None):
        job = store.get_job(run.job_id)
        mine = [m for m in (emails if emails is not None else store.list_emails()) if m.run_id == run.id]
        days = (utcnow() - run.updated_at).days
        follow = run.status == RunStatus.SUBMITTED and not mine and days >= profile().prefs.follow_up_days
        from .salary import parse_salary
        return {**run.model_dump(mode="json"), "job": job.model_dump(mode="json") if job else None,
                "starred": store.kv_get(f"star:{run.id}") == "1", "has_note": bool(store.kv_get(f"note:{run.id}")),
                "salary": parse_salary(f"{job.title}\n{job.description}") if job else None,
                "domain": store.kv_get(f"domain:{_norm(job.company)}") if job else None,
                "emails": len(mine), "days_since_update": days, "follow_up_due": follow}

    @app.get("/api/health")
    def health():
        return {"ok": True, "dry_run": cfg.dry_run, "hitl": cfg.require_approval, "gmail_configured": gmail.configured,
                "llm": cfg.llm_provider if cfg.use_llm else None,
                "inbox_polling": cfg.poll_inbox}

    @app.get("/api/pulse", dependencies=[api])
    def pulse():
        """Tiny 'has anything changed?' check for the page's background refresh."""
        return {"sig": f"{store.pulse()}|{len(queued_ids)}|{int(sweep_state['running'])}|{store.kv_get('agent:inbox:last', '')}"}

    @app.get("/api/stats", dependencies=[api])
    def stats():
        runs = store.list_runs()
        by = {s.value: 0 for s in RunStatus}
        for r in runs:
            by[r.status.value] += 1
        return {"by_status": by, "total": len(runs), "dry_run": cfg.dry_run,
                "quota": {"emails_last_hour": store.rate_count("email:hour", 3600, __import__("time").time()),
                          "email_limit": cfg.max_emails_per_hour}}

    pool = ThreadPoolExecutor(max_workers=1)    # one at a time: a local model serves one request at a time anyway

    def process(job_id: str) -> None:
        try:
            orch().start(job_id)
        except Exception as e:   # noqa: BLE001 - never let a worker thread die silently
            store.audit(AuditEvent(run_id=None, actor="worker", event="process_failed",
                                   detail={"job": job_id, "error": repr(e)}))

    queued_ids: set[str] = set()

    def queue_tailor(run_id: str) -> None:
        if run_id in queued_ids:
            return
        queued_ids.add(run_id)

        def job():
            try:
                orch(run_id).continue_run(run_id)
            finally:
                queued_ids.discard(run_id)
        pool.submit(job)

    @app.post("/api/runs/{run_id}/tailor", dependencies=[api])
    def tailor_now(run_id: str):
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status != RunStatus.SCORED:
            raise HTTPException(409, f"run is {r.status}")
        if cfg.use_llm:
            queue_tailor(run_id)
            return {"queued": True, "position": len(queued_ids)}
        return view(orch(run_id).continue_run(run_id))

    sweep_state = {"running": False, "started_at": None, "finished_at": None, "result": None}
    sweep_lock = threading.Lock()

    def do_sweep() -> dict:
        import collections
        import time as _t
        srcs = current_sources()
        src_stats: dict = {}
        new = sourcing.run_sourcing(store, srcs, profile(), src_stats)
        seen = {j.id for j in new}
        new += [j for j in store.jobs_without_runs() if j.id not in seen]   # orphans from an interrupted refresh
        by_source = collections.Counter(j.source.split(":")[0] for j in new)
        failed = [e["detail"]["source"] for e in store.audit_log(limit=50)
                  if e["event"] == "source_failed" and e["at"] >= (sweep_state["started_at"] or "")]
        # score everything now (ms); prepare only the best N ("Automatically prepare the best N" in Settings),
        # the rest wait under New matches for a click - same behaviour with or without a language model
        o = orch()
        runs = [o.start(j.id, until="tailor").id for j in new]
        top_n = profile().prefs.auto_tailor_top
        best = sorted((r for r in store.list_runs(RunStatus.SCORED.value) if r.id not in queued_ids),
                      key=lambda r: -(r.match_score or 0))[:top_n]
        for r in best:
            if cfg.use_llm:
                queue_tailor(r.id)
            else:
                o.continue_run(r.id)
        try:
            auto_outreach_drafts(profile().prefs.auto_outreach)     # drafts only: nothing is ever sent from here
        except Exception as e:   # noqa: BLE001
            store.audit(AuditEvent(run_id=None, actor="outreach", event="auto_draft_failed", detail={"error": repr(e)[:200]}))
        # OSINT: find full descriptions for the most promising thin listings (alert emails carry only a title)
        n = profile().prefs.auto_research
        if n and job_sources is None:
            thin = [r for r in store.list_runs() if r.status in (RunStatus.SCORED, RunStatus.AWAITING_APPROVAL, RunStatus.SKIPPED)]
            thin = [r for r in thin if (lambda j: j and len(j.description) < 600 and not j.enriched_from and not store.kv_get(f"jdmiss:{j.id}"))(store.get_job(r.job_id))]
            for r in sorted(thin, key=lambda r: -(r.match_score or 0))[:n]:
                research_bg(r.id)
        store.kv_set("agent:sourcing:last", str(_t.time()))
        queued = len(queued_ids)
        return {"discovered": len(new), "queued": queued, "runs": runs,
                "sources": len(srcs), "by_source": dict(by_source), "failed_sources": failed,
                "company_sites": {"boards": sum(1 for k in src_stats if k.split(":")[0] in ATS),
                                  **{k: sum(v[k] for n, v in src_stats.items() if n.split(":")[0] in ATS) for k in ("fetched", "matched", "new")}}}

    def sweep_bg():
        try:
            sweep_state["result"] = do_sweep()
        except Exception as e:   # noqa: BLE001
            sweep_state["result"] = {"error": repr(e)}
        finally:
            sweep_state.update(running=False, finished_at=utcnow().isoformat())
            sweep_lock.release()

    @app.post("/api/sweep", dependencies=[api])
    def sweep():
        """Refresh jobs from every enabled source. Runs in the background; poll /api/sweep/status."""
        if not sweep_lock.acquire(blocking=False):
            return {**sweep_state, "already_running": True}
        sweep_state.update(running=True, started_at=utcnow().isoformat(), finished_at=None, result=None)
        if job_sources is not None:          # injected sources (tests): synchronous, deterministic
            sweep_bg()
            return sweep_state["result"]
        threading.Thread(target=sweep_bg, daemon=True, name="sweep").start()
        return {**sweep_state}

    @app.get("/api/sweep/status", dependencies=[api])
    def sweep_status():
        return {**sweep_state, "tailor_queue": len(queued_ids)}

    @app.get("/api/runs", dependencies=[api])
    def runs(status: str | None = None, lite: bool = False):
        emails = store.list_emails()
        out_ = [view(r, emails) for r in store.list_runs(status)]
        if lite:                       # list screens: drop the long texts (the job panel fetches the full run)
            from .agents.market import years_asked, years_of_experience
            have = years_of_experience(profile())
            for v in out_:
                j, a = v.get("job"), v.get("adaptation")
                if j:
                    asked = years_asked(f"{j.get('title', '')}\n{j.get('description') or ''}")
                    v["exp"] = {"asked": asked, "have": have, "fit": None if asked is None else 1.0 if asked <= have else round(max(0.0, 1 - 0.18 * (asked - have)), 2)}
                    j["desc_len"] = len(j.get("description") or ""); j["description"] = ""
                if a:
                    v["adaptation"] = {"matched_requirements": a.get("matched_requirements", []), "missing_requirements": a.get("missing_requirements", [])}
                v.pop("checkpoint", None)
        return out_

    @app.get("/api/runs/{run_id}", dependencies=[api])
    def run_detail(run_id: str):
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        doc = Path(r.resume_path).with_name("resume.html") if r.resume_path else None
        from .agents.career import preflight
        j = store.get_job(r.job_id)
        return {**view(r), "resume_html": doc.read_text() if doc and doc.exists() else None,
                "audit": store.audit_log(run_id), "note": store.kv_get(f"note:{run_id}") or "",
                "checks": preflight(store, r, j, profile(), cfg.dry_run) if j and r.status == RunStatus.AWAITING_APPROVAL else [],
                "breakdown": _breakdown(j) if j else None, **(_analysis(r, j) if j else {}),
                "profile_version": store.kv_get(f"runprofile:{run_id}") or ""}

    def _analysis(r, j) -> dict:
        from .agents import market
        from .agents.matcher import parse_jd, score_parts
        from .salary import parse_salary
        p, reqs = profile_for(r.id), parse_jd(j)
        why = sourcing.passes_filters(j, profile())
        return {"verdict": market.verdict(p, j, reqs, score_parts(p, j, reqs), r.match_score or 0, why,
                                          parse_salary(f"{j.title}\n{j.description}"), r.adaptation),
                "keywords": market.keyword_report(p, j, reqs)}

    _insight_cache: dict = {}

    @app.get("/api/insights/jobs", dependencies=[api])
    def job_insights(ids: str = Query("", max_length=1200)):
        """One plain sentence per job saying why it fits (or doesn't), for the job cards. Built only from the
        verdict logic, i.e. from your profile and the posting; nothing is generated or guessed."""
        out = {}
        for rid in [x for x in ids.split(",") if x][:40]:
            r = store.get_run(rid); j = store.get_job(r.job_id) if r else None
            if not j:
                continue
            key = (rid, r.updated_at.isoformat() if r.updated_at else "", r.match_score)
            if key not in _insight_cache:
                v = _analysis(r, j)["verdict"]
                bit = (v["blockers"] or v["strengths"] or v["cautions"] or [""])[0]
                if len(_insight_cache) > 2000:
                    _insight_cache.clear()
                _insight_cache[key] = {"call": v["call"], "line": f"{v['why']} {bit}".strip(),
                                       "strengths": v["strengths"], "cautions": v["cautions"], "blockers": v["blockers"]}
            out[rid] = _insight_cache[key]
        return out

    def _breakdown(j) -> dict:
        """Why the job scored as it did: requirements you cover, how close the wording is to your background, and location."""
        from .agents.matcher import parse_jd, score_parts
        p = score_parts(profile(), j, parse_jd(j))
        why = sourcing.passes_filters(j, profile()) or ""
        loc_bad = any(w in why for w in ("on-site", "restricted", "work mode", "not remote"))
        from .agents.matcher import experience_fit
        return {"years": experience_fit(profile(), j), "skills": round(p["coverage"], 2) if p["asked"] else None, "met": p["met"], "asked": p["asked"],
                "experience": round(p["similarity"], 2), "location": 0.0 if loc_bad else 1.0, "location_note": why if loc_bad else ""}

    @app.post("/api/runs/{run_id}/decision", dependencies=[api])
    def decide(run_id: str, d: Decision):
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if d.cover_letter is not None and r.adaptation and r.status == RunStatus.AWAITING_APPROVAL:
            r.adaptation.cover_letter = d.cover_letter       # user edit before approve
            store.save_run(r)
            store.audit(AuditEvent(run_id=run_id, actor="user", event="cover_letter_edited"))
        if r.adaptation and r.status == RunStatus.AWAITING_APPROVAL and d.decision == "approve":
            r.resume_path = documents.build_documents(profile_for(r.id), r.adaptation, cfg.out_dir, r.id)    # current text, template and version
            store.save_run(r)
        try:
            return view(orch().resume(run_id, d.decision))
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.put("/api/runs/{run_id}/cover", dependencies=[api])
    def save_cover(run_id: str, c: Cover):
        r = store.get_run(run_id)
        if not r or not r.adaptation:
            raise HTTPException(404)
        if r.status not in (RunStatus.AWAITING_APPROVAL, RunStatus.NEEDS_MANUAL):
            raise HTTPException(409, f"run is {r.status}")
        if not c.cover_letter.strip() or len(c.cover_letter) > 8000:
            raise HTTPException(422, "cover letter must be 1-8000 characters")
        r.adaptation.cover_letter = c.cover_letter
        store.save_run(r)
        documents.build_documents(profile(), r.adaptation, cfg.out_dir, r.id)
        store.audit(AuditEvent(run_id=run_id, actor="user", event="cover_letter_edited"))
        return {"ok": True}

    @app.post("/api/runs/{run_id}/regenerate", dependencies=[api])
    def regenerate(run_id: str, body: Regen | None = None):
        note = body.note if body else None
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status not in (RunStatus.AWAITING_APPROVAL, RunStatus.FAILED, RunStatus.SKIPPED):
            raise HTTPException(409, f"run is {r.status}; only unsent runs can be regenerated")
        if cfg.use_llm:
            pool.submit(lambda: orch(run_id).retailor(run_id, note))
            return {"queued": True}
        return view(orch(run_id).retailor(run_id, note))

    @app.get("/api/action/{run_id}/{action}", response_class=HTMLResponse)
    def signed_action(run_id: str, action: str, exp: int = Query(), sig: str = Query()):
        """Target of Slack/Telegram buttons. HMAC-signed + expiring; single-use via status check."""
        if not notify.verify(cfg.signing_secret, run_id, action, exp, sig):
            raise HTTPException(403, "invalid or expired link")
        try:
            orch().resume(run_id, action, actor="user:signed-link")
        except (ValueError, KeyError) as e:
            raise HTTPException(409, str(e))
        return f"<h3>Done: {action}d.</h3><a href='/'>Open dashboard</a>"

    # Job boards where the user has an account: never automate them (bans), open them in the user's own browser
    BOARD_DOMAINS = ("glassdoor.", "linkedin.", "naukri.", "indeed.", "foundit.", "instahyre.", "monster.", "shine.com")

    def open_in_browser(url: str) -> None:
        import webbrowser
        webbrowser.open(url, new=2)

    def launch_form(run_id: str) -> None:
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "-m", "jobagent.agents.formfill", run_id], cwd=str(STATIC.parent.parent),
                         env=os.environ.copy(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @app.post("/api/runs/{run_id}/open-form", dependencies=[api])
    def open_form(run_id: str):
        """Opens the job page in a visible browser and pre-fills standard fields. Never submits."""
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status not in (RunStatus.NEEDS_MANUAL, RunStatus.AWAITING_APPROVAL):
            raise HTTPException(409, f"run is {r.status}")
        job = store.get_job(r.job_id)
        url = ((job.apply_url or job.url) if job else "") or ""     # the employer's own page when research found it
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if any(d in host for d in BOARD_DOMAINS):
            (launcher or (lambda _rid: open_in_browser(url)))(run_id)
            mode = "browser"
        else:
            (launcher or launch_form)(run_id)
            mode = "prefill"
        store.audit(AuditEvent(run_id=run_id, actor="user", event="open_form", detail={"mode": mode, "host": host}))
        return {"launched": True, "mode": mode, "host": host}

    @app.post("/api/runs/{run_id}/manual", dependencies=[api])
    def manual_outcome(run_id: str, m: Manual):
        """Record what the human did after using the assisted form."""
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status not in (RunStatus.NEEDS_MANUAL, RunStatus.AWAITING_APPROVAL):
            raise HTTPException(409, f"run is {r.status}")
        if m.outcome not in ("applied", "dropped"):
            raise HTTPException(422, "outcome must be applied|dropped")
        if m.outcome == "applied" and not m.confirmed:
            raise HTTPException(422, "confirm that you pressed Submit on the company's website first")
        r.status = RunStatus.SUBMITTED if m.outcome == "applied" else RunStatus.CLOSED
        if m.outcome == "applied":
            r.channel = Channel.FORM
        store.save_run(r)
        store.audit(AuditEvent(run_id=run_id, actor="user", event=f"manual_{m.outcome}"))
        return view(r)

    @app.post("/api/test-send", dependencies=[api])
    def test_send(t: TestSend):
        """User-initiated send of a sample tailored application to an address the user types (for verification)."""
        import uuid
        from .agents.matcher import parse_jd, tailor_with_guard
        from .mail import clean_addr
        from .schemas import JobListing
        from .agents.dispatch import Blocked, RateLimited, Transient
        try:
            to = clean_addr(t.to)
            base = SAMPLE_JOBS[0]
            job = JobListing(**{**base, "id": f"test-{uuid.uuid4().hex[:8]}", "apply_email": to,
                                "title": f"[JobAgent TEST] {base['title']}", "company": "Test Co"})
            adapt = tailor_with_guard(profile(), job, parse_jd(job), make_tailorer())
            path = documents.build_documents(profile(), adapt, cfg.out_dir, job.id)
            receipt = EmailSubmitter(cfg, limiter, store, profile, gmail).submit(job, path, adapt.cover_letter)
        except (Blocked, RateLimited, Transient) as e:
            raise HTTPException(502, str(e))
        store.audit(AuditEvent(run_id=None, actor="user", event="test_send", detail={"to": to, "receipt": receipt}))
        return {"receipt": receipt, "dry_run": cfg.dry_run}

    def poll_once() -> dict:
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import GmailReader
        try:
            res = triage.poll_inbox(store, GmailReader(gmail), profile().email)
            store.kv_set("agent:inbox:last", str(__import__("time").time()))
            if store.list_outreach() and __import__("time").time() - float(store.kv_get("outreach:last_check", "0") or 0) > 1200:
                app.state.check_outreach_replies()
            store.audit(AuditEvent(run_id=None, actor="inbox", event="poll", detail=res))
            return {"ok": True, **res}
        except (Blocked, RateLimited, Transient) as e:
            store.audit(AuditEvent(run_id=None, actor="inbox", event="poll_failed", detail={"error": str(e)}))
            return {"ok": False, "error": str(e)}

    @app.post("/api/inbox/poll", dependencies=[api])
    def inbox_poll():
        if not gmail.configured:
            raise HTTPException(409, "gmail not configured")
        return poll_once()

    def _email(mid: str):
        m = next((x for x in store.list_emails() if x.id == mid), None)
        if not m:
            raise HTTPException(404)
        return m

    @app.post("/api/inbox/{mid}/draft", dependencies=[api])
    def reply_draft(mid: str, n: Note | None = None):
        from .agents.assist import draft_reply
        body, how = draft_reply(cfg, profile(), _email(mid), (n.note if n else ""))
        return {"body": body, "method": how}

    @app.post("/api/inbox/{mid}/reply", dependencies=[api])
    def reply_send(mid: str, b: ReplyBody):
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import GmailReader, build_reply
        m = _email(mid)
        if not b.body.strip() or len(b.body) > 10000:
            raise HTTPException(422, "reply must be 1-10000 characters")
        if "[your" in b.body.lower():
            raise HTTPException(422, "fill in the [placeholders] before sending")
        if not mid.startswith("gmail:"):
            raise HTTPException(409, "only Gmail messages can be replied to")
        try:
            limiter.check_and_consume("email:hour", cfg.max_emails_per_hour, 3600)
            if cfg.dry_run:
                receipt = "dry-run: reply not sent"
            else:
                reader = GmailReader(gmail)
                orig = reader.headers(mid.split(":", 1)[1])
                sender = store.kv_get("gmail:address") or profile().email
                receipt = gmail.send(build_reply(sender, orig, b.body), thread_id=orig.get("threadId") or None)
        except (Blocked, RateLimited, Transient) as e:
            raise HTTPException(502, str(e))
        m.replied_at = utcnow().isoformat()
        store.save_email(m)
        store.audit(AuditEvent(run_id=m.run_id, actor="user", event="replied", detail={"email": mid, "receipt": receipt}))
        return {"ok": True, "dry_run": cfg.dry_run, "receipt": receipt}

    @app.post("/api/runs/{run_id}/followup/draft", dependencies=[api])
    def followup_draft(run_id: str):
        from .agents.assist import draft_followup
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not (r and j):
            raise HTTPException(404)
        body, how = draft_followup(cfg, profile(), j, (utcnow() - r.updated_at).days)
        return {"body": body, "method": how, "to": j.apply_email}

    @app.post("/api/runs/{run_id}/followup/send", dependencies=[api])
    def followup_send(run_id: str, b: ReplyBody):
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import build_message
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not (r and j):
            raise HTTPException(404)
        if r.status != RunStatus.SUBMITTED:
            raise HTTPException(409, f"run is {r.status}")
        if not j.apply_email:
            raise HTTPException(409, "no email address for this application - follow up on the company's site")
        if not b.body.strip() or "[your" in b.body.lower():
            raise HTTPException(422, "write the message and fill any [placeholders] first")
        p = profile()
        try:
            limiter.check_and_consume("email:hour", cfg.max_emails_per_hour, 3600)
            if cfg.dry_run:
                receipt = "dry-run: follow-up not sent"
            else:
                sender = store.kv_get("gmail:address") or p.email
                msg = build_message(sender, j.apply_email, p.email, f"Following up: Application for {j.title} - {p.full_name}",
                                    b.body, None, "")
                receipt = gmail.send(msg)
        except (Blocked, RateLimited, Transient) as e:
            raise HTTPException(502, str(e))
        store.save_run(r)                               # bumps updated_at: resets the follow-up clock
        store.audit(AuditEvent(run_id=run_id, actor="user", event="followed_up", detail={"receipt": receipt}))
        return {"ok": True, "dry_run": cfg.dry_run, "receipt": receipt}

    @app.get("/api/runs/{run_id}/prep", dependencies=[api])
    def get_prep(run_id: str):
        import json as js
        c = store.kv_get(f"prep:{run_id}")
        return js.loads(c) if c else None

    @app.post("/api/runs/{run_id}/prep", dependencies=[api])
    def make_prep(run_id: str):
        import json as js
        from .agents.assist import interview_prep
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not j:
            raise HTTPException(404)
        kit = interview_prep(cfg, profile(), j)
        store.kv_set(f"prep:{run_id}", js.dumps(kit))
        store.audit(AuditEvent(run_id=run_id, actor="assist", event="prep_generated", detail={"method": kit["method"]}))
        return kit

    @app.get("/api/insights", dependencies=[api])
    def get_insights():
        from .agents.assist import insights
        return insights(store, profile())

    @app.get("/api/inbox", dependencies=[api])
    def inbox():
        return [m.model_dump(mode="json") for m in store.list_emails()]

    @app.post("/api/inbox/webhook", dependencies=[api])
    def inbound(m: InboundEmail):
        return triage.process_inbound(store, m).model_dump(mode="json")

    @app.post("/api/demo/inbox", dependencies=[api])
    def demo_inbox():
        return [triage.process_inbound(store, InboundEmail(**m)).model_dump(mode="json") for m in SAMPLE_EMAILS]

    @app.get("/api/profile", dependencies=[api])
    def get_profile():
        return profile()

    @app.put("/api/profile", dependencies=[api])
    def put_profile(p: CandidateProfile):
        """Save a new/edited profile, then re-score every unsent job against it and re-tailor the best."""
        if not p.preferences:
            p.preferences = profile().preferences          # the editor doesn't send preferences
        if not p.experience or not p.skills:
            raise HTTPException(422, "a profile needs at least one experience entry and one skill")
        from .agents import retarget
        p.skills = retarget.split_skill_groups(p.skills) or p.skills           # "Cloud: AWS, GCP" -> AWS, GCP
        before, retargeted = profile(), None
        if retarget.needs_retarget(p, (p.preferences or {}).get("target_titles") or [], before):
            titles, field = retarget.search_titles(p)
            retargeted = {"from": (p.preferences or {}).get("target_titles") or [], "to": titles, "field": field}
            p.preferences = {**(p.preferences or {}), "target_titles": titles}   # the search follows the resume
        store.kv_set("profile", p.model_dump_json())
        store.audit(AuditEvent(run_id=None, actor="user", event="profile_updated",
                               detail={"skills": len(p.skills), "roles": len(p.experience)}))
        counts = orch().rescore_all()
        counts.update({f"filter_{k}": v for k, v in orch().refilter_all().items()})
        top = sorted(store.list_runs(RunStatus.SCORED.value), key=lambda r: -(r.match_score or 0))[:p.prefs.auto_tailor_top]
        for r in top:
            if cfg.use_llm:
                queue_tailor(r.id)
            else:
                orch().continue_run(r.id)
        searching = False
        if retargeted:
            store.audit(AuditEvent(run_id=None, actor="user", event="search_retargeted", detail=retargeted))
            if job_sources is None and sweep_lock.acquire(blocking=False):         # fetch jobs for the new field straight away
                sweep_state.update(running=True, started_at=utcnow().isoformat(), finished_at=None, result=None)
                threading.Thread(target=sweep_bg, daemon=True, name="sweep-retarget").start()
                searching = True
        return {"profile": p.model_dump(), "rescored": counts, "tailoring": len(top), "retargeted": retargeted, "searching": searching}

    @app.post("/api/profile/parse", dependencies=[api])
    def parse_profile(u: ResumeUpload):
        import base64 as b64
        from .agents.resume_parse import parse_resume
        try:
            data = b64.b64decode(u.data_b64, validate=True)
            return parse_resume(cfg, u.filename, data)
        except ValueError as e:
            raise HTTPException(422, str(e))

    # ---------------------------------------------------------- gmail connect / switch / disconnect
    oauth_pending: dict[str, str] = {}               # state -> PKCE verifier (single use)

    @app.get("/api/gmail/status", dependencies=[api])
    def gmail_status():
        has_client = bool(os.getenv("GMAIL_CLIENT_ID") and os.getenv("GMAIL_CLIENT_SECRET"))
        addr = store.kv_get("gmail:address") or ""
        if gmail.configured and not addr:
            try:
                from .mail import GmailReader
                addr = GmailReader(gmail).address()
                store.kv_set("gmail:address", addr)
            except Exception:   # noqa: BLE001
                addr = ""
        return {"connected": gmail.configured, "address": addr, "has_client": has_client,
                "client_id_hint": (os.getenv("GMAIL_CLIENT_ID") or "")[:12]}

    @app.post("/api/gmail/client", dependencies=[api])
    def gmail_client(c: GmailClient):
        if not c.client_id.endswith(".apps.googleusercontent.com") or len(c.client_secret) < 10:
            raise HTTPException(422, "that doesn't look like a Google OAuth client id / secret")
        from .env import update_env
        update_env({"GMAIL_CLIENT_ID": c.client_id.strip(), "GMAIL_CLIENT_SECRET": c.client_secret.strip()})
        return gmail_status()

    @app.get("/api/gmail/connect", dependencies=[api])
    def gmail_connect(request: Request):
        import base64 as b64
        import hashlib
        import secrets as sec
        import urllib.parse as up
        if not os.getenv("GMAIL_CLIENT_ID"):
            raise HTTPException(409, "add your Google OAuth client id and secret first")
        verifier, state = sec.token_urlsafe(64), sec.token_urlsafe(24)
        oauth_pending.clear()
        oauth_pending[state] = verifier
        challenge = b64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        redirect = f"http://127.0.0.1:{request.url.port or 8000}/"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + up.urlencode({
            "client_id": os.getenv("GMAIL_CLIENT_ID"), "redirect_uri": redirect, "response_type": "code",
            "scope": "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "access_type": "offline", "prompt": "consent select_account"})
        return {"url": url}

    def finish_oauth(code: str, state: str, port: int) -> str:
        import json as js
        import urllib.parse as up
        import urllib.request as ur
        from .env import update_env
        from .tls import ssl_context
        verifier = oauth_pending.pop(state, None)
        if not verifier:
            return "expired or unknown sign-in attempt - start again from Settings"
        data = up.urlencode({"client_id": os.getenv("GMAIL_CLIENT_ID"), "client_secret": os.getenv("GMAIL_CLIENT_SECRET"),
                             "code": code, "code_verifier": verifier, "grant_type": "authorization_code",
                             "redirect_uri": f"http://127.0.0.1:{port}/"}).encode()
        try:
            tok = js.load(ur.urlopen("https://oauth2.googleapis.com/token", data, timeout=20, context=ssl_context()))
        except Exception as e:   # noqa: BLE001
            return f"token exchange failed: {e}"
        want = {"https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"}
        if set(tok.get("scope", "").split()) != want or "refresh_token" not in tok:
            return "please tick BOTH permissions (send + read) on the Google screen"
        old = store.kv_get("gmail:address")
        update_env({"GMAIL_REFRESH_TOKEN": tok["refresh_token"]})
        gmail._token = None
        from .mail import GmailReader
        addr = GmailReader(gmail).address()
        store.kv_set("gmail:address", addr)
        if old and old != addr:                        # different mailbox: drop the previous account's inbox cache
            store._x("DELETE FROM inbox WHERE id LIKE 'gmail:%'")
            store._x("DELETE FROM kv WHERE k LIKE 'seen:%' OR k LIKE 'alertseen:%'")
        store.audit(AuditEvent(run_id=None, actor="user", event="gmail_connected", detail={"address": addr}))
        return ""

    @app.post("/api/gmail/disconnect", dependencies=[api])
    def gmail_disconnect():
        import urllib.parse as up
        import urllib.request as ur
        from .env import update_env
        from .tls import ssl_context
        tok = os.getenv("GMAIL_REFRESH_TOKEN")
        if tok:
            try:   # revoke at Google too, not just forget locally
                ur.urlopen(ur.Request("https://oauth2.googleapis.com/revoke", up.urlencode({"token": tok}).encode(),
                                      {"Content-Type": "application/x-www-form-urlencoded"}), timeout=15, context=ssl_context())
            except Exception:   # noqa: BLE001
                pass
        update_env({"GMAIL_REFRESH_TOKEN": None})
        gmail._token = None
        store._x("DELETE FROM kv WHERE k = 'gmail:address'")
        store.audit(AuditEvent(run_id=None, actor="user", event="gmail_disconnected"))
        return gmail_status()

    @app.get("/api/agents", dependencies=[api])
    def agents():
        import time as _t
        ago = lambda k: (lambda v: None if not v else int(_t.time() - float(v)))(store.kv_get(k))
        return {"sourcing": {"running": sweep_state["running"], "last_s_ago": ago("agent:sourcing:last"),
                             "every_h": profile().prefs.sweep_hours},
                "tailoring": {"provider": cfg.llm_provider if cfg.use_llm else "rules", "queue": len(queued_ids),
                              "model": cfg.ollama_model if cfg.llm_provider == "ollama" else cfg.llm_model},
                "triage": {"polling": cfg.poll_inbox and gmail.configured, "last_s_ago": ago("agent:inbox:last"),
                           "every_s": cfg.poll_interval_s},
                "dispatch": {"dry_run": cfg.dry_run, "gmail": gmail.configured,
                             "autopilot": profile().prefs.autopilot.enabled}}

    # ---------------------------------------------------------- OSINT: full descriptions + company research
    research_pool = ThreadPoolExecutor(max_workers=3)
    researching: set[str] = set()

    def research_job(run_id: str) -> dict:
        from .agents.intel import find_full_description, norm
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not j:
            return {"found": False}
        out = {"found": False}
        if len(j.description) < 600 and not j.enriched_from:
            hit = find_full_description(j, store.kv_get(f"domain:{norm(j.company)}"))
            if hit:
                j.description = html_to_text(hit["description"]) if "<" in hit["description"] else hit["description"]
                j.apply_url, j.enriched_from = hit["url"], hit["source"]
                store.update_job(j)
                before = r.match_score
                r = orch().rescore_one(run_id)
                store.audit(AuditEvent(run_id=run_id, actor="intel", event="full_description_found",
                                       detail={"source": hit["source"], "similarity": hit["similarity"], "score": [before, r.match_score]}))
                out = {"found": True, "source": hit["source"], "score_before": before, "score_after": r.match_score}
            else:
                store.kv_set(f"jdmiss:{j.id}", "1")
        return out

    def research_bg(run_id: str) -> None:
        if run_id in researching:
            return
        researching.add(run_id)

        def job():
            try:
                research_job(run_id)
            except Exception as e:   # noqa: BLE001
                store.audit(AuditEvent(run_id=run_id, actor="intel", event="research_failed", detail={"error": repr(e)[:200]}))
            finally:
                researching.discard(run_id)
        research_pool.submit(job)

    @app.post("/api/runs/{run_id}/research", dependencies=[api])
    def research(run_id: str, force: bool = False):
        from .agents.intel import company_intel
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not j:
            raise HTTPException(404)
        jd = research_job(run_id)
        intel = company_intel(store, j.company, force=force)
        return {"jd": jd, "intel": intel, "run": view(store.get_run(run_id))}

    @app.post("/api/runs/{run_id}/jd-from-link", dependencies=[api])
    def jd_from_link(run_id: str, body: dict):
        """User pastes the job's link on the company site -> full description + direct application link."""
        from .agents.intel import description_from_link
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not j:
            raise HTTPException(404)
        url = str(body.get("url", "")).strip()
        try:
            got = description_from_link(url)
        except ValueError as e:
            raise HTTPException(422, str(e))
        except Exception as e:   # noqa: BLE001
            raise HTTPException(422, f"couldn't read that page ({type(e).__name__}) - check the link")
        if len(got["description"]) < 200:
            raise HTTPException(422, "that page has almost no description text")
        warn = None
        from .agents.intel import _title_sim
        if got.get("title") and _title_sim(got["title"], j.title) < 0.3:
            warn = f"note: that page's title is “{got['title']}”, which differs from “{j.title}”"
        before = r.match_score
        j.description, j.apply_url, j.enriched_from = got["description"], url, got["source"]
        store.update_job(j)
        r = orch().rescore_one(run_id)
        store.audit(AuditEvent(run_id=run_id, actor="user", event="description_from_link", detail={"source": got["source"]}))
        return {"source": got["source"], "score_before": before, "score_after": r.match_score, "warning": warn, "run": view(r)}

    @app.get("/api/intel", dependencies=[api])
    def get_intel(company: str, force: bool = False):
        from .agents.intel import company_intel
        if not company.strip() or len(company) > 120:
            raise HTTPException(422, "company name required")
        return company_intel(store, company.strip(), force=force)

    @app.get("/api/companies", dependencies=[api])
    def companies():
        """Employers across your jobs, with cached research where available."""
        import json as js
        from .agents.intel import norm
        agg: dict = {}
        for r in store.list_runs():
            j = store.get_job(r.job_id)
            if not j or not j.company or j.company == "unknown":
                continue
            a = agg.setdefault(norm(j.company) or j.company, {"company": j.company, "jobs": 0, "best": 0.0, "statuses": {}, "rating": None, "run_ids": []})
            a["jobs"] += 1; a["best"] = max(a["best"], r.match_score or 0); a["run_ids"].append(r.id)
            a["statuses"][r.status.value] = a["statuses"].get(r.status.value, 0) + 1
            a["rating"] = a["rating"] or j.rating
        for k, a in agg.items():
            c = store.kv_get(f"intel:{k}")
            d = js.loads(c) if c else None
            a["domain"] = (d or {}).get("identity", {}).get("domain") or store.kv_get(f"domain:{k}")
            a["researched"] = bool(d)
            if d:
                a["open_roles"] = d.get("hiring", {}).get("open_roles"); a["security_roles"] = d.get("hiring", {}).get("security_roles")
                a["dmarc"] = d.get("security", {}).get("dmarc"); a["news"] = len(d.get("news", []))
        return sorted(agg.values(), key=lambda a: (-a["best"], a["company"]))

    @app.post("/api/companies/detect", dependencies=[api])
    def detect_company(body: dict):
        """Paste a careers-page link -> watchlist entry + a live check that the board has jobs."""
        from .agents.feeds import company_sources, detect_ats
        entry = detect_ats(str(body.get("url", "")))
        if not entry:
            raise HTTPException(422, "That link isn't a Greenhouse, Lever, Ashby or SmartRecruiters careers page. "
                                     "Open a job on the company's careers site and paste that page's address.")
        try:
            n = len(company_sources([entry])[0].fetch())
        except Exception as e:   # noqa: BLE001
            raise HTTPException(422, f"Found {entry} but couldn't load its jobs ({type(e).__name__}). Check the link.")
        return {"entry": entry, "open_jobs": n}

    @app.get("/api/settings", dependencies=[api])
    def get_settings():
        p = profile().prefs.model_dump()
        if p.get("watch_companies") is None:
            p["watch_companies"] = DEFAULT_WATCHLIST
        return p

    @app.put("/api/settings", dependencies=[api])
    def put_settings(new: Preferences):
        from .agents.feeds import ATS
        bad = [w for w in (new.watch_companies or []) if w.partition(":")[0] not in ATS or not company_sources([w])]
        if bad:
            raise HTTPException(422, f"watchlist entries must be greenhouse:/lever:/ashby:<slug>; bad: {bad}")
        p = profile()
        clean = {k: v for k, v in new.model_dump().items() if not k.startswith("_")}   # response-only keys never stored
        p.preferences = {**(p.preferences or {}), **clean}
        store.kv_set("profile", p.model_dump_json())
        store.audit(AuditEvent(run_id=None, actor="user", event="settings_updated"))
        applied = orch().refilter_all()          # filters & threshold apply to jobs already in the list, immediately
        return {**get_settings(), "_applied": applied}

    # ============================================================ candidate toolkit
    import json as _json
    import re as _re
    import uuid as _uuid
    from datetime import datetime as _dt
    from .agents import career
    from .schemas import Interview, Offer

    def _clean_name(*parts: str) -> str:
        return "_".join(_re.sub(r"[^A-Za-z0-9]+", "_", p).strip("_") for p in parts if p)[:120] or "file"

    # ---------- downloads (resume / cover letter as files for website applications)
    @app.get("/api/runs/{run_id}/files/{kind}", dependencies=[api])
    def download(run_id: str, kind: str):
        r = store.get_run(run_id)
        j = store.get_job(r.job_id) if r else None
        if not (r and j and r.adaptation):
            raise HTTPException(404, "no tailored documents for this job yet")
        p = profile_for(r.id)
        if kind == "resume":
            documents.build_documents(p, r.adaptation, cfg.out_dir, r.id)       # cheap when nothing changed; picks up a new template
            html_path = Path(cfg.out_dir) / r.id / "resume.html"
            f = Path(documents.ensure_pdf(str(html_path)))
            name = _clean_name(p.full_name, "Resume", j.company)
        elif kind == "cover-letter":
            f = Path(documents.cover_letter_pdf(p, j.company, j.title, r.adaptation.cover_letter, cfg.out_dir, r.id))
            name = _clean_name(p.full_name, "Cover_Letter", j.company)
        else:
            raise HTTPException(404)
        root = Path(cfg.out_dir).resolve()
        if root not in f.resolve().parents:
            raise HTTPException(404)
        store.audit(AuditEvent(run_id=run_id, actor="user", event="downloaded", detail={"kind": kind, "format": f.suffix}))
        return FileResponse(f, filename=name + f.suffix, media_type="application/pdf" if f.suffix == ".pdf" else "text/html")

    # ---------- notes & stars
    @app.put("/api/runs/{run_id}/note", dependencies=[api])
    def set_note(run_id: str, n: NoteIn):
        if not store.get_run(run_id):
            raise HTTPException(404)
        if n.note is not None:
            if len(n.note) > 10000:
                raise HTTPException(422, "notes are limited to 10,000 characters")
            store.kv_set(f"note:{run_id}", n.note)
        if n.starred is not None:
            store.kv_set(f"star:{run_id}", "1" if n.starred else "0")
        return {"note": store.kv_get(f"note:{run_id}") or "", "starred": store.kv_get(f"star:{run_id}") == "1"}

    # ---------- save a job from any website (bookmarklet) or by hand
    @app.post("/api/clip", dependencies=[api])
    def clip(c: ClipIn):
        from urllib.parse import urlparse
        import hashlib
        from .text import fingerprint
        title, company = c.title.strip()[:200], c.company.strip()[:120]
        desc = c.description.strip()
        if len(title) < 2:
            raise HTTPException(422, "add the job title")
        if len(desc) < 80:
            raise HTTPException(422, "paste the job description (at least a few sentences)")
        url = c.url.strip()
        if url and not url.startswith(("https://", "http://")):
            raise HTTPException(422, "the link must start with https://")
        host = urlparse(url).netloc.lower().removeprefix("www.") if url else "manual"
        boards = ("linkedin.", "glassdoor.", "naukri.", "indeed.", "foundit.", "monster.", "instahyre.", "shine.com")
        fp = fingerprint(title, company or host, "")
        dup = store.job_by_fingerprint(fp)
        if dup:
            if len(desc) > len(dup.description):
                dup.description = desc[:40000]; dup.enriched_from = dup.enriched_from or "saved"
                store.update_job(dup)
            run = store.run_for_job(dup.id) or orch().start(dup.id, until="tailor")
            return {"run_id": run.id, "status": run.status.value, "match_score": run.match_score, "duplicate": True}
        job = JobListing(id="saved:" + hashlib.sha1((url or title + company + desc[:200]).encode()).hexdigest()[:12],
                         source=f"saved:{host}", url=url or "", title=title, company=company or "Unknown company",
                         location=c.location.strip()[:200], remote=bool(_re.search(r"\bremote\b", c.location + " " + desc[:1500], _re.I)),
                         description=desc[:40000], fingerprint=fp, enriched_from="saved",
                         apply_url=url if url and not any(b in host for b in boards) else None)
        store.add_job(job)
        store.audit(AuditEvent(run_id=None, actor="user", event="job_saved", detail={"host": host, "title": title}))
        run = orch().start(job.id, until="tailor")          # you chose this job: filters don't apply, it's scored
        if c.prepare and run.status in (RunStatus.SCORED, RunStatus.SKIPPED):
            if run.status == RunStatus.SKIPPED:
                run.status = RunStatus.SCORED; store.save_run(run)
            if cfg.use_llm:
                queue_tailor(run.id)
            else:
                run = orch().continue_run(run.id)
        return {"run_id": run.id, "status": run.status.value, "match_score": run.match_score, "duplicate": False}

    @app.get("/clip")
    def clip_page():
        return FileResponse(STATIC / "clip.html")

    # ---------- resume health
    @app.get("/api/profile/health", dependencies=[api])
    def profile_health():
        from .agents.assist import insights
        return career.resume_health(profile(), insights(store, profile())["skill_demand"])

    @app.post("/api/profile/improve-bullet", dependencies=[api])
    def improve_bullet(body: dict):
        b = str(body.get("bullet", "")).strip()
        if not 5 <= len(b) <= 600:
            raise HTTPException(422, "bullet must be 5-600 characters")
        if not cfg.use_llm:
            return {"options": [], "method": "none", "note": "Turn on an AI model (Settings) for rewrite suggestions."}
        return {"options": career.rewrite_bullet(cfg, b), "method": cfg.llm_provider}

    @app.post("/api/profile/skills", dependencies=[api])
    def add_skills(body: dict):
        """Add skills the user confirms they have; re-score jobs without discarding prepared documents."""
        add = [str(s).strip()[:60] for s in body.get("add", []) if str(s).strip()][:20]
        if not add:
            raise HTTPException(422, "nothing to add")
        p = profile()
        have = {s.lower() for s in p.skills}
        p.skills += [s for s in add if s.lower() not in have]
        store.kv_set("profile", p.model_dump_json())
        store.audit(AuditEvent(run_id=None, actor="user", event="skills_added", detail={"skills": add}))
        o = orch()
        for r in store.list_runs():
            if r.status in (RunStatus.SCORED, RunStatus.SKIPPED, RunStatus.FILTERED, RunStatus.AWAITING_APPROVAL):
                o.rescore_one(r.id)
        o.refilter_all()
        return {"skills": p.skills}

    # ---------- practice
    @app.get("/api/practice", dependencies=[api])
    def practice_info(run_id: str | None = None):
        kit = _json.loads(store.kv_get(f"prep:{run_id}") or "null") if run_id else None
        hist = _json.loads(store.kv_get(f"practice:{run_id or 'general'}") or "[]")
        return {"bank": career.QUESTION_BANK, "prep": [q["question"] for q in (kit or {}).get("questions", [])], "history": hist[-30:]}

    @app.post("/api/practice", dependencies=[api])
    def practice(pi: PracticeIn):
        if not pi.question.strip() or len(pi.question) > 500:
            raise HTTPException(422, "question required")
        if len(pi.answer.split()) < 5:
            raise HTTPException(422, "write or dictate an answer first")
        if len(pi.answer) > 12000:
            raise HTTPException(422, "answer is too long")
        job = None
        if pi.run_id:
            r = store.get_run(pi.run_id)
            job = store.get_job(r.job_id) if r else None
        fb = career.practice_feedback(cfg, profile(), pi.question.strip(), pi.answer, job)
        key = f"practice:{pi.run_id or 'general'}"
        hist = _json.loads(store.kv_get(key) or "[]")
        hist.append({"at": utcnow().isoformat(), "question": pi.question.strip(), "score": fb["score"], "words": fb["words"]})
        store.kv_set(key, _json.dumps(hist[-60:]))
        return fb

    # ---------- interviews
    def iv_view(iv: Interview) -> dict:
        r = store.get_run(iv.run_id) if iv.run_id else None
        return {**iv.model_dump(mode="json"), "has_prep": bool(iv.run_id and store.kv_get(f"prep:{iv.run_id}")),
                "run_status": r.status.value if r else None}

    def _iv_from(body: dict, base: dict | None = None) -> Interview:
        data = {**(base or {}), **{k: v for k, v in body.items() if k not in ("id", "created_at", "thank_you_sent_at")}}
        try:
            return Interview(**data)
        except Exception as e:   # pydantic ValidationError -> readable 422
            raise HTTPException(422, str(e).split("\n")[1] if "\n" in str(e) else str(e))

    @app.get("/api/interviews", dependencies=[api])
    def list_interviews():
        return [iv_view(i) for i in store.list_interviews()]

    @app.post("/api/interviews", dependencies=[api])
    def create_interview(body: dict):
        iv = _iv_from(body, {"id": _uuid.uuid4().hex[:12]})
        if iv.run_id:
            r = store.get_run(iv.run_id)
            if not r:
                raise HTTPException(404, "unknown application")
            if r.status != RunStatus.OFFER:
                r.status = RunStatus.INTERVIEW; store.save_run(r)
        store.save_interview(iv)
        store.audit(AuditEvent(run_id=iv.run_id, actor="user", event="interview_scheduled",
                               detail={"company": iv.company, "at": iv.starts_at.isoformat()}))
        return iv_view(iv)

    @app.put("/api/interviews/{iid}", dependencies=[api])
    def update_interview(iid: str, body: dict):
        old = store.get_interview(iid)
        if not old:
            raise HTTPException(404)
        iv = _iv_from(body, old.model_dump())
        iv.thank_you_sent_at = old.thank_you_sent_at
        store.save_interview(iv)
        return iv_view(iv)

    @app.delete("/api/interviews/{iid}", dependencies=[api])
    def delete_interview(iid: str):
        store.delete_interview(iid)
        return {"ok": True}

    @app.get("/api/interviews/{iid}/ics", dependencies=[api])
    def interview_ics(iid: str):
        from fastapi.responses import Response
        iv = store.get_interview(iid)
        if not iv:
            raise HTTPException(404)
        return Response(career.interview_ics(iv), media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{_clean_name("Interview", iv.company)}.ics"'})

    def _recruiter_email(run_id: str | None):
        if not run_id:
            return None
        ms = [m for m in store.list_emails() if m.run_id == run_id and m.id.startswith("gmail:")]
        return sorted(ms, key=lambda m: m.received_at)[-1] if ms else None

    @app.post("/api/interviews/{iid}/thank-you/draft", dependencies=[api])
    def thanks_draft(iid: str, body: dict | None = None):
        iv = store.get_interview(iid)
        if not iv:
            raise HTTPException(404)
        text, how = career.thank_you_draft(cfg, profile(), iv, str((body or {}).get("topics", ""))[:500])
        m = _recruiter_email(iv.run_id)
        return {"body": text, "method": how, "to": m.sender if m else "", "in_thread": bool(m)}

    @app.post("/api/interviews/{iid}/thank-you/send", dependencies=[api])
    def thanks_send(iid: str, t: ThanksIn):
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import GmailReader, build_message, build_reply, clean_addr
        iv = store.get_interview(iid)
        if not iv:
            raise HTTPException(404)
        if not t.body.strip() or career.PLACEHOLDER.search(t.body):
            raise HTTPException(422, "fill in the [placeholders] first")
        try:
            to = clean_addr(t.to)
            limiter.check_and_consume("email:hour", cfg.max_emails_per_hour, 3600)
            if cfg.dry_run:
                receipt = "dry-run: thank-you not sent"
            else:
                sender = store.kv_get("gmail:address") or profile().email
                m = _recruiter_email(iv.run_id)
                if m and m.sender.lower() == to.lower():
                    orig = GmailReader(gmail).headers(m.id.split(":", 1)[1])
                    receipt = gmail.send(build_reply(sender, orig, t.body), thread_id=orig.get("threadId") or None)
                else:
                    receipt = gmail.send(build_message(sender, to, profile().email, f"Thank you — {iv.role or 'interview'} at {iv.company}",
                                                       t.body, None, ""))
        except (Blocked, RateLimited, Transient) as e:
            raise HTTPException(502, str(e))
        iv.thank_you_sent_at = utcnow().isoformat(); store.save_interview(iv)
        store.audit(AuditEvent(run_id=iv.run_id, actor="user", event="thank_you_sent", detail={"receipt": receipt}))
        return {"ok": True, "dry_run": cfg.dry_run}

    @app.get("/api/inbox/{mid}/interview-suggestion", dependencies=[api])
    def interview_suggestion(mid: str):
        m = next((x for x in store.list_emails() if x.id == mid), None)
        if not m:
            raise HTTPException(404)
        r = store.get_run(m.run_id) if m.run_id else None
        j = store.get_job(r.job_id) if r else None
        link = next((l for l in m.calendar_links if not _re.search(r"calendly|cal\.com|chilipiper|savvycal|goodtime", l)), "")
        return {"company": (j.company if j else m.company) or "", "role": j.title if j else "", "run_id": m.run_id,
                "times": career.parse_times(f"{m.subject}\n{m.body}"), "link": link,
                "booking_link": next((l for l in m.calendar_links if l != link), ""), "with_whom": m.sender_name}

    # ---------- offers
    def _offer_from(body: dict, base: dict | None = None) -> Offer:
        data = {**(base or {}), **{k: v for k, v in body.items() if k not in ("id", "created_at")}}
        try:
            return Offer(**data)
        except Exception as e:
            raise HTTPException(422, str(e).split("\n")[1] if "\n" in str(e) else str(e))

    def offer_view(o: Offer) -> dict:
        return {**o.model_dump(mode="json"), "recurring": o.recurring, "first_year": o.first_year}

    @app.get("/api/offers", dependencies=[api])
    def list_offers():
        return [offer_view(o) for o in store.list_offers()]

    @app.post("/api/offers", dependencies=[api])
    def create_offer(body: dict):
        o = _offer_from(body, {"id": _uuid.uuid4().hex[:12]})
        if o.run_id:
            r = store.get_run(o.run_id)
            if not r:
                raise HTTPException(404, "unknown application")
            r.status = RunStatus.OFFER; store.save_run(r)
        store.save_offer(o)
        store.audit(AuditEvent(run_id=o.run_id, actor="user", event="offer_added", detail={"company": o.company}))
        return offer_view(o)

    @app.put("/api/offers/{oid}", dependencies=[api])
    def update_offer(oid: str, body: dict):
        old = store.get_offer(oid)
        if not old:
            raise HTTPException(404)
        o = _offer_from(body, old.model_dump())
        store.save_offer(o)
        return offer_view(o)

    @app.delete("/api/offers/{oid}", dependencies=[api])
    def delete_offer(oid: str):
        store.delete_offer(oid)
        return {"ok": True}

    @app.get("/api/offers/market", dependencies=[api])
    def offers_market(role: str = ""):
        return career.market_salary(store, role[:200])

    @app.post("/api/offers/{oid}/negotiation", dependencies=[api])
    def negotiation(oid: str, n: NegotiationIn):
        o = store.get_offer(oid)
        if not o:
            raise HTTPException(404)
        if n.target_base <= 0:
            raise HTTPException(422, "enter the base salary you want to ask for")
        if n.target_base <= o.base:
            raise HTTPException(422, "your target should be higher than the current base")
        body, how, warns = career.negotiation_draft(cfg, profile(), o, store.list_offers(), n.target_base,
                                                    n.mention_competing, n.reasons, career.market_salary(store, o.role))
        return {"body": body, "method": how, "warnings": warns}

    @app.get("/api/learning", dependencies=[api])
    def learning(skills: str = ""):
        return career.learning_resources([s.strip() for s in skills.split(",") if s.strip()][:10])

    # ---------- weekly goal & streak (client computes weeks in the user's own timezone)
    @app.get("/api/progress", dependencies=[api])
    def progress():
        ev = [e["at"] for e in store.audit_log(limit=5000)
              if (e["event"] == "submitted" and e["actor"] == "dispatch") or e["event"] == "manual_applied"]
        ev += [r.created_at.isoformat() for r in store.list_runs()                       # applied elsewhere, found via Gmail
               if r.channel == Channel.EXTERNAL and r.job_id.startswith("import:")]
        return {"goal": profile().prefs.weekly_goal, "applied_at": ev}

    @app.get("/api/trends", dependencies=[api])
    def trends(days: int = Query(14, ge=7, le=90)):
        """Per-day counts for the dashboard trend lines and the activity grid (oldest first, local dates)."""
        import collections
        from datetime import datetime as _dt, timedelta
        today = _dt.now().astimezone().date()
        span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
        local = lambda v: (_dt.fromisoformat(v) if isinstance(v, str) else v).astimezone().date()
        cnt = {k: collections.Counter() for k in ("found", "applied", "interviews", "offers", "outreach")}
        runs = store.list_runs()
        for r in runs:
            cnt["found"][local(r.created_at)] += 1
        imported = {r.id: r for r in runs if r.channel == Channel.EXTERNAL}
        for e in store.audit_log(limit=5000):
            if (e["event"] == "submitted" and e["actor"] == "dispatch") or e["event"] == "manual_applied":
                cnt["applied"][local(e["at"])] += 1
            elif e["event"] == "imported_application" and e["run_id"] in imported:
                cnt["applied"][local(imported[e["run_id"]].created_at)] += 1      # the day the confirmation email arrived
        for i in store.list_interviews():
            cnt["interviews"][local(i.created_at)] += 1
        for o in store.list_offers():
            cnt["offers"][local(o.created_at)] += 1
        for o in store.list_outreach():
            if o.sent_at:
                cnt["outreach"][local(o.sent_at)] += 1
        return {"days": [d.isoformat() for d in span], **{k: [c.get(d, 0) for d in span] for k, c in cnt.items()}}

    # ---------- daily summary email (to yourself)
    def send_digest(force: bool = False) -> dict:
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import build_message
        p = profile()
        subject, body, n = career.digest_text(store, p, cfg.public_url, "OfferPilot")
        to = store.kv_get("gmail:address") or p.email
        if not gmail.configured:
            return {"sent": False, "reason": "Gmail isn't connected", "subject": subject, "preview": body}
        if cfg.dry_run:
            return {"sent": False, "reason": "practice mode — nothing is sent", "subject": subject, "preview": body}
        try:
            gmail.send(build_message(to, to, to, subject, body, None, ""))
        except (Blocked, RateLimited, Transient) as e:
            return {"sent": False, "reason": str(e), "subject": subject, "preview": body}
        store.kv_set("digest:last", _dt.now().date().isoformat())
        store.audit(AuditEvent(run_id=None, actor="digest", event="digest_sent", detail={"items": n}))
        return {"sent": True, "to": to, "subject": subject, "preview": body}

    app.state.send_digest = send_digest

    @app.post("/api/digest/send", dependencies=[api])
    def digest_now():
        return send_digest(force=True)

    # ---------- export everything (your data, portable)
    @app.get("/api/export", dependencies=[api])
    def export():
        from fastapi.responses import Response
        runs_ = store.list_runs()
        notes = {r.id: store.kv_get(f"note:{r.id}") for r in runs_ if store.kv_get(f"note:{r.id}")}
        data = {"exported_at": utcnow().isoformat(), "profile": profile().model_dump(mode="json"),
                "jobs": [store.get_job(r.job_id).model_dump(mode="json") for r in runs_ if store.get_job(r.job_id)],
                "applications": [r.model_dump(mode="json") for r in runs_], "emails": [m.model_dump(mode="json") for m in store.list_emails()],
                "interviews": [i.model_dump(mode="json") for i in store.list_interviews()],
                "offers": [o.model_dump(mode="json") for o in store.list_offers()], "notes": notes}
        return Response(_json.dumps(data, indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="offerpilot-export-{_dt.now():%Y-%m-%d}.json"'})

    # ---------- outreach: personalised email + tailored CV to people at companies, approval-gated, with a tracker
    from .agents import outreach as out
    from .schemas import Outreach, OutreachEvent
    outreach_queue = {"running": False, "sent": 0, "total": 0, "note": ""}
    outreach_lock = threading.Lock()
    app.state.outreach_delay = lambda: __import__("random").uniform(45, 90)   # seconds between emails; tests set 0
    OUT_EDITABLE = ("company", "role", "contact_name", "contact_title", "email", "linkedin_url", "run_id", "job_text", "note", "attach")

    def _oget(oid: str) -> Outreach:
        o = store.get_outreach(oid)
        if not o:
            raise HTTPException(404)
        return o

    def _oev(o: Outreach, event: str, detail: str = "") -> None:
        o.events.append(OutreachEvent(event=event, detail=detail[:200]))

    def _oview(o: Outreach) -> dict:
        d = out.view(o)
        d["blockers"] = out.blockers(o, store.list_outreach()) if o.status in ("draft", "approved") else []
        return d

    def _ofrom(body: dict, base: dict | None = None) -> Outreach:
        data = {**(base or {}), **{k: v for k, v in body.items() if k in OUT_EDITABLE + ("subject", "body", "followup_subject", "followup_body")}}
        try:
            return Outreach(**data)
        except Exception as e:   # noqa: BLE001
            raise HTTPException(422, str(e).split("\n")[1].strip().replace("Value error, ", "") if "\n" in str(e) else str(e))

    def _ofill_from_run(o: Outreach) -> None:
        r = store.get_run(o.run_id) if o.run_id else None
        j = store.get_job(r.job_id) if r else None
        if o.run_id and not j:
            raise HTTPException(404, "unknown saved job")
        if j:
            o.company, o.role = o.company or j.company, o.role or j.title
            o.job_text = o.job_text or (j.description or "")[:20000]

    def _oredraft(o: Outreach, polish: bool = False) -> list[str]:
        subject, body, method, warns = out.draft(cfg, profile(), o, polish)
        o.subject, o.body, o.method = subject, body, method
        return warns

    @app.get("/api/outreach", dependencies=[api])
    def outreach_list():
        items = store.list_outreach()
        cap = profile().prefs.outreach_daily_cap
        return {"items": [_oview(o) for o in items], "stats": out.stats(items, cap), "queue": outreach_queue,
                "dry_run": cfg.dry_run, "gmail": gmail.configured}

    @app.get("/api/outreach/links", dependencies=[api])
    def outreach_links(company: str = Query("", max_length=120), role: str = Query("", max_length=200)):
        if not company.strip():
            raise HTTPException(422, "enter a company name")
        return out.search_links(company.strip(), role.strip())

    @app.post("/api/outreach", dependencies=[api])
    def outreach_create(body: dict):
        o = _ofrom(body, {"id": _uuid.uuid4().hex[:12]})
        _ofill_from_run(o)
        o = _ofrom(o.model_dump(mode="json"), {"id": o.id})       # re-validate after filling
        items = store.list_outreach()
        dup = next((x for x in items if (o.email and x.email == o.email) or (o.linkedin_url and x.linkedin_url.rstrip("/") == o.linkedin_url.rstrip("/"))), None)
        if dup:
            raise HTTPException(409, f"{dup.contact_name or dup.email or 'This person'} at {dup.company} is already in your list ({dup.status}).")
        if not (o.email or o.linkedin_url or o.contact_name):
            raise HTTPException(422, "add at least an email address, a LinkedIn link or a name")
        warns = _oredraft(o)
        _oev(o, "created", "draft written")
        store.save_outreach(o)
        return {**_oview(o), "warnings": warns}

    @app.post("/api/outreach/import", dependencies=[api])
    def outreach_import(body: dict):
        """One contact per line: Name, email, Company, Role (role optional). Anything else on the line is ignored."""
        lines = [l.strip() for l in str(body.get("text", "")).splitlines() if l.strip()][:50]
        created, skipped = [], []
        for l in lines:
            parts = [x.strip() for x in _re.split(r"[,\t;|]", l)]
            email = next((x for x in parts if "@" in x), "")
            li = next((x for x in parts if "linkedin.com" in x), "")
            rest = [x for x in parts if x and x != email and x != li]
            if len(rest) < 2:
                skipped.append({"line": l[:80], "reason": "need a name and a company"}); continue
            try:
                created.append(outreach_create({"contact_name": rest[0], "company": rest[1], "role": rest[2] if len(rest) > 2 else "",
                                                "email": email, "linkedin_url": li, "job_text": body.get("job_text", "")})["id"])
            except HTTPException as e:
                skipped.append({"line": l[:80], "reason": str(e.detail)})
        return {"created": len(created), "skipped": skipped}

    @app.put("/api/outreach/{oid}", dependencies=[api])
    def outreach_update(oid: str, body: dict):
        old = _oget(oid)
        if old.status in ("sent", "replied", "interview", "declined", "bounced", "do_not_contact"):
            allowed = {k: v for k, v in body.items() if k in ("followup_subject", "followup_body", "contact_name", "contact_title", "note", "linkedin_url")}
            if not allowed:
                raise HTTPException(409, "This email has already been sent and can't be edited.")
            body = allowed
        o = _ofrom(body, old.model_dump())
        if old.status in ("draft", "approved"):
            o.reviewed = True                     # saving from the review dialog means the user has read it
        if o.status == "approved" and any(getattr(o, k) != getattr(old, k) for k in OUT_EDITABLE + ("subject", "body")):
            o.status = "draft"; _oev(o, "edited", "approval withdrawn — approve again after your changes")
        store.save_outreach(o)
        return _oview(o)

    @app.delete("/api/outreach/{oid}", dependencies=[api])
    def outreach_delete(oid: str):
        o = _oget(oid)
        if o.status == "do_not_contact":
            raise HTTPException(409, "Kept on purpose, so this person is never emailed again.")
        store.delete_outreach(oid)
        return {"ok": True}

    @app.post("/api/outreach/{oid}/draft", dependencies=[api])
    def outreach_redraft(oid: str, body: dict):
        o = _oget(oid)
        if o.status not in ("draft", "approved"):
            raise HTTPException(409, "already sent")
        for k in ("note", "job_text", "role", "company", "contact_name"):
            if k in body:
                setattr(o, k, str(body[k])[:20000])
        o = _ofrom(o.model_dump(mode="json"), {"id": o.id})
        warns = _oredraft(o, bool(body.get("polish")))
        o.status, o.reviewed = "draft", False; _oev(o, "drafted", f"rewritten ({o.method})")
        store.save_outreach(o)
        return {**_oview(o), "warnings": warns}

    @app.post("/api/outreach/{oid}/approve", dependencies=[api])
    def outreach_approve(oid: str):
        o = _oget(oid)
        if o.status == "approved":
            return _oview(o)
        if o.status != "draft":
            raise HTTPException(409, "already sent")
        bad = out.blockers(o, store.list_outreach())
        if bad:
            raise HTTPException(422, bad[0])
        bad_facts = out.ungrounded(o.body, profile(), f"{o.company} {o.role} {o.job_text} {o.note} {o.contact_name}")
        if bad_facts:
            raise HTTPException(422, f"The message mentions {', '.join(bad_facts[:3])}, which isn't in your profile. Remove it or add it to your profile first.")
        o.status, o.reviewed = "approved", True; _oev(o, "approved", "you approved this email")
        store.save_outreach(o)
        return _oview(o)

    @app.post("/api/outreach/{oid}/reviewed", dependencies=[api])
    def outreach_reviewed(oid: str):
        o = _oget(oid)
        if o.status in ("draft", "approved") and not o.reviewed:
            o.reviewed = True; store.save_outreach(o)
        return _oview(o)

    @app.post("/api/outreach/{oid}/unapprove", dependencies=[api])
    def outreach_unapprove(oid: str):
        o = _oget(oid)
        if o.status == "approved":
            o.status = "draft"; _oev(o, "unapproved"); store.save_outreach(o)
        return _oview(o)

    def _send_outreach(o: Outreach) -> str:
        """Sends one approved email (initial). Raises Blocked / RateLimited / Transient."""
        from .agents.dispatch import Blocked, RateLimited
        from .mail import build_message
        items = store.list_outreach()
        bad = out.blockers(o, items)
        if bad:
            raise Blocked(bad[0])
        if out.sent_in_last_24h(items, utcnow()) >= profile().prefs.outreach_daily_cap:
            raise RateLimited("outreach:day")
        limiter.check_and_consume("outreach:hour", 8, 3600)       # its own bucket: outreach never starves job applications
        path = None
        if o.attach:
            try:
                path, _ = out.build_cv(cfg, store, profile(), o)
            except Exception as e:   # noqa: BLE001
                raise Blocked(f"couldn't build the CV: {str(e)[:100]}")
        if cfg.dry_run:
            receipt = "dry-run: not sent"
        else:
            sender = store.kv_get("gmail:address") or profile().email
            receipt = gmail.send(build_message(sender, o.email, profile().email, o.subject, o.body, path,
                                               f"{profile().full_name}_CV_{o.company}")) or "sent"
        o.status, o.sent_at, o.receipt = "sent", utcnow(), receipt
        _oev(o, "sent", "practice mode: not actually sent" if cfg.dry_run else f"to {o.email}" + (" with CV" if path else ""))
        store.save_outreach(o)
        store.audit(AuditEvent(run_id=o.run_id, actor="user", event="outreach_sent", detail={"company": o.company, "practice": cfg.dry_run}))
        return receipt

    @app.post("/api/outreach/{oid}/send", dependencies=[api])
    def outreach_send(oid: str):
        from .agents.dispatch import Blocked, RateLimited, Transient
        o = _oget(oid)
        if o.status not in ("draft", "approved"):
            raise HTTPException(409, "already sent")
        if o.status == "draft":
            outreach_approve(oid); o = _oget(oid)      # "Send now" is your approval for this one email
        try:
            _send_outreach(o)
        except RateLimited as e:
            raise HTTPException(429, "Daily limit reached — it resumes tomorrow. You can change the limit in Settings." if e.bucket == "outreach:day" else "Sending too fast; try again in a few minutes.")
        except (Blocked, Transient) as e:
            raise HTTPException(502, str(e))
        return {**_oview(_oget(oid)), "dry_run": cfg.dry_run}

    def _outreach_queue_worker() -> None:
        from .agents.dispatch import Blocked, RateLimited, Transient
        try:
            while not stop.is_set():
                nxt = next((x for x in sorted(store.list_outreach(), key=lambda x: x.created_at) if x.status == "approved"), None)
                if not nxt:
                    outreach_queue["note"] = "All approved emails are sent."
                    break
                try:
                    _send_outreach(nxt)
                    outreach_queue["sent"] += 1
                except RateLimited as e:
                    outreach_queue["note"] = "Daily limit reached — the rest are waiting and you can send them tomorrow." if e.bucket == "outreach:day" else "Paused: hourly sending limit."
                    break
                except Blocked as e:
                    nxt = _oget(nxt.id); nxt.status = "draft"; _oev(nxt, "send_failed", str(e)); store.save_outreach(nxt)
                except Transient as e:
                    outreach_queue["note"] = f"Paused: {e}"
                    break
                if any(x.status == "approved" for x in store.list_outreach()) and stop.wait(app.state.outreach_delay()):
                    break                          # spacing between emails only when another one is waiting
        finally:
            outreach_queue["running"] = False
            outreach_lock.release()

    def _start_outreach_queue() -> dict:
        n = sum(1 for x in store.list_outreach() if x.status == "approved")
        if not n:
            raise HTTPException(409, "Nothing is approved yet. Review a draft and press Approve first.")
        if not outreach_lock.acquire(blocking=False):
            return {**outreach_queue, "already_running": True}
        outreach_queue.update(running=True, sent=0, total=n, note="")
        threading.Thread(target=_outreach_queue_worker, daemon=True, name="outreach-sender").start()
        return outreach_queue

    @app.post("/api/outreach/send-approved", dependencies=[api])
    def outreach_send_approved():
        return _start_outreach_queue()

    @app.post("/api/outreach/approve-and-send", dependencies=[api])
    def outreach_approve_and_send(body: dict):
        """One click for drafts the user has already opened and read: approve the ones that pass every check, then send."""
        ids = [str(i) for i in (body.get("ids") or [])][:50]
        done, skipped = [], []
        for oid in ids:
            o = store.get_outreach(oid)
            if not o or o.status not in ("draft", "approved"):
                continue
            if o.status == "draft":
                bad = out.blockers(o, store.list_outreach()) or ([] if o.reviewed else ["Open and read this one first."])
                bad = bad or (["It mentions something that isn't in your profile."] if out.ungrounded(o.body, profile(), f"{o.company} {o.role} {o.job_text} {o.note} {o.contact_name}") else [])
                if bad:
                    skipped.append({"id": oid, "who": o.contact_name or o.email or o.company, "reason": bad[0]}); continue
                o.status = "approved"; _oev(o, "approved", "approved with “Approve & send”"); store.save_outreach(o)
            done.append(oid)
        if not done:
            raise HTTPException(422, (skipped[0]["reason"] if skipped else "Nothing to send."))
        return {**_start_outreach_queue(), "approved": len(done), "skipped": skipped}

    def auto_outreach_drafts(limit: int) -> int:
        """Prepare (never send) an outreach draft for each of the best new matches; the user adds who to write to."""
        from datetime import timedelta
        if limit <= 0:
            return 0
        items, now = store.list_outreach(), utcnow()
        have_run = {x.run_id for x in items if x.run_id}
        recent = [x.company for x in items if now - x.created_at < timedelta(days=30)]
        floor = max(profile().prefs.min_match, 0.0)
        cands = sorted((r for r in store.list_runs() if r.status in (RunStatus.SCORED, RunStatus.AWAITING_APPROVAL, RunStatus.NEEDS_MANUAL)
                        and r.id not in have_run and (r.match_score or 0) >= floor), key=lambda r: -(r.match_score or 0))
        n = 0
        for r in cands:
            j = store.get_job(r.job_id)
            if not j or any(out._same_co(j.company, c) for c in recent):
                continue
            o = Outreach(id=_uuid.uuid4().hex[:12], company=j.company[:120], role=j.title[:200], run_id=r.id, job_text=(j.description or "")[:20000], auto=True)
            _oredraft(o); _oev(o, "auto_drafted", f"from a {round((r.match_score or 0) * 100)}% match — add who to write to")
            store.save_outreach(o); recent.append(j.company); n += 1
            if n >= limit:
                break
        return n

    @app.post("/api/outreach/auto-draft", dependencies=[api])
    def outreach_auto_draft(body: dict):
        lim = int(body.get("limit") or profile().prefs.auto_outreach or 5)
        return {"created": auto_outreach_drafts(max(1, min(lim, 20)))}

    @app.post("/api/outreach/{oid}/followup/draft", dependencies=[api])
    def outreach_followup_draft(oid: str):
        o = _oget(oid)
        if o.status != "sent":
            raise HTTPException(409, "Only unanswered emails get a follow-up.")
        o.followup_subject, o.followup_body = out.followup_draft(profile(), o)
        store.save_outreach(o)
        return _oview(o)

    @app.post("/api/outreach/{oid}/followup/send", dependencies=[api])
    def outreach_followup_send(oid: str):
        from .agents.dispatch import Blocked, RateLimited, Transient
        from .mail import GmailReader, build_message
        o = _oget(oid)
        bad = out.followup_blockers(o)
        if bad or not o.followup_body.strip():
            raise HTTPException(422, (bad or ["Write the follow-up first."])[0])
        if not o.email:
            raise HTTPException(422, "No email address — follow up where you first wrote to them (for example on LinkedIn).")
        try:
            limiter.check_and_consume("outreach:hour", 8, 3600)
            if cfg.dry_run:
                receipt = "dry-run: not sent"
            else:
                sender = store.kv_get("gmail:address") or profile().email
                msg, thread = build_message(sender, o.email, profile().email, o.followup_subject or ("Re: " + o.subject), o.followup_body, None, ""), None
                try:                                                   # keep it in the same thread when we can
                    orig = GmailReader(gmail).headers(o.receipt)
                    mid = orig.get("message-id", "")
                    if mid:
                        msg["In-Reply-To"], msg["References"] = mid, (orig.get("references", "") + " " + mid).strip()
                    thread = orig.get("threadId") or None
                except Exception:   # noqa: BLE001
                    pass
                receipt = gmail.send(msg, thread_id=thread)
        except RateLimited:
            raise HTTPException(429, "Sending too fast; try again in a few minutes.")
        except (Blocked, Transient) as e:
            raise HTTPException(502, str(e))
        o.followups_sent += 1; o.last_followup_at = utcnow()
        _oev(o, "followup_sent", "practice mode: not actually sent" if cfg.dry_run else "follow-up sent")
        store.save_outreach(o)
        store.audit(AuditEvent(run_id=o.run_id, actor="user", event="outreach_followup", detail={"company": o.company}))
        return {**_oview(o), "dry_run": cfg.dry_run}

    @app.post("/api/outreach/{oid}/mark", dependencies=[api])
    def outreach_mark(oid: str, body: dict):
        o = _oget(oid)
        status = body.get("status")
        if status not in ("replied", "interview", "declined", "do_not_contact", "sent"):
            raise HTTPException(422, "unknown status")
        if not o.sent_at and status in ("replied", "interview", "declined"):
            o.sent_at = utcnow()          # contacted outside the app (e.g. on LinkedIn)
            o.receipt = o.receipt or "manual"
        o.status = status
        if status in ("replied", "interview", "declined"):
            o.replied_at = o.replied_at or utcnow()
        _oev(o, "marked", f"you marked it {status.replace('_', ' ')}")
        store.save_outreach(o)
        return _oview(o)

    @app.post("/api/outreach/{oid}/contacted", dependencies=[api])
    def outreach_contacted(oid: str):
        """The user sent the message themselves (e.g. as a LinkedIn message) — start tracking it."""
        o = _oget(oid)
        if o.status in ("draft", "approved"):
            o.status, o.sent_at, o.receipt = "sent", utcnow(), "manual"
            _oev(o, "sent", "you sent it yourself (for example on LinkedIn)")
            store.save_outreach(o)
        return _oview(o)

    def check_outreach_replies() -> int:
        from .mail import GmailReader
        if not gmail.configured:
            return 0
        waiting = [x for x in store.list_outreach() if x.status == "sent"]
        n = 0
        for oid, kind, snippet, when in out.scan_replies(GmailReader(gmail), waiting, triage.classify):
            o = _oget(oid)
            o.status = kind
            if kind != "bounced":
                o.replied_at, o.reply_snippet = when, snippet
            _oev(o, kind, snippet[:120] if kind != "bounced" else "the address bounced — check it")
            store.save_outreach(o); n += 1
        store.kv_set("outreach:last_check", str(__import__("time").time()))
        return n

    app.state.check_outreach_replies = check_outreach_replies

    @app.post("/api/outreach/check-replies", dependencies=[api])
    def outreach_check_replies():
        from .agents.dispatch import Blocked, RateLimited, Transient
        if not gmail.configured:
            raise HTTPException(409, "Connect Gmail first (Settings) so replies can be found.")
        try:
            return {"updated": check_outreach_replies()}
        except (Blocked, RateLimited, Transient) as e:
            raise HTTPException(502, str(e))

    @app.get("/api/outreach/{oid}/cv", dependencies=[api])
    def outreach_cv(oid: str):
        o = _oget(oid)
        try:
            path, what = out.build_cv(cfg, store, profile(), o)
        except Exception as e:   # noqa: BLE001
            raise HTTPException(500, f"couldn't build the CV: {str(e)[:100]}")
        f = Path(path)
        root = Path(cfg.out_dir).resolve()
        if not f.is_file() or root not in f.resolve().parents:
            raise HTTPException(404)
        name = _re.sub(r"[^\w.-]", "_", f"{profile().full_name}_CV_{o.company}") + f.suffix
        return FileResponse(f, filename=name, media_type="application/pdf" if f.suffix == ".pdf" else "text/html", headers={"X-CV-About": what})

    # ---------- resume versions, templates, salary explorer, LinkedIn review, contacts, form-fill data
    from .agents import market
    from .schemas import Contact

    def _save_versions(vs: list[dict]) -> None:
        import json as _json
        store.kv_set("profiles", _json.dumps(vs))

    def _vsummary(v: dict) -> dict:
        pr = v["profile"]
        return {"id": v["id"], "name": v["name"], "saved_at": v["saved_at"], "skills": len(pr.get("skills", [])),
                "headline": (pr.get("experience") or [{}])[0].get("title", ""), "titles": (pr.get("preferences") or {}).get("target_titles", [])}

    def _sync_active() -> list[dict]:
        """Before switching, write the working profile back into its own version so edits aren't lost."""
        vs, act = versions(), store.kv_get("profile:active")
        for v in vs:
            if v["id"] == act:
                v["profile"], v["saved_at"] = profile().model_dump(mode="json"), utcnow().isoformat()
        return vs

    @app.get("/api/profile/versions", dependencies=[api])
    def list_versions():
        return {"active": store.kv_get("profile:active") or "", "versions": [_vsummary(v) for v in versions()]}

    @app.post("/api/profile/versions", dependencies=[api])
    def save_version(body: dict):
        name = str(body.get("name", "")).strip()[:40]
        if not name:
            raise HTTPException(422, "give this version a name, for example “Backend”")
        vs = versions()                 # a snapshot of what you have now; the other versions stay as they were saved
        if any(v["name"].lower() == name.lower() for v in vs):
            raise HTTPException(409, "you already have a version with that name")
        if len(vs) >= 8:
            raise HTTPException(409, "eight versions is the limit — delete one first")
        v = {"id": _uuid.uuid4().hex[:10], "name": name, "saved_at": utcnow().isoformat(), "profile": profile().model_dump(mode="json")}
        _save_versions(vs + [v]); store.kv_set("profile:active", v["id"])
        return list_versions()

    @app.post("/api/profile/versions/{vid}/activate", dependencies=[api])
    def activate_version(vid: str):
        vs = _sync_active()
        v = next((x for x in vs if x["id"] == vid), None)
        if not v:
            raise HTTPException(404)
        _save_versions(vs)
        store.kv_set("profile:active", vid)
        out_ = put_profile(CandidateProfile.model_validate(v["profile"]))       # same path as saving a profile: re-score, re-filter, prepare the best
        return {**list_versions(), "rescored": out_["rescored"], "tailoring": out_["tailoring"]}

    @app.delete("/api/profile/versions/{vid}", dependencies=[api])
    def delete_version(vid: str):
        if vid == store.kv_get("profile:active"):
            raise HTTPException(409, "this is the version in use — switch to another one first")
        _save_versions([v for v in versions() if v["id"] != vid])
        return list_versions()

    @app.post("/api/runs/{run_id}/dismiss", dependencies=[api])
    def dismiss_run(run_id: str):
        """“Not for me”: a matched job you don't want. It moves to Closed and can be brought back."""
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status not in (RunStatus.SCORED, RunStatus.SKIPPED):
            raise HTTPException(409, "only jobs you haven't prepared can be dismissed this way")
        r.status = RunStatus.REJECTED; store.save_run(r)
        store.audit(AuditEvent(run_id=run_id, actor="user", event="dismissed"))
        return view(r)

    @app.post("/api/runs/{run_id}/restore", dependencies=[api])
    def restore_run(run_id: str):
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404)
        if r.status != RunStatus.REJECTED or r.adaptation:
            raise HTTPException(409, "only dismissed jobs can be restored")
        r.status = RunStatus.SCORED if (r.match_score or 0) >= profile().prefs.min_match else RunStatus.SKIPPED; store.save_run(r)
        return view(r)

    @app.put("/api/runs/{run_id}/version", dependencies=[api])
    def set_run_version(run_id: str, body: dict):
        """Use a particular resume version for this one job (empty = the active one). Takes effect when it is next prepared."""
        if not store.get_run(run_id):
            raise HTTPException(404)
        vid = str(body.get("version") or "")
        if vid and not any(v["id"] == vid for v in versions()):
            raise HTTPException(404, "unknown resume version")
        store.kv_set(f"runprofile:{run_id}", vid)
        return {"version": vid}

    @app.get("/api/resume/templates", dependencies=[api])
    def resume_templates():
        return {"active": profile().prefs.resume_template, "templates": [{"id": k, "label": v[0]} for k, v in documents.TEMPLATES.items()]}

    @app.get("/api/resume/preview", dependencies=[api], response_class=HTMLResponse)
    def resume_preview(template: str = Query("classic")):
        if template not in documents.TEMPLATES:
            raise HTTPException(404)
        return documents.render_resume_html(profile(), out.master_adaptation(profile()), template)

    @app.get("/api/salary", dependencies=[api])
    def salary(role: str = Query("", max_length=80), city: str = Query("", max_length=40)):
        return market.salary_explorer(store, role.strip(), city.strip())

    @app.post("/api/linkedin/review", dependencies=[api])
    def linkedin_review(body: dict):
        from .agents.assist import insights
        skills = body.get("skills") or []
        if isinstance(skills, str):
            skills = _re.split(r"[,\n;·•|]+", skills)
        if not (str(body.get("headline", "")).strip() or str(body.get("about", "")).strip()):
            raise HTTPException(422, "paste your LinkedIn headline or About section first")
        return market.linkedin_review(profile(), str(body.get("headline", ""))[:400], str(body.get("about", ""))[:6000],
                                      [str(x)[:60] for x in skills][:120], insights(store, profile())["skill_demand"],
                                      profile().prefs.target_titles)

    def _cview(c: Contact) -> dict:
        today = utcnow().astimezone().date().isoformat()
        return {**c.model_dump(mode="json"), "due": bool(c.next_follow_up and c.next_follow_up <= today)}

    def _cfrom(body: dict, base: dict) -> Contact:
        try:
            return Contact(**{**base, **{k: v for k, v in body.items() if k not in ("id", "created_at")}})
        except Exception as e:   # noqa: BLE001
            raise HTTPException(422, str(e).split("\n")[1].strip().replace("Value error, ", "") if "\n" in str(e) else str(e))

    @app.get("/api/contacts", dependencies=[api])
    def contacts():
        return [_cview(c) for c in store.list_contacts()]

    @app.post("/api/contacts", dependencies=[api])
    def contact_create(body: dict):
        c = _cfrom(body, {"id": _uuid.uuid4().hex[:12]})
        store.save_contact(c)
        return _cview(c)

    @app.put("/api/contacts/{cid}", dependencies=[api])
    def contact_update(cid: str, body: dict):
        old = store.get_contact(cid)
        if not old:
            raise HTTPException(404)
        c = _cfrom(body, old.model_dump())
        store.save_contact(c)
        return _cview(c)

    @app.delete("/api/contacts/{cid}", dependencies=[api])
    def contact_delete(cid: str):
        store.delete_contact(cid)
        return {"ok": True}

    @app.get("/api/autofill", dependencies=[api])
    def autofill():
        """What the browser extension may type into an application form: contact details and, optionally, a prepared cover letter.
        The extension never presses Submit and never answers salary, visa, demographic or consent questions."""
        from .agents.formfill import profile_values
        p = profile()
        vals = profile_values(p)
        other = next((l for l in p.links if "linkedin" not in l.lower()), "")
        vals.update({"website": other if other.startswith("http") else ("https://" + other if other else ""),
                     "current_company": p.experience[0].company if p.experience else "",
                     "current_title": p.experience[0].title if p.experience else ""})
        ready = []
        for r in store.list_runs():
            if r.status in (RunStatus.AWAITING_APPROVAL, RunStatus.NEEDS_MANUAL) and r.adaptation:
                j = store.get_job(r.job_id)
                if j:
                    ready.append({"id": r.id, "company": j.company, "title": j.title, "cover_letter": r.adaptation.cover_letter})
        return {"values": vals, "applications": ready[:60], "name": p.full_name}

    # ---------- assistant: answers questions about the app from its own guide
    from .agents import assistant

    def _assistant_status() -> dict:
        from datetime import timedelta
        by = {x.value: 0 for x in RunStatus}
        for r in store.list_runs():
            by[r.status.value] += 1
        now = utcnow()
        ivs = [i for i in store.list_interviews() if i.status == "scheduled" and i.starts_at > now]
        ost = out.stats(store.list_outreach(), profile().prefs.outreach_daily_cap)
        return {"new": by["scored"], "ready": by["awaiting_approval"] + by["needs_manual"], "applied": by["submitted"],
                "interviews": by["interview"], "offers": by["offer"], "dry_run": cfg.dry_run, "gmail": gmail.configured,
                "has_profile": profile().full_name != SAMPLE_PROFILE["full_name"],
                "interviews_soon": sum(1 for i in ivs if i.starts_at - now < timedelta(hours=48)),
                "replies": sum(1 for m in store.list_emails() if (m.label or "") in ("interview_request", "screening_questions") and not m.replied_at),
                "outreach_due": ost["follow_ups_due"], "outreach_drafts": ost["drafts"], "outreach_sent": ost["sent"], "outreach_replied": ost["replied"]}

    @app.get("/api/assistant", dependencies=[api])
    def assistant_info():
        return {"starters": assistant.STARTERS, "topics": [{"id": t["id"], "title": t["title"]} for t in assistant.GUIDE],
                "ai": cfg.use_llm}

    @app.post("/api/assistant", dependencies=[api])
    def assistant_ask(body: dict):
        q = str(body.get("message", ""))[:500]
        hist = [h for h in (body.get("history") or []) if isinstance(h, dict)][-6:]
        return assistant.answer(cfg, q, _assistant_status(), hist, str(body.get("product") or "OfferPilot")[:40])

    @app.get("/api/audit", dependencies=[api])
    def audit():
        return store.audit_log()

    @app.get("/")
    def index(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        from fastapi.responses import RedirectResponse
        import urllib.parse as up
        if error:
            return RedirectResponse("/#settings?gmail=" + up.quote("Google sign-in was cancelled"))
        if code and state:
            err = finish_oauth(code, state, request.url.port or 8000)
            return RedirectResponse("/#settings?gmail=" + up.quote(err or "connected"))
        return FileResponse(STATIC / "index.html")

    @app.get("/welcome")
    def welcome():
        return FileResponse(STATIC / "welcome.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app

