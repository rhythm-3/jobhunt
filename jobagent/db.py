"""Persistence layer (SQLite for dev; schema maps 1:1 onto Postgres + pgvector in prod)."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Iterable

from .schemas import ApplicationRun, AuditEvent, InboundEmail, Interview, JobListing, Contact, Offer, Outreach, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL,
  doc TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, run_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, actor TEXT,
  event TEXT, detail TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(run_id TEXT PRIMARY KEY, node TEXT, state TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS rate_events(bucket TEXT, at REAL);
CREATE INDEX IF NOT EXISTS rate_bucket ON rate_events(bucket, at);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS interviews(id TEXT PRIMARY KEY, run_id TEXT, starts_at TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offers(id TEXT PRIMARY KEY, run_id TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outreach(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
"""


class _Rows(list):
    def fetchone(self):
        return self[0] if self else None


class Store:
    def __init__(self, path: str = "jobagent.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def _x(self, sql: str, args: Iterable = ()) -> "_Rows":
        # Rows are fully read while the lock is held: the connection is shared by the API threads and the
        # background workers, and a lazily-iterated cursor can otherwise be reset by another thread's query.
        with self._lock:
            return _Rows(self._conn.execute(sql, tuple(args)).fetchall())

    # jobs
    def add_job(self, job: JobListing) -> bool:
        """Returns False when the fingerprint already exists (dedup)."""
        try:
            self._x("INSERT INTO jobs VALUES(?,?,?)", (job.id, job.fingerprint, job.model_dump_json()))
            return True
        except sqlite3.IntegrityError:
            return False

    def update_job(self, job: JobListing) -> None:
        self._x("UPDATE jobs SET doc=? WHERE id=?", (job.model_dump_json(), job.id))

    def job_by_fingerprint(self, fp: str) -> JobListing | None:
        r = self._x("SELECT doc FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
        return JobListing.model_validate_json(r["doc"]) if r else None

    def get_job(self, job_id: str) -> JobListing | None:
        r = self._x("SELECT doc FROM jobs WHERE id=?", (job_id,)).fetchone()
        return JobListing.model_validate_json(r["doc"]) if r else None

    # runs
    def save_run(self, run: ApplicationRun) -> None:
        run.updated_at = utcnow()
        self._x("INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
                "doc=excluded.doc,updated_at=excluded.updated_at",
                (run.id, run.job_id, run.status.value, run.model_dump_json(), run.updated_at.isoformat()))

    def get_run(self, run_id: str) -> ApplicationRun | None:
        r = self._x("SELECT doc FROM runs WHERE id=?", (run_id,)).fetchone()
        return ApplicationRun.model_validate_json(r["doc"]) if r else None

    def list_runs(self, status: str | None = None) -> list[ApplicationRun]:
        q, a = ("SELECT doc FROM runs WHERE status=? ORDER BY updated_at DESC", (status,)) if status \
            else ("SELECT doc FROM runs ORDER BY updated_at DESC", ())
        return [ApplicationRun.model_validate_json(r["doc"]) for r in self._x(q, a)]

    def jobs_without_runs(self) -> list[JobListing]:
        return [JobListing.model_validate_json(r["doc"]) for r in
                self._x("SELECT doc FROM jobs WHERE id NOT IN (SELECT job_id FROM runs)")]

    def run_for_job(self, job_id: str) -> ApplicationRun | None:
        r = self._x("SELECT doc FROM runs WHERE job_id=?", (job_id,)).fetchone()
        return ApplicationRun.model_validate_json(r["doc"]) if r else None

    # inbox
    def save_email(self, m: InboundEmail) -> None:
        self._x("INSERT OR REPLACE INTO inbox VALUES(?,?,?)", (m.id, m.run_id, m.model_dump_json()))

    def list_emails(self) -> list[InboundEmail]:
        return [InboundEmail.model_validate_json(r["doc"])
                for r in self._x("SELECT doc FROM inbox ORDER BY rowid DESC")]

    def has_email(self, mid: str) -> bool:
        return self._x("SELECT 1 FROM inbox WHERE id=?", (mid,)).fetchone() is not None

    # audit (append-only)
    def audit(self, ev: AuditEvent) -> None:
        self._x("INSERT INTO audit(run_id,actor,event,detail,at) VALUES(?,?,?,?,?)",
                (ev.run_id, ev.actor, ev.event, json.dumps(ev.detail, default=str), ev.at.isoformat()))

    def audit_log(self, run_id: str | None = None, limit: int = 200) -> list[dict]:
        q, a = ("SELECT * FROM audit WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)) if run_id \
            else ("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in self._x(q, a)]

    # checkpoints
    def save_checkpoint(self, run_id: str, node: str, state: dict) -> None:
        self._x("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)",
                (run_id, node, json.dumps(state, default=str), utcnow().isoformat()))

    def load_checkpoint(self, run_id: str) -> tuple[str, dict] | None:
        r = self._x("SELECT node,state FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
        return (r["node"], json.loads(r["state"])) if r else None

    # rate limiting (sliding window)
    def rate_count(self, bucket: str, window_s: float, now: float) -> int:
        return self._x("SELECT COUNT(*) c FROM rate_events WHERE bucket=? AND at>?",
                       (bucket, now - window_s)).fetchone()["c"]

    def rate_add(self, bucket: str, now: float) -> None:
        self._x("INSERT INTO rate_events VALUES(?,?)", (bucket, now))

    # kv
    def kv_get(self, k: str, default: str | None = None) -> str | None:
        r = self._x("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    # contacts (people you know at companies)
    def save_contact(self, c: Contact) -> None:
        self._x("INSERT OR REPLACE INTO contacts VALUES(?,?)", (c.id, c.model_dump_json()))

    def get_contact(self, cid: str) -> Contact | None:
        r = self._x("SELECT doc FROM contacts WHERE id=?", (cid,)).fetchone()
        return Contact.model_validate_json(r["doc"]) if r else None

    def list_contacts(self) -> list[Contact]:
        return sorted((Contact.model_validate_json(r["doc"]) for r in self._x("SELECT doc FROM contacts")), key=lambda c: (c.company.lower(), c.name.lower()))

    def delete_contact(self, cid: str) -> None:
        self._x("DELETE FROM contacts WHERE id=?", (cid,))

    def pulse(self) -> str:
        """A cheap fingerprint of everything list screens show; changes whenever a job, application or email does."""
        r = self._x("SELECT (SELECT COUNT(*) || ':' || IFNULL(MAX(updated_at),'') || ':' || IFNULL(SUM(LENGTH(status)),0) FROM runs) AS a, "
                    "(SELECT COUNT(*) || ':' || IFNULL(SUM(LENGTH(doc)),0) FROM inbox) AS b, "
                    "(SELECT COUNT(*) || ':' || IFNULL(SUM(LENGTH(doc)),0) FROM jobs) AS c").fetchone()
        return f"{r['a']}|{r['b']}|{r['c']}"

    def kv_set(self, k: str, v: str) -> None:
        self._x("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, v))

    # interviews
    def save_interview(self, iv: Interview) -> None:
        self._x("INSERT OR REPLACE INTO interviews VALUES(?,?,?,?)", (iv.id, iv.run_id, iv.starts_at.isoformat(), iv.model_dump_json()))

    def get_interview(self, iid: str) -> Interview | None:
        r = self._x("SELECT doc FROM interviews WHERE id=?", (iid,)).fetchone()
        return Interview.model_validate_json(r["doc"]) if r else None

    def list_interviews(self) -> list[Interview]:
        return [Interview.model_validate_json(r["doc"]) for r in self._x("SELECT doc FROM interviews ORDER BY starts_at")]

    def delete_interview(self, iid: str) -> None:
        self._x("DELETE FROM interviews WHERE id=?", (iid,))

    # offers
    def save_offer(self, o: Offer) -> None:
        self._x("INSERT OR REPLACE INTO offers VALUES(?,?,?)", (o.id, o.run_id, o.model_dump_json()))

    def get_offer(self, oid: str) -> Offer | None:
        r = self._x("SELECT doc FROM offers WHERE id=?", (oid,)).fetchone()
        return Offer.model_validate_json(r["doc"]) if r else None

    def list_offers(self) -> list[Offer]:
        # INSERT OR REPLACE gives an edited row a new rowid, so order by creation time to keep columns stable
        return sorted((Offer.model_validate_json(r["doc"]) for r in self._x("SELECT doc FROM offers")), key=lambda o: o.created_at)

    def delete_offer(self, oid: str) -> None:
        self._x("DELETE FROM offers WHERE id=?", (oid,))

    # outreach (emails to people at companies)
    def save_outreach(self, o: Outreach) -> None:
        self._x("INSERT OR REPLACE INTO outreach VALUES(?,?)", (o.id, o.model_dump_json()))

    def get_outreach(self, oid: str) -> Outreach | None:
        r = self._x("SELECT doc FROM outreach WHERE id=?", (oid,)).fetchone()
        return Outreach.model_validate_json(r["doc"]) if r else None

    def list_outreach(self) -> list[Outreach]:
        return sorted((Outreach.model_validate_json(r["doc"]) for r in self._x("SELECT doc FROM outreach")), key=lambda o: o.created_at, reverse=True)

    def delete_outreach(self, oid: str) -> None:
        self._x("DELETE FROM outreach WHERE id=?", (oid,))
