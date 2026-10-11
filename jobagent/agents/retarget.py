"""Keep the job search in step with the resume.

When a different resume is saved, the search should follow it: the titles to look for, and (through them) what the
job boards are asked. This is deterministic, so it works with or without a language model, and it reads only the
person's own titles, summary and skills.
"""
from __future__ import annotations

import re

from ..schemas import CandidateProfile

# field -> (search titles, words that signal the field). Search titles are matched as parts of a job title,
# so "security" also finds "Cybersecurity Engineer" and "developer" finds "Backend Developer".
FIELDS: dict[str, tuple[list[str], str]] = {
    "security": (["security", "detection", "soc", "threat", "incident"],
                 r"secur|cyber|infosec|\bsoc\b|siem|soar|detection|threat|incident response|vulnerab|pentest|penetration|forensic|malware|\bgrc\b"),
    "software": (["software", "developer", "backend", "full stack", "sde"],
                 r"software|developer|backend|back-end|frontend|front-end|full[- ]?stack|\bsde\b|programmer|web dev|application engineer"),
    "data": (["data", "analytics", "machine learning", "ai engineer"],
             r"data (?:scien|engineer|analy)|analytics|machine learning|\bml\b|deep learning|\bnlp\b|business intelligence|\bbi\b|statistic"),
    "devops": (["devops", "sre", "platform", "cloud", "infrastructure"],
               r"devops|\bsre\b|site reliability|platform engineer|cloud engineer|infrastructure|kubernetes|terraform|ci/cd"),
    "qa": (["qa", "test", "quality", "sdet"], r"\bqa\b|quality assurance|test(?:er|ing)? engineer|\bsdet\b|automation test"),
    "mobile": (["mobile", "android", "ios", "flutter"], r"android|\bios\b|mobile (?:dev|engineer|app)|flutter|react native|swift|kotlin"),
    "product": (["product manager", "product owner", "program manager"], r"product manag|product owner|program manag|roadmap"),
    "design": (["designer", "ux", "ui"], r"\bux\b|\bui\b designer|product design|interaction design|figma|user research"),
}
LEVEL = re.compile(r"\b(senior|sr\.?|junior|jr\.?|lead|principal|staff|associate|intern|trainee|i{1,3}|iv|\d+|engineer|specialist|analyst|consultant)\b", re.I)


def split_skill_groups(skills: list[str]) -> list[str]:
    """'Cloud: AWS, GCP, Azure' is three skills, not one. Category labels are dropped; order is kept."""
    out: list[str] = []
    for s in skills:
        s = s.strip()
        label, sep, rest = s.partition(":")
        if sep and rest.strip() and ("," in rest or len(s) > 45) and len(label.split()) <= 5:
            parts = [p.strip(" .;") for p in re.split(r"[,;]", rest)]
        elif len(s) > 45 and s.count(",") >= 2:
            parts = [p.strip(" .;") for p in s.split(",")]
        else:
            parts = [s]
        out.extend(p for p in parts if p and len(p) <= 60)
    return list(dict.fromkeys(out))[:80]


def field_scores(p: CandidateProfile) -> dict[str, float]:
    titles = [e.title.lower() for e in p.experience]
    parts = [(titles[0], 4.0)] if titles else []
    parts += [(t, 2.0) for t in titles[1:]]
    parts += [(p.summary.lower(), 1.5), (" ".join(p.skills).lower(), 0.6)]
    scores = {}
    for field, (_, pattern) in FIELDS.items():
        rx = re.compile(pattern)
        scores[field] = round(sum(w * min(3, len(rx.findall(text))) for text, w in parts), 2)
    return scores


def search_titles(p: CandidateProfile) -> tuple[list[str], str]:
    """-> (titles to search for, the field they describe). Falls back to the words of the latest job title."""
    scores = field_scores(p)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked and ranked[0][1] >= 4:
        field, top = ranked[0]
        titles = list(FIELDS[field][0])
        if len(ranked) > 1 and ranked[1][1] >= max(6, 0.7 * top):          # a genuine second field, e.g. security + devops
            titles += FIELDS[ranked[1][0]][0][:2]
        return titles[:6], field
    latest = p.experience[0].title if p.experience else ""
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#/-]{2,}", LEVEL.sub(" ", latest))]
    return (list(dict.fromkeys(words))[:3] or ["engineer"]), "general"


def needs_retarget(p: CandidateProfile, current: list[str], previous: CandidateProfile | None) -> bool:
    """Retarget when the resume is a different one, or when the current titles no longer describe it at all."""
    titles, field = search_titles(p)
    cur = [t.lower() for t in current or []]
    if not cur:
        return True
    pattern = re.compile(FIELDS[field][1]) if field in FIELDS else None
    fits = any(t in titles or (pattern and pattern.search(t)) for t in cur)
    if not fits:
        return True
    if previous and previous.experience and p.experience:
        return search_titles(previous)[1] != field                           # the new resume is in another field
    return False
