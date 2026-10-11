"""Jobs from the user's own job-alert emails (Glassdoor, Naukri, LinkedIn alerts, recruiter invites).

This is how LinkedIn/Naukri/Glassdoor listings get in WITHOUT scraping those sites: the user already subscribed
to these alerts, and we only read their own mailbox (gmail.readonly). Listings link back to the board, where the
human applies (assisted pre-fill is disabled on those domains to protect the user's account).
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import re
import urllib.parse
from html.parser import HTMLParser

from ..schemas import JobListing
from ..text import fingerprint
from .feeds import html_to_text

ALERT_QUERY = ("newer_than:{days}d (from:noreply@glassdoor.com OR from:naukri.com OR from:jobalerts-noreply@linkedin.com "
               "OR from:jobs-listings@linkedin.com OR from:instahyre.com OR from:alerts.resume.io)")


class _Anchors(HTMLParser):
    """Collect <a href> with the separate text segments inside each anchor."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list | None = None
        self.out: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.stack = [dict(attrs).get("href", ""), []]

    def handle_data(self, data):
        if self.stack is not None and data.strip():
            self.stack[1].append(" ".join(data.split()))

    def handle_endtag(self, tag):
        if tag == "a" and self.stack is not None:
            self.out.append((htmlmod.unescape(self.stack[0]), self.stack[1]))
            self.stack = None


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def parse_glassdoor(html: str) -> list[JobListing]:
    """Each job card is one <a> to /partner/jobListing.htm whose text segments are
    [company, 'rating ★', title, location, '₹salary (Glassdoor Est.)', ('Easy Apply'), age]."""
    p = _Anchors(); p.feed(html)
    jobs = []
    for href, segs in p.out:
        if "jobListing.htm" not in href or len(segs) < 3:
            continue
        segs = [s for s in segs if s.lower() != "easy apply"]
        i = 1 + (1 if len(segs) > 1 and "★" in segs[1] else 0)
        company, title = segs[0], segs[i] if i < len(segs) else ""
        location = segs[i + 1] if i + 1 < len(segs) and "₹" not in segs[i + 1] else ""
        salary = next((s for s in segs if "₹" in s or "$" in s), "")
        rm = re.search(r"(\d(?:\.\d)?)\s*★", " ".join(segs[:3]))
        if not title:
            continue
        jobs.append(JobListing(id=f"glassdoor:{_id(company, title, location)}", source="glassdoor", url=href,
                               title=title, company=company, location=location, remote="remote" in location.lower(),
                               description=f"{title}\n{company}\n{location}\n{salary}".strip(),
                               fingerprint=fingerprint(title, company, ""), rating=float(rm.group(1)) if rm else None))
    return jobs


NAUKRI_SUBJECT = re.compile(r"Job \| (?P<title>.+?) in (?:(?P<company>[^\[\]]+?) - )?\[?(?P<loc>[^\]|]+)\]?\s*(?:\||$)")


def parse_naukri_invite(html: str, subject: str) -> list[JobListing]:
    """Recruiter 'Nvite' mails: labelled lines after 'Posted by', then a full 'Job description' section."""
    text = html_to_text(html)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    try:
        k = next(i for i, l in enumerate(lines) if l.lower().startswith("posted by"))
    except StopIteration:
        return []
    poster = lines[k][len("posted by"):].strip()
    title = lines[k + 1] if k + 1 < len(lines) else ""
    loc = lines[k + 2] if k + 2 < len(lines) else ""
    m = NAUKRI_SUBJECT.search(subject or "")
    hiring_for = next((l.split("Hiring for", 1)[1].strip() for l in lines[:k] if l.startswith("Hiring for")), "")
    if hiring_for.lower().endswith("industry"):
        hiring_for = ""                        # "Hiring for IT Services & Consulting industry" names a sector, not a company
    company = (m.group("company") if m and m.group("company") else "") or hiring_for or poster
    try:
        s = next(i for i, l in enumerate(lines) if l.lower().startswith("job description"))
        e = next((i for i, l in enumerate(lines[s + 1:], s + 1) if l.lower().startswith(("industry type", "what you get"))), len(lines))
        desc = "\n".join(lines[s + 1:e])
    except StopIteration:
        desc = ""
    meta = "\n".join(lines[k + 3:k + 7])       # experience, salary, work mode, key skills
    p = _Anchors(); p.feed(html)
    url = next((h for h, segs in p.out if "apply" in h.lower() and "naukri" in h.lower()), "https://www.naukri.com/")
    if not title:
        return []
    return [JobListing(id=f"naukri:{_id(title, company, loc)}", source="naukri", url=url, title=title,
                       company=company, location=loc, remote="remote" in (loc + meta).lower(),
                       description=f"{meta}\n{desc}".strip(), fingerprint=fingerprint(title, company, ""))]


def parse_linkedin_alert(html: str) -> list[JobListing]:
    """LinkedIn job-alert mails: anchors to /jobs/view/<id> with [title, company · location] segments."""
    p = _Anchors(); p.feed(html)
    seen, jobs = set(), []
    for href, segs in p.out:
        m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", href)
        if not m or m.group(1) in seen or not segs:
            continue
        seen.add(m.group(1))
        title = segs[0]
        rest = " · ".join(segs[1:])
        company, _, location = rest.partition(" · ")
        jobs.append(JobListing(id=f"linkedin:{m.group(1)}", source="linkedin",
                               url=f"https://www.linkedin.com/jobs/view/{m.group(1)}/", title=title,
                               company=company or "unknown", location=location,
                               remote="remote" in location.lower(), description=f"{title}\n{rest}",
                               fingerprint=fingerprint(title, company, "")))
    return [j for j in jobs if j.company != "unknown" or len(jobs) == 1]


def parse_alert(sender: str, subject: str, html: str) -> list[JobListing]:
    s = sender.lower()
    if "glassdoor" in s:
        return parse_glassdoor(html)
    if "naukri" in s and "Job |" in (subject or ""):
        return parse_naukri_invite(html, subject)
    if "linkedin" in s:
        return parse_linkedin_alert(html)
    return []


class GmailAlertSource:
    """JobSource over the user's alert emails. Each email is parsed once (tracked in kv)."""
    name = "gmail-alerts"

    def __init__(self, reader, store, days: int = 14, limit: int = 60):
        self.reader, self.store, self.days, self.limit = reader, store, days, limit

    def fetch(self) -> list[JobListing]:
        from ..mail import LIST_URL
        q = urllib.parse.urlencode({"q": ALERT_QUERY.format(days=self.days), "maxResults": self.limit})
        jobs: list[JobListing] = []
        for m in self.reader._get(f"{LIST_URL}?{q}").get("messages", []):
            key = f"alertseen:{m['id']}"
            if self.store.kv_get(key):
                continue
            sender, subject, html = self.reader.fetch_html(m["id"])
            jobs.extend(parse_alert(sender, subject, html))
            self.store.kv_set(key, "1")
        return jobs
