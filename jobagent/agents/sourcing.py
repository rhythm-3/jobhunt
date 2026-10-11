"""Sourcing Agent: pluggable adapters -> normalize -> filter -> cross-board dedup."""
from __future__ import annotations

import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from typing import Protocol

from ..db import Store
from ..tls import ssl_context
from ..schemas import AuditEvent, CandidateProfile, JobListing
from ..text import fingerprint


INDIA_CITIES = {"india", "bengaluru", "bangalore", "mumbai", "delhi", "pune", "hyderabad", "chennai", "gurgaon",
                "gurugram", "noida", "lucknow", "kolkata", "ahmedabad", "kochi", "jaipur", "chandigarh"}


class JobSource(Protocol):
    name: str
    def fetch(self) -> list[JobListing]: ...


class RSSSource:
    """Generic RSS/Atom adapter. Respects a hard timeout and never raises into the orchestrator."""
    def __init__(self, name: str, url: str, timeout: float = 10):
        self.name, self.url, self.timeout = name, url, timeout

    def fetch(self) -> list[JobListing]:
        req = urllib.request.Request(self.url, headers={"User-Agent": "jobagent/0.1 (+personal use)"})
        with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context()) as r:   # noqa: S310 (operator-configured URL)
            root = ET.fromstring(r.read())
        out = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            company, _, role = title.partition(":") if ":" in title else ("unknown", "", title)
            link = (it.findtext("link") or "").strip()
            desc = (it.findtext("description") or "").strip()
            out.append(JobListing(id=f"{self.name}:{__import__('hashlib').sha1(link.encode()).hexdigest()[:12]}", source=self.name, url=link,
                                  title=role.strip(), company=company.strip(), description=desc,
                                  remote="remote" in (title + desc).lower(),
                                  fingerprint=fingerprint(role, company)))
        return out


class FixtureSource:
    """Offline demo source so the system runs end-to-end without network access."""
    name = "fixtures"

    def fetch(self) -> list[JobListing]:
        from ..fixtures import SAMPLE_JOBS
        return [JobListing(**{**j, "fingerprint": fingerprint(j["title"], j["company"], j.get("location", ""))})
                for j in SAMPLE_JOBS]


def passes_filters(job: JobListing, profile: CandidateProfile) -> str | None:
    """Return a rejection reason, or None if the job is acceptable."""
    p = profile.preferences
    prefs = profile.prefs
    text = f"{job.title} {job.description}".lower()
    for co in prefs.exclude_companies:
        if co.strip() and co.lower().strip() in job.company.lower():
            return f"excluded company: {co}"
    from ..salary import parse_salary
    sal = parse_salary(f"{job.title}\n{job.description}")
    if prefs.min_salary_lpa and sal and sal["currency"] == "INR" and sal["max"] < prefs.min_salary_lpa:
        return f"salary below {prefs.min_salary_lpa:g} LPA"
    mode = "remote" if job.remote else ("hybrid" if "hybrid" in f"{job.location} {text[:600]}" else "onsite")
    if mode not in prefs.work_modes:
        return f"work mode {mode} not wanted"
    for bad in p.get("exclude_keywords", []):
        if bad.lower() in text:
            return f"excluded keyword: {bad}"
    if p.get("remote_only") and not job.remote:
        return "not remote"
    where = re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFKD", job.location))   # Hyderābād -> Hyderabad
    where = re.sub(r"\bremote\b|\(|\)|,", " ", where.lower()).strip()   # bare "Remote" = unspecified
    if where:
        ok = {w.lower() for loc in p.get("target_locations", []) for w in re.findall(r"[A-Za-z]{3,}", loc)
              if w.lower() not in ("remote",)} | {"worldwide", "anywhere", "global", "apac", "asia", "emea"}
        if any("india" in l.lower() for l in p.get("target_locations", [])):
            ok |= INDIA_CITIES
        if p.get("target_locations") and not any(w in where for w in ok):
            if job.remote:
                return f"remote but restricted to: {job.location[:40]}"
            return f"on-site outside targets: {job.location[:40]}"
    roles = [r.lower() for r in p.get("target_titles", [])]
    if roles and not any(r in job.title.lower() for r in roles):
        return "title outside targets"
    return None


def run_sourcing(store: Store, sources: list[JobSource], profile: CandidateProfile, stats: dict | None = None) -> list[JobListing]:
    new: list[JobListing] = []
    for src in sources:
        try:
            jobs = src.fetch()
        except Exception as e:   # one broken board must not stop the others
            store.audit(AuditEvent(run_id=None, actor="sourcing", event="source_failed",
                                   detail={"source": src.name, "error": repr(e)}))
            continue
        st = stats.setdefault(src.name, {"fetched": 0, "matched": 0, "new": 0}) if stats is not None else None
        if st:
            st["fetched"] = len(jobs)
        for j in jobs:
            reason = passes_filters(j, profile)
            if not reason and st:
                st["matched"] += 1
            if reason:
                store.audit(AuditEvent(run_id=None, actor="sourcing", event="filtered",
                                       detail={"job": j.id, "reason": reason}))
            elif store.add_job(j):
                new.append(j)
                if st:
                    st["new"] += 1
    store.audit(AuditEvent(run_id=None, actor="sourcing", event="sweep_complete", detail={"new": len(new)}))
    return new
