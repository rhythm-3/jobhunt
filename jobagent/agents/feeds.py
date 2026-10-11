"""Real job-board adapters (public, ToS-friendly APIs/feeds only - no scraping of logged-in sites)."""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from ..schemas import JobListing
from ..text import fingerprint
from ..tls import ssl_context

UA = {"User-Agent": "jobagent/0.1 (personal job search)"}
BLOCKS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0                      # inside <style>/<script>/<head>: not visible text

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        if tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s: str) -> str:
    """HTML -> plain text, one block per line (the JD parser is line-oriented)."""
    p = _Text()
    p.feed(html.unescape(s) if "&lt;" in s else s)
    text = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:   # noqa: S310
        return r.read()


def _job(source: str, ext_id: str, url: str, title: str, company: str, location: str, desc: str,
         remote: bool = True, apply_email: str | None = None) -> JobListing:
    return JobListing(id=f"{source}:{ext_id}", source=source, url=url, title=title.strip(), company=company.strip(),
                      location=location.strip(), remote=remote, description=html_to_text(desc), apply_email=apply_email,
                      fingerprint=fingerprint(title, company, ""))


class RemotiveSource:
    name = "remotive"

    def __init__(self, searches=("security", "detection engineer", "soar", "devsecops", "cloud security"), get=_get):
        self.searches, self.get = searches, get

    def fetch(self) -> list[JobListing]:
        out: dict[str, JobListing] = {}
        for q in self.searches:
            data = json.loads(self.get("https://remotive.com/api/remote-jobs?" +
                                       urllib.parse.urlencode({"search": q, "limit": 50})))
            for j in data.get("jobs", []):
                out[str(j["id"])] = _job(self.name, str(j["id"]), j["url"], j["title"], j["company_name"],
                                         j.get("candidate_required_location", ""), j.get("description", ""))
        return list(out.values())


class RemoteOKSource:
    """RemoteOK terms: link back to the listing and credit RemoteOK as the source - the URL we store does both."""
    name = "remoteok"

    def __init__(self, tags=("security", "infosec", "cyber-security", "devsecops"), get=_get):
        self.tags, self.get = tags, get

    def fetch(self) -> list[JobListing]:
        out: dict[str, JobListing] = {}
        for t in self.tags:
            data = json.loads(self.get("https://remoteok.com/api?tag=" + urllib.parse.quote(t)))
            for j in data:
                if "id" not in j or "position" not in j:      # first element is a legal notice
                    continue
                out[str(j["id"])] = _job(self.name, str(j["id"]), j.get("url") or j.get("apply_url", ""),
                                         j["position"], j.get("company", ""), j.get("location", ""),
                                         j.get("description", ""))
        return list(out.values())


class WWRSource:
    """We Work Remotely RSS. Titles look like 'Company: Role'."""
    def __init__(self, feed: str = "remote-devops-sysadmin-jobs", get=_get):
        self.name, self.url, self.get = "weworkremotely", f"https://weworkremotely.com/categories/{feed}.rss", get

    def fetch(self) -> list[JobListing]:
        root = ET.fromstring(self.get(self.url))
        out = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            company, sep, role = title.partition(": ")
            link = (it.findtext("link") or "").strip()
            out.append(_job(self.name, hashlib.sha1(link.encode()).hexdigest()[:12], link, role if sep else title,
                            company if sep else "unknown", it.findtext("region") or it.findtext("country") or "",
                            it.findtext("description") or ""))
        return out


SOFTWARE_WORDS = ("software", "developer", "backend", "back-end", "frontend", "front-end", "fullstack", "full-stack", "full stack",
                  "programmer", "python", "java", "sde", "web", "engineer")
SECURITY_WORDS = ("security", "detection", "soar", "threat", "incident", "soc", "devsecops", "infosec", "cyber")


def default_sources(titles=None):
    """Remote boards, searched for the user's own target titles (not a fixed field)."""
    qs = [t.lower() for t in (titles or []) if len(t) > 2][:4]
    if not qs:                                                        # no preferences yet: the original security defaults
        return [RemotiveSource(), RemoteOKSource(), WWRSource()]
    security = any(w in q for q in qs for w in SECURITY_WORDS)
    software = any(w in q for q in qs for w in SOFTWARE_WORDS) and not all(any(w in q for w in SECURITY_WORDS) for q in qs)
    tags = list(dict.fromkeys([q.replace(" ", "-") for q in qs] + (["dev", "backend"] if software else []) + (["security"] if security else [])))[:5]
    feeds = (["remote-back-end-programming-jobs", "remote-full-stack-programming-jobs"] if software else []) + \
            (["remote-devops-sysadmin-jobs"] if security or not software else [])
    return [RemotiveSource(searches=tuple(qs)), RemoteOKSource(tags=tuple(tags))] + [WWRSource(f) for f in feeds]


# ------------------------------------------------------------------ company career sites (public ATS APIs)
class GreenhouseSource:
    """boards-api.greenhouse.io - public, documented, meant for job-board consumption."""
    def __init__(self, slug: str, get=_get):
        self.slug, self.get, self.name = slug, get, f"greenhouse:{slug}"

    def fetch(self) -> list[JobListing]:
        d = json.loads(self.get(f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs?content=true"))
        company = self.slug.replace("-", " ").title()
        return [_job(self.name, str(j["id"]), j.get("absolute_url", ""), j.get("title", ""),
                     re.sub(r"\s+(?:job board|careers|jobs)$", "", j.get("company_name") or company, flags=re.I), (j.get("location") or {}).get("name", ""),
                     html.unescape(j.get("content", "")), remote="remote" in (j.get("location") or {}).get("name", "").lower())
                for j in d.get("jobs", [])]


class LeverSource:
    def __init__(self, slug: str, get=_get):
        self.slug, self.get, self.name = slug, get, f"lever:{slug}"

    def fetch(self) -> list[JobListing]:
        d = json.loads(self.get(f"https://api.lever.co/v0/postings/{self.slug}?mode=json"))
        out = []
        for j in d if isinstance(d, list) else []:
            cat = j.get("categories") or {}
            loc = cat.get("location", "")
            desc = (j.get("descriptionPlain") or "") + "\n" + "\n".join(
                f"{l.get('text', '')}\n" + html_to_text(l.get("content", "")) for l in j.get("lists", []))
            out.append(_job(self.name, j["id"], j.get("hostedUrl", ""), j.get("text", ""), self.slug.title(), loc,
                            desc, remote=(j.get("workplaceType") == "remote") or "remote" in loc.lower()))
        return out


class AshbySource:
    def __init__(self, slug: str, get=_get):
        self.slug, self.get, self.name = slug, get, f"ashby:{slug}"

    def fetch(self) -> list[JobListing]:
        d = json.loads(self.get(f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}"))
        return [_job(self.name, j["id"], j.get("jobUrl", ""), j.get("title", ""), self.slug.title(),
                     j.get("location", ""), j.get("descriptionHtml") or j.get("descriptionPlain", ""),
                     remote=bool(j.get("isRemote")))
                for j in d.get("jobs", [])]


ATS = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}
DEFAULT_WATCHLIST = ["greenhouse:rubrik", "greenhouse:twilio", "greenhouse:okta", "greenhouse:gitlab",
                     "greenhouse:databricks", "greenhouse:mongodb", "lever:meesho", "lever:zeta",
                     # security employers with open roles in India / remote-India
                     "greenhouse:zscaler", "greenhouse:netskope", "greenhouse:abnormalsecurity", "greenhouse:coinbase",
                     "greenhouse:commvault", "greenhouse:druva"]


def company_sources(watchlist: list[str]) -> list:
    out = []
    for entry in watchlist:
        ats, _, slug = entry.partition(":")
        if ats in ATS and re.fullmatch(r"[A-Za-z0-9-]{1,60}", slug or "") and (ats == "smartrecruiters" or slug == slug.lower()):
            out.append(ATS[ats](slug))
    return out


# ------------------------------------------------------------------ more remote boards (public JSON APIs)
def _queries(prefs_titles) -> list[str]:
    qs = [t for t in (prefs_titles or []) if len(t) > 2][:4]
    return qs or ["security"]


class HimalayasSource:
    """himalayas.app public API - remote jobs with explicit country eligibility (we ask for the user's country)."""
    name = "himalayas"

    def __init__(self, queries=("security",), country: str = "India", get=_get, pages: int = 2):
        self.queries, self.country, self.get, self.pages = list(queries), country, get, pages

    def fetch(self) -> list[JobListing]:
        out: dict[str, JobListing] = {}
        for q in self.queries:
            for page in range(self.pages):
                d = json.loads(self.get("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode(
                    {"q": q, "country": self.country, "limit": 20, "offset": page * 20})))
                jobs = d.get("jobs", [])
                for j in jobs:
                    locs = j.get("locationRestrictions") or []
                    loc = ", ".join(locs) if isinstance(locs, list) else str(locs)
                    url = j.get("applicationLink") or j.get("guid") or ""
                    out[url] = _job(self.name, hashlib.sha1(url.encode()).hexdigest()[:12], url, j.get("title", ""),
                                    j.get("companyName", ""), loc or "Worldwide", j.get("description") or j.get("excerpt", ""))
                if len(jobs) < 20:
                    break
        return list(out.values())


class JobicySource:
    """jobicy.com public API - remote jobs; geo 'anywhere' + 'apac' cover roles open to India."""
    name = "jobicy"

    def __init__(self, tags=("security",), geos=("anywhere", "apac"), get=_get):
        self.tags, self.geos, self.get = list(tags), list(geos), get

    def fetch(self) -> list[JobListing]:
        out: dict[str, JobListing] = {}
        for tag in self.tags:
            for geo in self.geos:
                d = json.loads(self.get("https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode({"count": 50, "geo": geo, "tag": tag})))
                for j in d.get("jobs", []):
                    out[str(j["id"])] = _job(self.name, str(j["id"]), j.get("url", ""), j.get("jobTitle", ""), j.get("companyName", ""),
                                             j.get("jobGeo", "Anywhere"), j.get("jobDescription", ""))
        return list(out.values())


class SmartRecruitersSource:
    """api.smartrecruiters.com public postings API (large employers: Bosch, Visa, ...). India filter by default."""
    def __init__(self, slug: str, country: str = "in", get=_get):
        self.slug, self.country, self.get, self.name = slug, country, get, f"smartrecruiters:{slug}"

    def fetch(self) -> list[JobListing]:
        d = json.loads(self.get(f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(self.slug)}/postings?"
                                + urllib.parse.urlencode({"limit": 100, "country": self.country})))
        out = []
        for p in d.get("content", []):
            loc = p.get("location") or {}
            where = ", ".join(x for x in (loc.get("city"), (loc.get("country") or "").upper()) if x)
            remote = bool(loc.get("remote"))
            url = f"https://jobs.smartrecruiters.com/{self.slug}/{p['id']}"
            dept = (p.get("department") or {}).get("label", "")
            out.append(_job(self.name, str(p["id"]), url, p.get("name", ""), (p.get("company") or {}).get("name", self.slug),
                            where + (", India" if "IN" in where and "India" not in where else ""), f"{p.get('name', '')}\n{dept}", remote=remote))
        return out


ATS["smartrecruiters"] = SmartRecruitersSource


def detect_ats(url: str) -> str | None:
    """Careers-page URL -> 'ats:slug' for the watchlist, or None if the site isn't a supported public job board."""
    u = urllib.parse.urlparse(url.strip() if "://" in url else "https://" + url.strip())
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    pats = [(r"(^|\.)greenhouse\.io$", "greenhouse"), (r"^jobs\.lever\.co$", "lever"), (r"^jobs\.ashbyhq\.com$", "ashby"),
            (r"^(jobs|careers)\.smartrecruiters\.com$", "smartrecruiters")]
    for rx, ats in pats:
        if re.search(rx, host) and parts:
            slug = parts[0].lower() if ats != "smartrecruiters" else parts[0]
            if ats == "greenhouse" and parts[0] in ("embed", "v1") and "for" in dict(urllib.parse.parse_qsl(u.query)):
                slug = dict(urllib.parse.parse_qsl(u.query))["for"]
            return f"{ats}:{slug}"
    return None


def remote_sources(titles) -> list:
    return [HimalayasSource(queries=_queries(titles)), JobicySource(tags=_queries(titles)[:2])]
