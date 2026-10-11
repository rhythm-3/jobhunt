"""Dispatch Agent: rate-limited, channel-fallback submission. Only ever invoked after HITL approval."""
from __future__ import annotations

import time
from typing import Protocol

from ..config import Settings
from ..db import Store
from ..schemas import ApplicationRun, AuditEvent, Channel, JobListing, RunStatus


class Blocked(Exception):
    """Anti-bot wall (CAPTCHA / 403 / challenge). Not retryable on the same channel."""


class Transient(Exception):
    """Timeouts, 5xx, network blips. Retry with backoff."""


class RateLimited(Exception):
    def __init__(self, bucket: str):
        super().__init__(f"rate limit hit: {bucket}")
        self.bucket = bucket


class RateLimiter:
    """Sliding-window limiter persisted in the DB so restarts can't reset quotas."""
    def __init__(self, store: Store, settings: Settings, clock=time.time):
        self.s, self.cfg, self.clock = store, settings, clock

    def check_and_consume(self, bucket: str, limit: int, window_s: float) -> None:
        now = self.clock()
        if self.s.rate_count(bucket, window_s, now) >= limit:
            raise RateLimited(bucket)
        self.s.rate_add(bucket, now)


class Submitter(Protocol):
    channel: Channel
    def submit(self, job: JobListing, resume_path: str, cover_letter: str) -> str: ...


class EmailSubmitter:
    """Email application via Gmail API. Dry-run records what would be sent; live mode fails closed if unconfigured."""
    channel = Channel.EMAIL

    def __init__(self, settings: Settings, limiter: RateLimiter, store: Store | None = None,
                 profile_fn=None, sender=None):
        self.cfg, self.limiter, self.store, self.profile_fn, self.sender = settings, limiter, store, profile_fn, sender

    def submit(self, job, resume_path, cover_letter):
        if not job.apply_email:
            raise Blocked("no apply email")
        dedupe_key = f"sent:{job.id}"
        if self.store and self.store.kv_get(dedupe_key):
            raise Blocked("already emailed this job")          # belt-and-braces on top of one-run-per-job
        self.limiter.check_and_consume("email:hour", self.cfg.max_emails_per_hour, 3600)
        if self.cfg.dry_run:
            return f"dry-run: would email {job.apply_email} with {resume_path}"
        if not (self.sender and self.profile_fn):
            raise Blocked("email sender not configured")
        from ..mail import build_message
        p = self.profile_fn()
        sender = (self.store.kv_get("gmail:address") if self.store else None) or p.email
        msg = build_message(sender=sender, to=job.apply_email, reply_to=p.email,
                            subject=f"Application: {job.title} - {p.full_name}", body=cover_letter,
                            attachment=resume_path, attach_name=f"{p.full_name}_Resume")
        msg_id = self.sender.send(msg)
        if self.store:
            self.store.kv_set(dedupe_key, msg_id or "sent")    # recorded immediately after the send succeeds
        return f"gmail message {msg_id} -> {job.apply_email}"


class FormSubmitter:
    """Web forms are never auto-submitted (bot walls, per-ATS quirks, and account bans make it a bad trade).
    The run is escalated to a human, who uses the dashboard's assisted pre-fill (agents/formfill.py) and clicks Submit."""
    channel = Channel.FORM

    def __init__(self, settings: Settings, limiter: RateLimiter):
        self.cfg, self.limiter = settings, limiter

    def submit(self, job, resume_path, cover_letter):
        raise Blocked("no apply email: open the pre-filled form from the dashboard and submit it yourself")


def dispatch_with_fallback(run: ApplicationRun, job: JobListing, store: Store, cfg: Settings,
                           submitters: list[Submitter], sleep=time.sleep) -> ApplicationRun:
    """Try each channel in order; retry transient errors with exponential backoff; escalate to a human."""
    def log(ev, **d):
        store.audit(AuditEvent(run_id=run.id, actor="dispatch", event=ev, detail=d))

    for sub in submitters:
        for attempt in range(1, cfg.max_attempts + 1):
            run.attempts += 1
            try:
                receipt = sub.submit(job, run.resume_path or "", run.adaptation.cover_letter if run.adaptation else "")
            except Transient as e:
                log("transient_error", channel=sub.channel, attempt=attempt, error=str(e))
                if attempt < cfg.max_attempts:
                    sleep(min(60, 2 ** attempt))
                    continue
                break
            except (Blocked, RateLimited) as e:
                log("channel_blocked", channel=sub.channel, error=str(e))
                run.last_error = str(e)
                break                       # don't hammer a wall; move to next channel
            else:
                run.channel, run.last_error = sub.channel, None
                log("submitted", channel=sub.channel, receipt=receipt)
                run.status = RunStatus.SUBMITTED
                return run
    run.status = RunStatus.NEEDS_MANUAL
    run.channel = Channel.MANUAL
    log("escalated_to_human", reason=run.last_error)
    return run
