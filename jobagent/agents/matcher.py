"""Match & Optimization Agent: JD parsing, similarity scoring, grounded tailoring + hallucination guard.

`Tailorer` is the seam for an LLM. The deterministic implementation below obeys the same contract
(ResumeAdaptation) and is what the guard validates, so swapping in a model cannot weaken safety.
"""
from __future__ import annotations

import re
from typing import Protocol

from ..schemas import BulletAdaptation, CandidateProfile, JDRequirements, JobListing, ResumeAdaptation
from ..text import ALIASES, cosine, embed, extract_keywords, tokens


class HallucinationError(ValueError):
    pass


def parse_jd(job: JobListing) -> JDRequirements:
    text = job.description
    must, nice = [], []
    section = "must"
    for line in text.splitlines():
        l = line.strip().lower()
        if re.match(r"^(nice to have|bonus|preferred|plus)", l):
            section = "nice"
        elif re.match(r"^(requirements|must have|qualifications|what you)", l):
            section = "must"
        kws = [k for k in extract_keywords(line, 10) if k in set(tokens(line))]
        (must if section == "must" else nice).extend(kws)
    # company, location and salary lines are not requirements (short alert-email descriptions are mostly those)
    noise = set(tokens(f"{job.company} {job.location}")) | {"lpa", "lacs", "lakh", "ctc", "est", "glassdoor"}
    must = [k for k in must if k not in noise and not re.search(r"\d", k)]
    nice = [k for k in nice if k not in noise and not re.search(r"\d", k)]
    kws = [k for k in extract_keywords(text) if k not in noise]
    lowered = f"{job.title} {text}".lower()
    sen = next((s for s, pat in {"staff": r"staff|principal", "senior": r"senior|sr\.", "junior": r"junior|entry",
                                 "mid": r"mid-level"}.items() if re.search(pat, lowered)), "unknown")
    dedupe = lambda xs: list(dict.fromkeys(xs))
    return JDRequirements(must_have=dedupe(must)[:20], nice_to_have=dedupe(nice)[:10], keywords=kws, seniority=sen)


def score_parts(profile: CandidateProfile, job: JobListing, reqs: JDRequirements) -> dict:
    """The two ingredients of the match score, so the UI can show why a job scored as it did."""
    prof_text = profile.summary + " " + " ".join(profile.skills) + " " + " ".join(
        b for e in profile.experience for b in e.bullets)
    sem = max(0.0, cosine(embed(prof_text), embed(job.title + " " + job.description)))
    have = {ALIASES.get(s.lower(), s.lower()) for s in profile.skills} | set(tokens(prof_text))
    met = [k for k in reqs.must_have if k in have]
    coverage = (len(met) / len(reqs.must_have)) if reqs.must_have else sem
    return {"similarity": min(1.0, sem * 2.0), "coverage": coverage, "met": len(met), "asked": len(reqs.must_have)}


def experience_fit(profile: CandidateProfile, job: JobListing) -> dict:
    """Years the posting asks for against the years you have. fit is 1 when you meet it and falls 18 points per missing year;
    None when the posting states no years (then it simply doesn't count)."""
    from . import market
    have, asked = market.years_of_experience(profile), market.years_asked(f"{job.title}\n{job.description}")
    if asked is None:
        return {"asked": None, "have": have, "fit": None}
    gap = asked - have
    return {"asked": asked, "have": have, "fit": 1.0 if gap <= 0 else round(max(0.0, 1 - 0.18 * gap), 2)}


def score(profile: CandidateProfile, job: JobListing, reqs: JDRequirements) -> float:
    """Experience asked against yours carries the most weight (45%), then the requirements you cover (35%), then how close
    the wording is to your background (20%). When the posting states no years, it is requirements 65% and wording 35%."""
    p, x = score_parts(profile, job, reqs), experience_fit(profile, job)
    if x["fit"] is None:
        return round(0.35 * p["similarity"] + 0.65 * p["coverage"], 3)
    return round(0.45 * x["fit"] + 0.35 * p["coverage"] + 0.20 * p["similarity"], 3)


class Tailorer(Protocol):
    def tailor(self, profile: CandidateProfile, job: JobListing, reqs: JDRequirements,
               feedback: str | None = None) -> ResumeAdaptation: ...


class RuleTailorer:
    """Select & reorder real content by JD relevance. Never invents skills or experience."""

    def tailor(self, profile: CandidateProfile, job: JobListing, reqs: JDRequirements,
               feedback: str | None = None) -> ResumeAdaptation:
        wanted = set(reqs.keywords) | set(reqs.must_have) | set(reqs.nice_to_have)
        norm = lambda s: ALIASES.get(s.lower(), s.lower())
        skills = sorted(profile.skills, key=lambda s: (norm(s) not in wanted, profile.skills.index(s)))
        matched = [k for k in reqs.must_have + reqs.nice_to_have if k in {norm(s) for s in profile.skills}
                   or k in set(tokens(" ".join(b for e in profile.experience for b in e.bullets)))]
        missing = [k for k in reqs.must_have if k not in matched]
        bullets: list[BulletAdaptation] = []
        for key, e in profile.roles().items():
            ranked = sorted(enumerate(e.bullets), key=lambda ib: -len(set(tokens(ib[1])) & wanted))
            for i, b in ranked[:3]:
                hits = sorted(set(tokens(b)) & wanted)
                bullets.append(BulletAdaptation(source_company=key, source_index=i, original=b,
                                                rewritten=b, injected_keywords=[]))
        top = ", ".join(matched[:4]) or "relevant experience"
        summary = f"{profile.summary.rstrip('.')}. Strengths aligned with {job.company}: {top}."
        cover = (f"Dear {job.company} hiring team,\n\nI'm applying for the {job.title} role. "
                 f"My background in {top} maps directly onto what you describe. "
                 f"{profile.experience[0].bullets[0] if profile.experience else ''}\n\n"
                 f"I'd welcome the chance to discuss how I can contribute.\n\nBest regards,\n{profile.full_name}")
        return ResumeAdaptation(job_id=job.id, match_score=min(1.0, score(profile, job, reqs)),
                                matched_requirements=matched, missing_requirements=missing,
                                tailored_summary=summary, bullets=bullets, ordered_skills=skills,
                                cover_letter=cover)


def _with_parts(toks: list[str]) -> set[str]:
    """'ci/cd-style' also counts as 'ci/cd' and 'style' - hyphenated compounds are evidence for their parts."""
    out = set(toks)
    for t in toks:
        out.update(p for p in t.split("-") if len(p) > 1)
    return out


def verify_grounded(profile: CandidateProfile, adapt: ResumeAdaptation) -> None:
    """Hallucination guard. Raises HallucinationError on any claim not traceable to the profile."""
    known_skills = {ALIASES.get(s.lower(), s.lower()) for s in profile.skills}
    corpus = _with_parts(tokens(profile.summary + " " + " ".join(b for e in profile.experience for b in e.bullets) + " " +
                        " ".join(b + " " + " ".join(p.technologies) for p in profile.projects for b in p.bullets)))
    known_skills |= _with_parts(tokens(" ".join(profile.skills)))
    by_co = profile.roles()

    for s in adapt.ordered_skills:
        if s.lower() not in {x.lower() for x in profile.skills}:
            raise HallucinationError(f"skill not in profile: {s}")
    for b in adapt.bullets:
        e = by_co.get(b.source_company)
        if not e or not (0 <= b.source_index < len(e.bullets)) or e.bullets[b.source_index] != b.original:
            raise HallucinationError(f"bullet not traceable to profile: {b.original[:50]!r}")
        new_terms = set(tokens(b.rewritten)) - set(tokens(b.original))
        # a rewrite may introduce new words, but never new tech terms or numbers the profile doesn't support
        unsupported = {t for t in new_terms
                       if t not in corpus and t not in known_skills and (re.search(r"\d", t) or t in _TECH_HINTS)}
        if unsupported:
            raise HallucinationError(f"rewrite adds unsupported terms {sorted(unsupported)}")
    # prose may not name tech the candidate has no evidence for (covers LLM-written summary / cover letter)
    prose = set(tokens(adapt.tailored_summary + " " + adapt.cover_letter))
    leaked = {t for t in prose if t in _TECH_HINTS and t not in corpus and t not in known_skills}
    if leaked:
        raise HallucinationError(f"summary/cover letter mentions unsupported technologies {sorted(leaked)}")
    for claim in re.findall(r"\b\d[\d,.]*\+?\s*(?:years?|yrs?)\b", adapt.tailored_summary + adapt.cover_letter):
        if claim not in profile.summary and not any(claim in b for e in profile.experience for b in e.bullets):
            raise HallucinationError(f"unsupported quantitative claim: {claim}")
    for m in adapt.matched_requirements:
        if m not in known_skills and m not in corpus:
            raise HallucinationError(f"claims match on requirement candidate lacks: {m}")


from ..text import TECH as _TECH_HINTS  # noqa: E402


def tailor_with_guard(profile, job, reqs, tailorer: Tailorer, retries: int = 2,
                      user_note: str | None = None) -> ResumeAdaptation:
    last: Exception | None = None
    feedback: str | None = f"USER:{user_note}" if user_note else None
    for _ in range(retries + 1):
        a = tailorer.tailor(profile, job, reqs, feedback)
        try:
            verify_grounded(profile, a)
            return a
        except HallucinationError as e:
            last = e                        # an LLM tailorer uses this to self-correct on the next attempt
            feedback = str(e) + (f" | USER:{user_note}" if user_note else "")
    raise HallucinationError(f"tailoring failed grounding after {retries + 1} attempts: {last}")
