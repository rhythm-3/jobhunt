"""Durable state-machine orchestrator (LangGraph/Temporal-shaped, zero extra deps).

Each node is a pure-ish function `(ctx, run) -> next_node | INTERRUPT | END`. After every node the run
and a checkpoint are persisted, so a crash resumes at the last completed node. `INTERRUPT` parks the run
at the human-approval gate until `resume()` is called with a decision — the graph has NO edge from
`tailor` to `dispatch` that bypasses it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

from .agents import documents, matcher, notify
from .agents.dispatch import Submitter, dispatch_with_fallback
from .config import Settings
from .db import Store
from .schemas import ApplicationRun, AuditEvent, CandidateProfile, RunStatus

END, INTERRUPT = "__end__", "__interrupt__"


@dataclass
class Ctx:
    store: Store
    cfg: Settings
    profile: CandidateProfile
    tailorer: matcher.Tailorer
    submitters: list[Submitter]
    sleep: Callable[[float], None] = __import__("time").sleep


Node = Callable[[Ctx, ApplicationRun], str]


def _log(ctx: Ctx, run: ApplicationRun, event: str, **detail):
    ctx.store.audit(AuditEvent(run_id=run.id, actor="orchestrator", event=event, detail=detail))


def n_score(ctx: Ctx, run: ApplicationRun) -> str:
    job = ctx.store.get_job(run.job_id)
    reqs = matcher.parse_jd(job)
    run.match_score = matcher.score(ctx.profile, job, reqs)
    run.status = RunStatus.SCORED
    if run.match_score < ctx.profile.prefs.min_match:
        run.status = RunStatus.SKIPPED
        _log(ctx, run, "below_threshold", score=run.match_score)
        return END
    return "tailor"


def n_tailor(ctx: Ctx, run: ApplicationRun) -> str:
    job = ctx.store.get_job(run.job_id)
    reqs = matcher.parse_jd(job)
    try:
        note = ctx.store.kv_get(f"note:{run.id}")
        run.adaptation = matcher.tailor_with_guard(ctx.profile, job, reqs, ctx.tailorer, user_note=note)
    except matcher.HallucinationError as e:
        run.status, run.last_error = RunStatus.FAILED, str(e)
        _log(ctx, run, "grounding_failed", error=str(e))
        return END
    run.resume_path = documents.build_documents(ctx.profile, run.adaptation, ctx.cfg.out_dir, run.id)
    run.status = RunStatus.TAILORED
    return "approval_gate"


def _autopilot_ok(ctx: Ctx, run: ApplicationRun) -> bool:
    ap = ctx.profile.prefs.autopilot
    job = ctx.store.get_job(run.job_id)
    if not (ap.enabled and job and job.apply_email and (run.match_score or 0) >= ap.min_score):
        return False                                  # only email applications, only very strong matches
    import time
    if ctx.store.rate_count("autopilot:day", 86400, time.time()) >= ap.daily_cap:
        return False
    ctx.store.rate_add("autopilot:day", time.time())
    return True


def n_gate(ctx: Ctx, run: ApplicationRun) -> str:
    if _autopilot_ok(ctx, run):
        run.status = RunStatus.APPROVED
        _log(ctx, run, "auto_approved", score=run.match_score)
        return "dispatch"
    run.status = RunStatus.AWAITING_APPROVAL
    notify.notify(ctx.store, ctx.cfg, run, ctx.store.get_job(run.job_id))
    return INTERRUPT


def n_dispatch(ctx: Ctx, run: ApplicationRun) -> str:
    if run.status != RunStatus.APPROVED:   # defence in depth: never send without explicit approval
        raise PermissionError("dispatch reached without approval")
    run.status = RunStatus.SUBMITTING
    dispatch_with_fallback(run, ctx.store.get_job(run.job_id), ctx.store, ctx.cfg, ctx.submitters, ctx.sleep)
    return END


GRAPH: dict[str, Node] = {"score": n_score, "tailor": n_tailor, "approval_gate": n_gate, "dispatch": n_dispatch}


class Orchestrator:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def start(self, job_id: str, until: str | None = None) -> ApplicationRun:
        existing = self.ctx.store.run_for_job(job_id)
        if existing:
            return existing                 # idempotent: one run per job
        run = ApplicationRun(id=uuid.uuid4().hex[:12], job_id=job_id)
        self.ctx.store.save_run(run)
        _log(self.ctx, run, "run_created")
        return self._drive(run, "score", until)

    def continue_run(self, run_id: str, node: str = "tailor") -> ApplicationRun:
        """Resume a run parked by `start(..., until=node)` (used to score fast, tailor later in the background)."""
        run = self.ctx.store.get_run(run_id)
        if not run or run.status != RunStatus.SCORED:
            return run
        return self._drive(run, node)

    def _drive(self, run: ApplicationRun, node: str, until: str | None = None) -> ApplicationRun:
        while node not in (END, INTERRUPT) and node != until:
            try:
                nxt = GRAPH[node](self.ctx, run)
            except PermissionError:
                raise
            except Exception as e:          # unexpected bug -> fail the run, keep the system alive
                run.status, run.last_error = RunStatus.FAILED, repr(e)
                _log(self.ctx, run, "node_crashed", node=node, error=repr(e))
                nxt = END
            self.ctx.store.save_run(run)
            self.ctx.store.save_checkpoint(run.id, node, {"next": nxt})
            _log(self.ctx, run, "node_done", node=node, next=nxt, status=run.status)
            node = nxt
        return run

    def resume(self, run_id: str, decision: str, actor: str = "user") -> ApplicationRun:
        """HITL entry point. Only valid while the run is parked at the approval gate."""
        run = self.ctx.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        if run.status != RunStatus.AWAITING_APPROVAL:
            raise ValueError(f"run is {run.status}, not awaiting approval")
        self.ctx.store.audit(AuditEvent(run_id=run.id, actor=actor, event=f"decision_{decision}"))
        if decision == "reject":
            run.status = RunStatus.REJECTED
            self.ctx.store.save_run(run)
            return run
        if decision != "approve":
            raise ValueError("decision must be approve|reject")
        run.status = RunStatus.APPROVED
        self.ctx.store.save_run(run)
        return self._drive(run, "dispatch")

    def retailor(self, run_id: str, note: str | None = None) -> ApplicationRun:
        """Redo tailoring for a run that has not been sent (e.g. after switching to a better model)."""
        run = self.ctx.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        if run.status not in (RunStatus.AWAITING_APPROVAL, RunStatus.FAILED, RunStatus.SKIPPED):
            raise ValueError(f"run is {run.status}; only unsent runs can be regenerated")
        self.ctx.store.kv_set(f"note:{run.id}", (note or "").strip()[:500])
        self.ctx.store.audit(AuditEvent(run_id=run.id, actor="user", event="regenerate", detail={"note": note or ""}))
        run.last_error = None
        return self._drive(run, "tailor")      # explicit user request: tailor even a below-threshold match

    def refilter_all(self) -> dict:
        """Preferences changed: re-apply filters and the match threshold to every unsent job.
        Nothing is deleted - failing jobs become FILTERED (with the reason) and come back when filters loosen."""
        from collections import Counter
        from .agents.sourcing import passes_filters
        out: Counter = Counter()
        minm = self.ctx.profile.prefs.min_match
        movable = (RunStatus.SCORED, RunStatus.SKIPPED, RunStatus.AWAITING_APPROVAL, RunStatus.FAILED, RunStatus.FILTERED)
        for run in self.ctx.store.list_runs():
            if run.status not in movable:
                continue
            job = self.ctx.store.get_job(run.job_id)
            if not job or job.source == "gmail-import":
                continue
            reason = passes_filters(job, self.ctx.profile)
            before = (run.status, run.last_error)
            if reason:
                if run.status != RunStatus.FILTERED:
                    out["hidden"] += 1
                run.status, run.last_error = RunStatus.FILTERED, reason
            else:
                if run.status == RunStatus.FILTERED:
                    out["restored"] += 1
                    run.last_error = None
                    run.status = RunStatus.AWAITING_APPROVAL if run.adaptation else RunStatus.SCORED
                if run.status in (RunStatus.SCORED, RunStatus.SKIPPED):
                    new = RunStatus.SCORED if (run.match_score or 0) >= minm else RunStatus.SKIPPED
                    if new != run.status:
                        out["now_low_match" if new == RunStatus.SKIPPED else "now_new_match"] += 1
                    run.status = new
            if (run.status, run.last_error) != before:
                self.ctx.store.save_run(run)
        self.ctx.store.audit(AuditEvent(run_id=None, actor="orchestrator", event="refiltered", detail=dict(out)))
        return dict(out)

    def rescore_one(self, run_id: str) -> ApplicationRun | None:
        """A job's description changed (e.g. full text found): re-score it; unsent jobs move with the threshold."""
        run = self.ctx.store.get_run(run_id)
        job = self.ctx.store.get_job(run.job_id) if run else None
        if not (run and job):
            return run
        run.match_score = matcher.score(self.ctx.profile, job, matcher.parse_jd(job))
        if run.status in (RunStatus.SCORED, RunStatus.SKIPPED):
            run.status = RunStatus.SCORED if run.match_score >= self.ctx.profile.prefs.min_match else RunStatus.SKIPPED
        self.ctx.store.save_run(run)
        return run

    def rescore_scores(self) -> int:
        """The scoring formula changed: refresh every score in place. Documents are kept; unprepared jobs move with the threshold."""
        n = 0
        for run in self.ctx.store.list_runs():
            job = self.ctx.store.get_job(run.job_id)
            if not job or run.status in (RunStatus.SUBMITTED, RunStatus.APPROVED, RunStatus.SUBMITTING):
                continue
            new = matcher.score(self.ctx.profile, job, matcher.parse_jd(job))
            if new == run.match_score:
                continue
            run.match_score = new
            if run.status in (RunStatus.SCORED, RunStatus.SKIPPED):
                run.status = RunStatus.SCORED if new >= self.ctx.profile.prefs.min_match else RunStatus.SKIPPED
            self.ctx.store.save_run(run); n += 1
        return n

    def rescore_all(self) -> dict:
        """Profile changed: re-score every unsent run; tailored documents built from the old profile are discarded."""
        from collections import Counter
        out: Counter = Counter()
        for run in self.ctx.store.list_runs():
            if run.status not in (RunStatus.SCORED, RunStatus.SKIPPED, RunStatus.AWAITING_APPROVAL, RunStatus.FAILED,
                                  RunStatus.FILTERED):
                continue
            if run.adaptation is not None:
                out["documents_reset"] += 1
            run.adaptation, run.resume_path, run.last_error = None, None, None
            self._drive(run, "score", until="tailor")
            out[run.status.value] += 1
        self.ctx.store.audit(AuditEvent(run_id=None, actor="orchestrator", event="rescored_all", detail=dict(out)))
        return dict(out)

    def recover(self) -> int:
        """Crash recovery: re-drive runs stuck mid-graph (not parked, not terminal)."""
        n = 0
        for run in self.ctx.store.list_runs():
            cp = self.ctx.store.load_checkpoint(run.id)
            if run.status == RunStatus.TAILORED and cp and cp[1]["next"] in GRAPH:
                self._drive(run, cp[1]["next"]); n += 1
        return n
