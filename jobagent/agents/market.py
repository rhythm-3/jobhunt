"""Job-level and market-level analysis: "should I apply?" verdict, keyword report, salary explorer, LinkedIn review.

Everything here is deterministic and grounded: verdicts cite the posting and the profile, salary figures come only from
salaries stated in listings the app has seen, and LinkedIn rewrites are assembled from the user's own profile text.
"""
from __future__ import annotations

import re
import statistics
import urllib.parse
from datetime import date

from ..schemas import CandidateProfile, JobListing
from ..text import ALIASES, tokens
from ..text import TECH
from .career import TOOL_TERMS, disp

# concept words that count as keywords even though they aren't tool names; everyday words ("team", "world") never do
CONCEPTS = set("""backend frontend fullstack full-stack microservices distributed scalability scalable architecture api apis rest restful grpc
graphql database databases sql nosql cloud serverless infrastructure devops ci/cd automation testing tdd agile scrum security authentication
authorization oauth sso iam encryption compliance monitoring observability logging performance optimization concurrency caching queue
streaming pipeline pipelines etl analytics ml ai llm rag nlp mobile web ui ux accessibility debugging refactoring mentoring leadership
detection incident threat vulnerability soc siem soar forensics malware phishing networking linux unix containers virtualization
algorithms oop saas platform reliability sre deployment integration migration""".split())


SHORT_CAPS = set("ai ml ui ux api apis aws gcp s3 ec2 ecs eks sns sqs sql sso iam soc sre etl nlp tdd oop edr xdr kql spl llm rag cdn dns tcp vpn jvm sdk cli css html".split())


def show(t: str) -> str:
    """Display form: short codes are capitals (AI, S3, AWS); the rest use the shared display names."""
    d = disp(t)
    if t in SHORT_CAPS:
        return t.upper()
    return {"ebpf": "eBPF", "go": "Go", "golang": "Go", "k8s": "Kubernetes"}.get(t, d)


def meaningful(t: str, extra: set[str] = frozenset()) -> bool:
    return t in TECH or t in TOOL_TERMS or t in CONCEPTS or t in extra

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


# ---------------------------------------------------------------- experience
def _ym(s: str, today: date) -> tuple[int, int] | None:
    s = (s or "").strip().lower()
    if not s or re.search(r"present|current|now|today|ongoing", s):
        return today.year, today.month
    y = re.search(r"(19|20)\d{2}", s)
    if not y:
        return None
    m = next((n for k, n in MONTHS.items() if k in s), 1)
    return int(y.group(0)), m


def years_of_experience(p: CandidateProfile, today: date | None = None) -> float:
    """Total months across roles (overlaps counted once), in years."""
    today = today or date.today()
    months: set[int] = set()
    for e in p.experience:
        a, b = _ym(e.start, today), _ym(e.end, today)
        if not a or not b:
            continue
        months.update(range(a[0] * 12 + a[1], b[0] * 12 + b[1] + 1))
    return round(len(months) / 12, 1)


def years_asked(text: str) -> int | None:
    """Smallest 'N+ years' the posting asks for (ignores company-age and benefit sentences as best it can)."""
    hits = []
    for m in re.finditer(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(?:\d{1,2}\s*)?(?:years?|yrs?)\b([^.\n]{0,14})", text or "", re.I):
        tail = m.group(2).lower()
        n = int(m.group(1))
        if 0 < n <= 20 and not re.search(r"old|in business|history|anniversar|warranty", tail):
            hits.append(n)
    return min(hits) if hits else None


# ---------------------------------------------------------------- verdict
def verdict(p: CandidateProfile, job: JobListing, reqs, parts: dict, score: float, filter_reason: str | None,
            salary: dict | None, adaptation=None) -> dict:
    have_years, want_years = years_of_experience(p), years_asked(f"{job.title}\n{job.description}")
    blockers, cautions, strengths = [], [], []
    if filter_reason:
        blockers.append({"salary below": "The stated pay is below your minimum.", "excluded": "You excluded this company or keyword."}.get(
            next((k for k in ("salary below", "excluded") if k in filter_reason), ""), f"Outside your preferences: {filter_reason}."))
    if want_years:
        gap = want_years - have_years
        if gap >= 3:
            blockers.append(f"Asks for {want_years}+ years; you have about {have_years:g}.")
        elif gap >= 1:
            cautions.append(f"Asks for {want_years}+ years; you have about {have_years:g}. Worth a try if the rest fits.")
        elif gap > 0:
            strengths.append(f"Close to the experience asked ({want_years}+ years; you have about {have_years:g}).")
        else:
            strengths.append(f"You meet the experience asked ({want_years}+ years; you have about {have_years:g}).")
    if reqs.seniority == "staff" and have_years < 6:
        cautions.append("Staff/Principal level: these usually expect 8+ years.")
    skill_words = {t for sk in p.skills for t in tokens(sk)}
    pool = list(dict.fromkeys(list(reqs.must_have) + list(reqs.nice_to_have) + list(reqs.keywords)))
    matched = [k for k in pool if k in _have(p) and meaningful(k, skill_words)]
    missing = [k for k in pool if k not in _have(p) and meaningful(k)]
    if matched:
        strengths.append("You cover " + ", ".join(show(k) for k in matched[:5]) + (f" and {len(matched) - 5} more" if len(matched) > 5 else "") + ".")
    if parts.get("similarity", 0) >= 0.66:
        strengths.append("The role reads close to your background.")
    if missing:
        cautions.append("Not in your profile: " + ", ".join(show(k) for k in missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "") + ".")
    if len(job.description or "") < 600:
        cautions.append("Only a short description is available, so this is a rough read.")
    if salary and salary.get("currency") == "INR":
        strengths.append(f"Pay is stated: {salary['label']}.")
    if blockers:
        call, why = "skip", "There's a deal-breaker."
    elif score >= 0.5 and len(cautions) <= 2:
        call, why = "apply", "Strong fit with no deal-breakers."
    elif score >= 0.35:
        call, why = "maybe", "A partial fit — apply if the company matters to you."
    else:
        call, why = "skip", "Little overlap with your profile."
    return {"call": call, "why": why, "strengths": strengths[:4], "cautions": cautions[:4], "blockers": blockers[:3],
            "years_have": have_years, "years_asked": want_years}


def _have(p: CandidateProfile) -> set[str]:
    text = p.summary + " " + " ".join(p.skills) + " " + " ".join(b for e in p.experience for b in e.bullets)
    return {ALIASES.get(s.lower(), s.lower()) for s in p.skills} | set(tokens(text))


# ---------------------------------------------------------------- keyword report
def keyword_report(p: CandidateProfile, job: JobListing, reqs) -> dict:
    """Every keyword the posting uses, whether your resume has it, and where."""
    jd = tokens(f"{job.title} {job.description}")
    counts: dict[str, int] = {}
    for t in jd:
        counts[t] = counts.get(t, 0) + 1
    noise = set(tokens(f"{job.company} {job.location}"))
    skills = {ALIASES.get(s.lower(), s.lower()): s for s in p.skills}
    skill_tokens = {t: s for s in p.skills for t in tokens(s)}
    terms = [t for t in dict.fromkeys(list(reqs.must_have) + list(reqs.nice_to_have) + list(reqs.keywords) + [t for t in counts if t in skill_tokens or t in skills])
             if t not in noise and meaningful(t, set(skill_tokens) | set(skills))][:40]
    rows = []
    for t in terms:
        where = ""
        if t in skills or t in skill_tokens:
            where = "Skills"
        else:
            for key, e in p.roles().items():
                if any(t in tokens(b) for b in e.bullets):
                    where = f"Experience at {key}"
                    break
            if not where and any(t in tokens(b) or t in [x.lower() for x in pr.technologies] for pr in p.projects for b in pr.bullets + [" ".join(pr.technologies)]):
                where = "Projects"
            if not where and t in tokens(p.summary):
                where = "Summary"
        rows.append({"term": show(t), "key": t, "count": counts.get(t, 0), "have": bool(where), "where": where,
                     "must": t in reqs.must_have})
    rows.sort(key=lambda r: (-r["must"], -r["count"], r["term"]))
    have = [r for r in rows if r["have"]]
    return {"have": have, "missing": [r for r in rows if not r["have"]], "total": len(rows),
            "coverage": round(len(have) / len(rows), 2) if rows else None}


# ---------------------------------------------------------------- salary explorer
CITY_ALIASES = {"bangalore": "Bengaluru", "bengaluru": "Bengaluru", "gurgaon": "Gurugram", "gurugram": "Gurugram", "bombay": "Mumbai",
                "mumbai": "Mumbai", "pune": "Pune", "hyderabad": "Hyderabad", "chennai": "Chennai", "noida": "Noida", "delhi": "Delhi",
                "kolkata": "Kolkata", "ahmedabad": "Ahmedabad", "kochi": "Kochi", "jaipur": "Jaipur", "chandigarh": "Chandigarh"}


def city_of(location: str, remote: bool = False) -> str:
    low = (location or "").lower()
    for k, v in CITY_ALIASES.items():
        if k in low:
            return v
    return "Remote" if remote or "remote" in low else "Other"


def _pct(vals: list[float], q: float) -> float:
    return round(vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))], 1)


def salary_explorer(store, role: str = "", city: str = "") -> dict:
    """Pay stated in listings the app has seen (INR, LPA). Honest about sample size; never extrapolates."""
    from ..salary import parse_salary
    rt = set(tokens(role))
    rows = []
    for r in store.list_runs():
        j = store.get_job(r.job_id)
        s = parse_salary(f"{j.title}\n{j.description}") if j else None
        if not s or s["currency"] != "INR":
            continue
        if rt and not (rt & set(tokens(j.title))):
            continue
        rows.append({"mid": (s["min"] + s["max"]) / 2, "min": s["min"], "max": s["max"], "city": city_of(j.location, j.remote),
                     "title": j.title, "company": j.company, "source": j.source.split(":")[0]})
    by_city: dict[str, list[float]] = {}
    for x in rows:
        by_city.setdefault(x["city"], []).append(x["mid"])
    cities = sorted(({"city": c, "n": len(v), "median": round(statistics.median(v), 1), "low": round(min(v), 1), "high": round(max(v), 1)}
                     for c, v in by_city.items()), key=lambda c: -c["n"])
    sel = [x for x in rows if not city or x["city"].lower() == city.lower()]
    vals = sorted(x["mid"] for x in sel)
    q = urllib.parse.quote_plus
    what, where = role or "software engineer", city if city and city not in ("Remote", "Other") else "India"
    out = {"n": len(vals), "role": role, "city": city, "cities": cities, "unit": "LPA",
           "sources": sorted({x["source"] for x in sel}),
           "examples": [{"title": x["title"], "company": x["company"], "range": f"₹{x['min']:g}–{x['max']:g} LPA" if x["max"] != x["min"] else f"₹{x['min']:g} LPA", "city": x["city"]}
                        for x in sorted(sel, key=lambda x: -x["mid"])[:6]],
           "links": [{"label": "Levels.fyi", "url": f"https://www.levels.fyi/t/software-engineer/locations/india?search={q(what)}"},
                     {"label": "Glassdoor", "url": f"https://www.google.com/search?q={q(f'{what} salary {where} glassdoor')}"},
                     {"label": "AmbitionBox", "url": f"https://www.google.com/search?q={q(f'{what} salary {where} ambitionbox')}"}],
           "note": "From pay stated in job listings this app has seen — mostly Glassdoor estimates and recruiter ranges. A guide, not a quote."}
    if len(vals) >= 3:
        out.update(low=vals[0], p25=_pct(vals, .25), median=round(statistics.median(vals), 1), p75=_pct(vals, .75), high=vals[-1])
    return out


# ---------------------------------------------------------------- LinkedIn profile review (pasted text; LinkedIn itself is never opened)
BUZZ = re.compile(r"\b(seeking|looking for|open to) (?:new )?(?:opportunit|role|job)|aspiring|unemployed|passionate|hard-?working|"
                  r"team player|results?-driven|go-getter|guru|ninja|rockstar|synergy", re.I)


def linkedin_review(p: CandidateProfile, headline: str, about: str, skills: list[str], demand: list[dict], titles: list[str]) -> dict:
    headline, about = (headline or "").strip(), (about or "").strip()
    li_skills = {ALIASES.get(s.strip().lower(), s.strip().lower()) for s in skills if s.strip()}
    mine = {ALIASES.get(s.lower(), s.lower()): s for s in p.skills}
    wanted = [d["skill"] for d in demand if d.get("have")][:12]                   # in demand AND genuinely yours
    top = [mine.get(k, show(k)) for k in wanted if k in mine][:6] or p.skills[:6]
    role = re.sub(r"\s+\d+$", "", re.split(r"\s+[—–-]\s+", p.experience[0].title)[0]).strip() if p.experience else "Engineer"
    checks = []

    def add(area, ok, text, pts):
        checks.append({"area": area, "ok": bool(ok), "text": text, "points": pts})

    hl = headline.lower()
    add("Headline", 40 <= len(headline) <= 220, f"Length is {len(headline)} characters — aim for 60–160 so it isn't cut off." if headline else "Add a headline.", 10)
    add("Headline", any(t.lower() in hl for t in titles) or role.lower() in hl, "Names the role recruiters search for." if headline else "Name your target role.", 12)
    add("Headline", sum(1 for s in top if s.lower() in hl) >= 2, "Mentions at least two of your in-demand skills.", 10)
    add("Headline", not BUZZ.search(headline), "No filler like “seeking opportunities” or “passionate”.", 6)
    add("About", 400 <= len(about) <= 2600, f"Length is {len(about)} characters — 600–2,000 reads best." if about else "Add an About section.", 10)
    add("About", bool(re.search(r"\d", about)), "Includes at least one number (scale, percentage, time saved).", 10)
    add("About", sum(1 for s in top if s.lower() in about.lower()) >= 3, "Mentions three or more of your in-demand skills.", 10)
    add("About", bool(re.search(r"\b(I|I'm|I’ve|my)\b", about)), "Written in the first person.", 5)
    add("About", bool(re.search(r"@|reach me|contact|message me|get in touch|dm me", about, re.I)), "Ends with how to reach you.", 5)
    add("About", not BUZZ.search(about), "No filler phrases.", 4)
    add("Skills", len(li_skills) >= 15, f"{len(li_skills)} skills listed — LinkedIn search works best with 15 or more.", 8)
    add_skills = [mine[k] for k in wanted if k in mine and k not in li_skills][:10]
    add("Skills", not add_skills, "Lists your in-demand skills." if not add_skills else "Missing skills employers ask for that are in your resume.", 10)
    score = round(100 * sum(c["points"] for c in checks if c["ok"]) / sum(c["points"] for c in checks))

    # rewrites: assembled only from the profile's own words
    domain = next((w for w in ("backend", "full-stack", "cloud", "security", "data", "AI", "platform", "infrastructure")
                   if w.lower() in p.summary.lower()), "")
    new_headline = " | ".join(x for x in (role, ", ".join(top[:4]), (domain[0].upper() + domain[1:] if domain else "")) if x)[:220]
    metric = [b.strip().rstrip(".") for e in p.experience for b in e.bullets if re.search(r"\d", b)][:2]
    li = next((l for l in p.links if "linkedin" not in l.lower()), "")
    new_about = "\n\n".join(x for x in (
        p.summary.strip(),
        ("Some of what I've done:\n" + "\n".join(f"• {m}." for m in metric)) if metric else "",
        "What I work with: " + ", ".join(top + [s for s in p.skills if s not in top][:6]) + ".",
        f"The best way to reach me is {p.email}." + (f" More of my work: {li}." if li else "")) if x)
    return {"score": score, "grade": "Strong" if score >= 80 else "Good" if score >= 60 else "Needs work", "checks": checks,
            "add_skills": add_skills, "headline": new_headline, "about": new_about,
            "note": "Rewrites use only wording from your saved resume. Paste them into LinkedIn yourself — nothing is sent there."}
