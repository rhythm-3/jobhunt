"""Notification Agent: webhook/Slack/Telegram payloads with HMAC-signed, expiring action links."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request

from ..tls import ssl_context

from ..config import Settings
from ..db import Store
from ..schemas import ApplicationRun, AuditEvent, JobListing

ACTIONS = ("approve", "reject")


def sign(secret: str, run_id: str, action: str, exp: int) -> str:
    return hmac.new(secret.encode(), f"{run_id}|{action}|{exp}".encode(), hashlib.sha256).hexdigest()


def verify(secret: str, run_id: str, action: str, exp: int, sig: str, now: float | None = None) -> bool:
    if action not in ACTIONS or (now or time.time()) > exp:
        return False
    return hmac.compare_digest(sign(secret, run_id, action, exp), sig)


def action_url(cfg: Settings, run_id: str, action: str, ttl: int = 86400) -> str:
    exp = int(time.time()) + ttl
    return f"{cfg.public_url}/api/action/{run_id}/{action}?exp={exp}&sig={sign(cfg.signing_secret, run_id, action, exp)}"


def approval_payload(cfg: Settings, run: ApplicationRun, job: JobListing) -> dict:
    """Slack Block Kit compatible; Discord/Telegram adapters can map from the same structure."""
    return {"text": f"Approval needed: {job.title} @ {job.company} ({run.match_score:.0%} match)",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                        "text": f"*{job.title}* — {job.company}\nMatch *{run.match_score:.0%}* · {job.url}"}},
                       {"type": "actions", "elements": [
                           {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary",
                            "url": action_url(cfg, run.id, "approve")},
                           {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "style": "danger",
                            "url": action_url(cfg, run.id, "reject")},
                           {"type": "button", "text": {"type": "plain_text", "text": "Review / Edit"},
                            "url": f"{cfg.public_url}/#run={run.id}"}]}]}


def notify(store: Store, cfg: Settings, run: ApplicationRun, job: JobListing, kind: str = "approval") -> None:
    payload = approval_payload(cfg, run, job)
    delivered = False
    if cfg.webhook_url:
        try:
            req = urllib.request.Request(cfg.webhook_url, json.dumps(payload).encode(),
                                         {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10, context=ssl_context()).read()   # noqa: S310
            delivered = True
        except Exception as e:   # notification failure must never block the pipeline
            store.audit(AuditEvent(run_id=run.id, actor="notify", event="delivery_failed", detail={"error": repr(e)}))
    store.audit(AuditEvent(run_id=run.id, actor="notify", event=f"{kind}_notification",
                           detail={"delivered": delivered, "channel": "webhook" if cfg.webhook_url else "dashboard"}))
