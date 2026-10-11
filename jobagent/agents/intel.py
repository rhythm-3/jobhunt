"""Open-source intelligence on employers - PUBLIC, PASSIVE sources only.

  * Full job descriptions: the same role on the company's own public job board (Greenhouse / Lever / Ashby /
    SmartRecruiters) or Himalayas. Sites that block automated access (Glassdoor, LinkedIn...) are never fetched.
  * Company profile: identity & logo (Clearbit autocomplete), summary (Wikipedia), hiring momentum (its job board),
    public DNS records (MX / SPF / DMARC via DNS-over-HTTPS), one homepage request (HSTS, CDN, stack hints),
    /.well-known/security.txt, public GitHub org, recent news (Google News RSS).
  * Never: individuals. No profiling of recruiters or employees, no email guessing, no scanning or probing.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from ..text import tokens
from ..tls import ssl_context
from .feeds import AshbySource, GreenhouseSource, HimalayasSource, LeverSource, SmartRecruitersSource, html_to_text

UA = {"User-Agent": "Mozilla/5.0 (JobAgent personal job search; +local)"}
TTL = 7 * 86400


def _get(url: str, timeout: float = 10, head: bool = False, limit: int = 600_000):
    req = urllib.request.Request(url, headers=UA, method="HEAD" if head else "GET")
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:   # noqa: S310 (public endpoints)
        return r.status, dict(r.headers), (b"" if head else r.read(limit))      # pages: capped; API JSON: see _json


def _json(url: str, timeout: float = 10):
    return json.loads(_get(url, timeout, limit=20_000_000)[2])


def norm(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(inc|ltd|llc|limited|pvt|private|corp|corporation|gmbh|plc|group|technologies|india)\b", "",
                                             (company or "").lower()))


# ------------------------------------------------------------------ job-description enrichment
def slug_candidates(company: str, domain: str | None = None) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (company or "").lower())
    words = [w for w in words if w not in ("inc", "ltd", "llc", "limited", "pvt", "private", "corp", "the", "co")]
    c = ["".join(words), "-".join(words), words[0] if words else ""]
    if domain:
        c.insert(0, domain.split(".")[0])
    return [s for s in dict.fromkeys(c) if len(s) > 1]


def _title_sim(a: str, b: str) -> float:
    A, B = set(tokens(a)), set(tokens(b))
    return len(A & B) / max(1, len(A | B))


def find_full_description(job, domain: str | None = None, deadline_s: float = 25) -> dict | None:
    """Look for the same role on the employer's public job board. Returns {description, url, source, similarity}."""
    t0 = time.time()
    best = None
    for slug in slug_candidates(job.company, domain):
        for src in (GreenhouseSource(slug), LeverSource(slug), AshbySource(slug), SmartRecruitersSource(slug.title() if "-" not in slug else slug)):
            if time.time() - t0 > deadline_s:
                break
            try:
                jobs = src.fetch()
            except Exception:   # noqa: BLE001 - board doesn't exist under this slug
                continue
            for j in jobs:
                s = _title_sim(job.title, j.title)
                if s >= 0.6 and len(j.description) > 300 and (not best or s > best["similarity"]):
                    best = {"description": j.description, "url": j.url, "source": src.name, "similarity": round(s, 2),
                            "location": j.location}
            if best and best["similarity"] >= 0.85:
                return best
    if not best:
        try:     # remote roles are often on Himalayas with a full description
            for j in HimalayasSource(queries=[job.title], pages=1).fetch():
                if norm(j.company) == norm(job.company) and _title_sim(job.title, j.title) >= 0.6:
                    best = {"description": j.description, "url": j.url, "source": "himalayas", "similarity": _title_sim(job.title, j.title)}
                    break
        except Exception:   # noqa: BLE001
            pass
    return best


# ------------------------------------------------------------------ company profile
def identity(company: str) -> dict:
    try:
        rows = _json("https://autocomplete.clearbit.com/v1/companies/suggest?query=" + urllib.parse.quote(company))
        want = norm(company)
        for r in rows:
            if norm(r.get("name", "")) == want or want in norm(r.get("name", "")) or norm(r.get("domain", "").split(".")[0]) == want:
                return {"name": r.get("name"), "domain": r.get("domain"), "logo": r.get("logo")}
    except Exception:   # noqa: BLE001
        pass
    return {}


def wiki(company: str) -> dict:
    try:
        s = _json("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": f"{company} company", "format": "json", "srlimit": 3}))
        for hit in s.get("query", {}).get("search", []):
            if set(re.findall(r"[a-z0-9]+", company.lower())) & set(re.findall(r"[a-z0-9]+", hit["title"].lower())):
                d = _json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(hit["title"].replace(" ", "_")))
                if d.get("type") == "standard":
                    return {"title": d.get("title"), "summary": d.get("extract", "")[:900],
                            "url": d.get("content_urls", {}).get("desktop", {}).get("page")}
    except Exception:   # noqa: BLE001
        pass
    return {}


def _dns(name: str, rtype: str) -> list[str]:
    try:
        d = _json(f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}", timeout=8)
        return [a.get("data", "").strip('"') for a in d.get("Answer", []) or []]
    except Exception:   # noqa: BLE001
        return []


MX_PROVIDERS = [("google", "Google Workspace"), ("outlook", "Microsoft 365"), ("pphosted", "Proofpoint"), ("mimecast", "Mimecast"),
                ("barracuda", "Barracuda"), ("messagelabs", "Broadcom/Symantec"), ("iphmx", "Cisco Secure Email"), ("zoho", "Zoho Mail")]
SPF_VENDORS = [("_spf.google.com", "Google"), ("spf.protection.outlook.com", "Microsoft 365"), ("sendgrid", "SendGrid"),
               ("mailgun", "Mailgun"), ("amazonses", "Amazon SES"), ("salesforce", "Salesforce"), ("hubspot", "HubSpot"),
               ("mktomail", "Marketo"), ("zendesk", "Zendesk"), ("pphosted", "Proofpoint"), ("mimecast", "Mimecast"),
               ("servicenow", "ServiceNow"), ("atlassian", "Atlassian"), ("workday", "Workday"), ("greenhouse", "Greenhouse")]
STACK = [(r"__NEXT_DATA__|/_next/", "Next.js"), (r"data-reactroot|react-dom", "React"), (r"ng-version|angular", "Angular"),
         (r"wp-content|wp-json", "WordPress"), (r"cdn\.shopify", "Shopify"), (r"googletagmanager", "Google Tag Manager"),
         (r"hs-scripts|hubspot", "HubSpot"), (r"marketo|mktoForms", "Marketo"), (r"optimizely", "Optimizely"),
         (r"onetrust|cookielaw", "OneTrust"), (r"segment\.com/analytics|cdn\.segment", "Segment"), (r"drift\.com", "Drift"),
         (r"intercom", "Intercom"), (r"cloudflare|cf-ray", "Cloudflare"), (r"akamai", "Akamai"), (r"fastly", "Fastly")]


def security_signals(domain: str) -> dict:
    """Passive, public signals only: DNS records + one homepage GET + security.txt."""
    out: dict = {"domain": domain}
    mx = " ".join(_dns(domain, "MX")).lower()
    out["mail"] = next((n for k, n in MX_PROVIDERS if k in mx), "custom / other" if mx else "none found")
    spf = next((t for t in _dns(domain, "TXT") if t.lower().startswith("v=spf1")), "")
    out["spf"] = bool(spf)
    out["spf_services"] = sorted({n for k, n in SPF_VENDORS if k in spf.lower()})
    dmarc = next((t for t in _dns("_dmarc." + domain, "TXT") if t.lower().startswith("v=dmarc1")), "")
    m = re.search(r"\bp=(\w+)", dmarc)
    out["dmarc"] = m.group(1).lower() if m else ("present" if dmarc else "missing")
    try:
        st, h, body = _get(f"https://{domain}/", timeout=10)
        hl = {k.lower(): v for k, v in h.items()}
        text = body.decode("utf-8", "replace")
        out["hsts"] = "strict-transport-security" in hl
        out["csp"] = "content-security-policy" in hl
        blob = text[:300_000] + " " + " ".join(f"{k}:{v}" for k, v in hl.items())
        out["stack"] = sorted({n for rx, n in STACK if re.search(rx, blob, re.I)})
    except Exception:   # noqa: BLE001
        out.update(hsts=None, csp=None, stack=[])
    try:
        st, h, body = _get(f"https://{domain}/.well-known/security.txt", timeout=8)
        out["security_txt"] = st == 200 and b"contact:" in body.lower()
    except urllib.error.HTTPError as e:
        out["security_txt"] = False if e.code in (404, 410) else None     # 403 etc. = the site refused: unknown, not "no"
    except Exception:   # noqa: BLE001
        out["security_txt"] = None
    return out


def github_org(company: str, domain: str | None) -> dict:
    for slug in slug_candidates(company, domain)[:3]:
        try:
            d = _json(f"https://api.github.com/orgs/{urllib.parse.quote(slug)}", timeout=8)
            blog = (d.get("blog") or "").lower()
            if domain and domain.split(".")[0] not in blog + d.get("login", "").lower() + (d.get("name") or "").lower():
                continue                                    # a same-named org belonging to someone else
            return {"login": d.get("login"), "name": d.get("name"), "repos": d.get("public_repos"), "followers": d.get("followers"),
                    "url": d.get("html_url")}
        except Exception:   # noqa: BLE001
            continue
    return {}


def news(company: str, limit: int = 6) -> list[dict]:
    try:
        st, h, body = _get("https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f'"{company}" when:60d', "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}), timeout=10)
        root = ET.fromstring(body)
        out = []
        for it in root.iter("item"):
            t = it.findtext("title") or ""
            src = (it.find("source").text if it.find("source") is not None else "")
            out.append({"title": re.sub(rf"\s+-\s+{re.escape(src)}$", "", t) if src else t, "source": src,
                        "date": it.findtext("pubDate") or "", "url": it.findtext("link") or ""})
            if len(out) >= limit:
                break
        return out
    except Exception:   # noqa: BLE001
        return []


def hiring(company: str, domain: str | None) -> dict:
    for slug in slug_candidates(company, domain):
        for src in (GreenhouseSource(slug), LeverSource(slug), AshbySource(slug)):
            try:
                jobs = src.fetch()
            except Exception:   # noqa: BLE001
                continue
            if jobs:
                sec = [j for j in jobs if re.search(r"secur|detection|soc\b|threat|incident|appsec|iam|grc", j.title, re.I)]
                india = [j for j in jobs if re.search(r"india|bengaluru|bangalore|hyderabad|pune|gurgaon|gurugram|mumbai|chennai|noida|remote", j.location, re.I)]
                return {"board": src.name, "open_roles": len(jobs), "security_roles": len(sec), "india_or_remote": len(india),
                        "security_titles": [j.title for j in sec[:8]]}
    return {}


def company_intel(store, company: str, force: bool = False) -> dict:
    key = f"intel:{norm(company)}"
    cached = store.kv_get(key)
    if cached and not force:
        d = json.loads(cached)
        if time.time() - d.get("fetched_at", 0) < TTL:
            return d
    ident = identity(company)
    domain = ident.get("domain")
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_wiki = ex.submit(wiki, company)
        f_sec = ex.submit(security_signals, domain) if domain else None
        f_gh = ex.submit(github_org, company, domain)
        f_news = ex.submit(news, company)
        f_hire = ex.submit(hiring, company, domain)
        d = {"company": company, "identity": ident, "about": f_wiki.result(), "security": f_sec.result() if f_sec else {},
             "github": f_gh.result(), "news": f_news.result(), "hiring": f_hire.result(), "fetched_at": time.time()}
    store.kv_set(key, json.dumps(d))
    if domain:
        store.kv_set(f"domain:{norm(company)}", domain)
    return d


# ------------------------------------------------------------------ description from a link the user pastes
BLOCKED_HOSTS = ("linkedin.", "glassdoor.", "naukri.", "indeed.", "foundit.", "monster.", "shine.com", "instahyre.")


def _jsonld_jobposting(html: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:   # noqa: BLE001
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return d
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
            elif isinstance(d, list):
                stack.extend(d)
    return None


def description_from_link(url: str) -> dict:
    """Full description for one specific job page. Uses the site's public API where there is one, else the
    schema.org JobPosting data career sites embed for Google Jobs. One request; refuses account-based job boards."""
    u = urllib.parse.urlparse(url.strip())
    host = u.netloc.lower()
    if u.scheme not in ("http", "https") or not host:
        raise ValueError("paste a full link starting with https://")
    if any(b in host for b in BLOCKED_HOSTS):
        raise ValueError("that's a job board with personal accounts (LinkedIn, Glassdoor, Naukri…) - paste the link from the company's own careers site instead")
    parts = [p for p in u.path.split("/") if p]
    qs = dict(urllib.parse.parse_qsl(u.query))
    if "gh_jid" in qs and qs["gh_jid"].isdigit():        # Greenhouse job embedded on the company's own site
        root = host.removeprefix("www.").split(".")[0]
        for slug in dict.fromkeys([root, root.replace("-", "")]):
            try:
                d = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{qs['gh_jid']}")
                return {"title": d.get("title", ""), "company": slug, "location": (d.get("location") or {}).get("name", ""),
                        "description": html_to_text(__import__("html").unescape(d.get("content", ""))), "source": f"greenhouse:{slug}"}
            except Exception:   # noqa: BLE001
                continue
    # Greenhouse: boards.greenhouse.io/{slug}/jobs/{id}  |  job-boards.greenhouse.io/{slug}/jobs/{id}
    if re.search(r"(^|\.)greenhouse\.io$", host) and "jobs" in parts:
        slug, jid = parts[0], parts[parts.index("jobs") + 1]
        d = _json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
        return {"title": d.get("title", ""), "company": slug, "description": html_to_text(__import__("html").unescape(d.get("content", ""))),
                "location": (d.get("location") or {}).get("name", ""), "source": f"greenhouse:{slug}"}
    if host == "jobs.lever.co" and len(parts) >= 2:
        d = _json(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")
        desc = (d.get("descriptionPlain") or "") + "\n" + "\n".join(f"{l.get('text', '')}\n" + html_to_text(l.get("content", "")) for l in d.get("lists", []))
        return {"title": d.get("text", ""), "company": parts[0], "description": desc,
                "location": (d.get("categories") or {}).get("location", ""), "source": f"lever:{parts[0]}"}
    # Workday career sites: {tenant}.wdN.myworkdayjobs.com/[lang/]{site}/job/{...}
    if host.endswith(".myworkdayjobs.com") and "job" in parts:
        tenant = host.split(".")[0]
        i = parts.index("job")
        site = parts[i - 1]
        d = _json(f"https://{host}/wday/cxs/{tenant}/{site}/{'/'.join(parts[i:])}")
        info = d.get("jobPostingInfo", {})
        return {"title": info.get("title", ""), "company": (d.get("hiringOrganization") or {}).get("name", tenant),
                "description": html_to_text(info.get("jobDescription", "")), "location": info.get("location", ""),
                "source": f"workday:{tenant}"}
    try:
        st, h, body = _get(url, timeout=15)
    except urllib.error.HTTPError as e:
        raise ValueError(f"that site refused an automated read (HTTP {e.code}) - open the job in your browser and copy the description into the cover-letter notes instead") from e
    jp = _jsonld_jobposting(body.decode("utf-8", "replace"))
    if not jp or not jp.get("description"):
        raise ValueError("couldn't find job details on that page - open the specific job (not the careers home page) and paste its link")
    loc = jp.get("jobLocation")
    loc = loc[0] if isinstance(loc, list) and loc else loc
    addr = (loc or {}).get("address", {}) if isinstance(loc, dict) else {}
    where = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else "") if x)
    org = jp.get("hiringOrganization") or {}
    return {"title": jp.get("title", ""), "company": org.get("name", "") if isinstance(org, dict) else str(org),
            "description": html_to_text(__import__("html").unescape(jp["description"])), "location": where, "source": f"link:{host}"}
