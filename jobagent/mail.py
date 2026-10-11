"""Gmail API sender (OAuth2 refresh-token flow, `gmail.send` scope only) built on stdlib.

Safety properties:
  * No library can widen the scope: the refresh token itself is minted with gmail.send only (scripts/gmail_auth.py).
  * Header-injection safe: addresses are validated, subject is stripped of CR/LF, MIME built with `email.message`.
  * At-most-once: Gmail has no idempotency key, so an ambiguous failure (timeout after the request left)
    is NOT retried - it is reported as Blocked so a human checks the Sent folder.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

from .agents.dispatch import Blocked, RateLimited, Transient
from .tls import ssl_context
from .secrets import EnvSecrets, SecretProvider

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
EMAIL_RE = re.compile(r"^[^\s@<>,;\"']+@[^\s@<>,;\"']+\.[^\s@<>,;\"']+$")

# (method, url, headers, body) -> (status, body_bytes); raises OSError family on network failure
Http = Callable[[str, str, dict, bytes], tuple[int, bytes]]


def urllib_http(method: str, url: str, headers: dict, body: bytes, timeout: float = 20) -> tuple[int, bytes]:
    req = urllib.request.Request(url, body, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:   # noqa: S310 (fixed Google endpoints)
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def clean_addr(a: str) -> str:
    a = (a or "").strip()
    if not EMAIL_RE.match(a):
        raise Blocked(f"invalid email address: {a[:60]!r}")
    return a


def build_message(sender: str, to: str, reply_to: str, subject: str, body: str,
                  attachment: str | None, attach_name: str) -> EmailMessage:
    m = EmailMessage()
    m["To"], m["From"], m["Reply-To"] = clean_addr(to), clean_addr(sender), clean_addr(reply_to)
    m["Subject"] = re.sub(r"[\r\n]+", " ", subject).strip()[:200]
    m.set_content(body)
    if attachment and Path(attachment).is_file():
        ctype = mimetypes.guess_type(attachment)[0] or "application/octet-stream"
        main, _, sub = ctype.partition("/")
        ext = Path(attachment).suffix
        m.add_attachment(Path(attachment).read_bytes(), maintype=main, subtype=sub,
                         filename=re.sub(r"[^\w.-]", "_", attach_name) + ext)
    return m


class GmailSender:
    def __init__(self, secrets: SecretProvider | None = None, http: Http = urllib_http, clock=time.time):
        self.secrets, self.http, self.clock = secrets or EnvSecrets(), http, clock
        self._token: tuple[str, float] | None = None

    @property
    def configured(self) -> bool:
        return all(self.secrets.get(k) for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"))

    def _access_token(self, force: bool = False) -> str:
        if self._token and not force and self.clock() < self._token[1] - 60:
            return self._token[0]
        body = urllib.parse.urlencode({
            "client_id": self.secrets.get("GMAIL_CLIENT_ID"), "client_secret": self.secrets.get("GMAIL_CLIENT_SECRET"),
            "refresh_token": self.secrets.get("GMAIL_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode()
        try:
            status, raw = self.http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        except OSError as e:
            raise Transient(f"token endpoint unreachable: {e}") from e
        if status >= 500 or status == 429:
            raise Transient(f"token endpoint {status}")
        if status != 200:
            raise Blocked(f"OAuth refresh rejected ({status}); re-run scripts/gmail_auth.py")   # revoked/expired
        data = json.loads(raw)
        self._token = (data["access_token"], self.clock() + int(data.get("expires_in", 3600)))
        return self._token[0]

    def send(self, msg: EmailMessage, thread_id: str | None = None) -> str:
        """Returns the Gmail message id. Raises Transient / RateLimited / Blocked."""
        if not self.configured:
            raise Blocked("gmail not configured (GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN)")
        body = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
        if thread_id:
            body["threadId"] = thread_id
        payload = json.dumps(body).encode()
        for attempt in (1, 2):
            token = self._access_token(force=attempt == 2)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            try:
                status, raw = self.http("POST", SEND_URL, headers, payload)
            except OSError as e:
                if _never_sent(e):
                    raise Transient(f"connection failed before send: {e}") from e
                raise Blocked(f"ambiguous delivery, check Sent folder: {e}") from e   # timeout/reset: don't retry
            if status == 401 and attempt == 1:
                continue                                   # stale access token: refresh once, resend
            if 200 <= status < 300:
                return json.loads(raw).get("id", "")
            reason = _err_reason(raw)
            if status == 429 or (status == 403 and "ratelimit" in reason.lower().replace("_", "").replace(" ", "")):
                raise RateLimited("gmail")
            if status >= 500:
                raise Transient(f"gmail {status}")
            raise Blocked(f"gmail rejected send ({status}): {reason[:120]}")
        raise Blocked("gmail auth failed")


def _never_sent(e: OSError) -> bool:
    """True only for failures that provably happened before any bytes reached Gmail."""
    return isinstance(getattr(e, "reason", e), (ConnectionRefusedError, socket.gaierror))


def _err_reason(raw: bytes) -> str:
    try:
        e = json.loads(raw)["error"]
        return (e.get("errors") or [{}])[0].get("reason") or e.get("message", "")
    except Exception:
        return raw[:120].decode("utf-8", "replace")


# ---------------------------------------------------------------- inbox reading (gmail.readonly)
LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# Only job-related mail is even listed; everything else never leaves Google's servers.
# Two searches, because they fail differently. Application evidence is found by subject or by known application-system
# senders (so promotions that merely say "opportunity" can't crowd it out); recruiter mail by interview-ish wording.
# Neither is limited to the inbox: confirmations are often read and archived.
APPLIED_QUERY = ('-in:spam -in:trash -from:me newer_than:{days}d (subject:(application OR applying OR applied OR "thank you for applying") '
                 'OR from:(jobs-noreply@linkedin.com OR inmail-hit-reply@linkedin.com OR messages-noreply@linkedin.com OR greenhouse-mail.io '
                 'OR lever.co OR ashbyhq.com OR myworkday.com OR smartrecruiters.com OR icims.com OR jobvite.com OR successfactors.com OR workablemail.com))')
RECRUITER_QUERY = ('-in:spam -in:trash -from:me -category:promotions newer_than:{days}d (interview OR recruiter OR candidacy OR "your resume" '
                   'OR "next steps" OR "hiring team" OR calendly OR "schedule a call" OR "your availability" OR "job offer" OR "offer letter" '
                   'OR shortlisted OR "your profile")')
JOB_QUERY = RECRUITER_QUERY


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def extract_body(payload: dict) -> str:
    """Prefer text/plain; fall back to HTML->text. Walks nested multipart."""
    from .agents.feeds import html_to_text
    plain, html_ = [], []

    def walk(p: dict):
        mt, body = p.get("mimeType", ""), p.get("body", {}).get("data")
        if body and mt == "text/plain":
            plain.append(_b64(body))
        elif body and mt == "text/html":
            html_.append(_b64(body))
        for c in p.get("parts", []) or []:
            walk(c)

    walk(payload)
    return ("\n".join(plain) or html_to_text("\n".join(html_)))[:6000]


class GmailReader:
    def __init__(self, auth: "GmailSender"):
        self.auth = auth          # shares token refresh + HTTP transport with the sender

    def _get(self, url: str) -> dict:
        for attempt in (1, 2):
            token = self.auth._access_token(force=attempt == 2)
            try:
                status, raw = self.auth.http("GET", url, {"Authorization": f"Bearer {token}"}, b"")
            except OSError as e:
                raise Transient(f"gmail unreachable: {e}") from e
            if status == 401 and attempt == 1:
                continue
            if status == 403 and "insufficient" in raw.decode("utf-8", "replace").lower():
                raise Blocked("token lacks gmail.readonly - re-run scripts/gmail_auth.py and update GMAIL_REFRESH_TOKEN")
            if status == 429:
                raise RateLimited("gmail-read")
            if status >= 500:
                raise Transient(f"gmail {status}")
            if status != 200:
                raise Blocked(f"gmail read failed ({status}): {_err_reason(raw)[:100]}")
            return json.loads(raw)
        raise Blocked("gmail auth failed")

    def list_ids(self, days: int = 14, limit: int = 150) -> list[str]:
        ids = dict.fromkeys(self.search_ids(APPLIED_QUERY.format(days=days), limit))
        ids.update(dict.fromkeys(self.search_ids(RECRUITER_QUERY.format(days=days), limit)))
        return list(ids)

    def search_ids(self, query: str, limit: int = 5) -> list[str]:
        """Message ids matching a Gmail search in the user's own mailbox (newest first)."""
        ids, token = [], None
        while len(ids) < limit:                       # follow Gmail's pages instead of stopping at the first 50
            params = {"q": query, "maxResults": min(100, limit - len(ids))}
            if token:
                params["pageToken"] = token
            page = self._get(f"{LIST_URL}?{urllib.parse.urlencode(params)}")
            ids += [m["id"] for m in page.get("messages", [])]
            token = page.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def fetch(self, msg_id: str):
        from email.utils import parseaddr
        from datetime import datetime, timezone
        from .schemas import InboundEmail
        m = self._get(f"{LIST_URL}/{msg_id}?format=full")
        h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
        ts = int(m.get("internalDate", "0")) / 1000
        name, addr = parseaddr(h.get("from", ""))
        return InboundEmail(id=f"gmail:{msg_id}", sender=addr, sender_name=name, thread_id=m.get("threadId", ""),
                            subject=re.sub(r"[\r\n]+", " ", h.get("subject", ""))[:300],
                            body=extract_body(m.get("payload", {})),
                            received_at=datetime.fromtimestamp(ts, timezone.utc))


def _html_part(payload: dict) -> str:
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return _b64(payload["body"]["data"])
    for c in payload.get("parts", []) or []:
        h = _html_part(c)
        if h:
            return h
    return ""


def _reader_fetch_html(self, msg_id: str) -> tuple[str, str, str]:
    """(sender address, subject, raw html) - used by the alert parsers, which need link structure."""
    from email.utils import parseaddr
    m = self._get(f"{LIST_URL}/{msg_id}?format=full")
    h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
    return parseaddr(h.get("from", ""))[1], h.get("subject", ""), _html_part(m.get("payload", {}))


GmailReader.fetch_html = _reader_fetch_html


def _reader_headers(self, msg_id: str) -> dict:
    """Headers needed to reply in-thread, plus the thread id."""
    q = "&".join(f"metadataHeaders={h}" for h in ("Message-ID", "Subject", "From", "Reply-To", "References"))
    m = self._get(f"{LIST_URL}/{msg_id}?format=metadata&{q}")
    h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
    h["threadId"] = m.get("threadId", "")
    return h


def _reader_address(self) -> str:
    return self._get("https://gmail.googleapis.com/gmail/v1/users/me/profile").get("emailAddress", "")


GmailReader.headers = _reader_headers
GmailReader.address = _reader_address


def build_reply(sender: str, orig: dict, body: str) -> EmailMessage:
    from email.utils import parseaddr
    to = parseaddr(orig.get("reply-to") or orig.get("from", ""))[1]
    subj = orig.get("subject", "")
    m = EmailMessage()
    m["To"], m["From"] = clean_addr(to), clean_addr(sender)
    m["Subject"] = re.sub(r"[\r\n]+", " ", subj if subj.lower().startswith("re:") else f"Re: {subj}")[:250]
    mid = re.sub(r"[\r\n]", "", orig.get("message-id", ""))
    if mid:
        m["In-Reply-To"] = mid
        m["References"] = (re.sub(r"[\r\n]", " ", orig.get("references", "")) + " " + mid).strip()
    m.set_content(body)
    return m
