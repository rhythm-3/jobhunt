"""Shared state schema. Every agent reads/writes these types only."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(StrEnum):
    DISCOVERED = "discovered"
    SCORED = "scored"
    SKIPPED = "skipped"                 # below match threshold
    FILTERED = "filtered"               # fails the user's current filters (salary, location, company...); reversible
    TAILORED = "tailored"
    AWAITING_APPROVAL = "awaiting_approval"   # HITL gate #1 (outbound application)
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    NEEDS_MANUAL = "needs_manual"       # all automated channels exhausted
    FAILED = "failed"
    INTERVIEW = "interview"
    OFFER = "offer"                     # an offer was received for this application
    CLOSED = "closed"


class Channel(StrEnum):
    EMAIL = "email"
    FORM = "form"
    MANUAL = "manual"
    EXTERNAL = "external"                 # applied outside the app; imported from a confirmation email


class Experience(BaseModel):
    company: str
    title: str
    start: str
    end: str = "present"
    bullets: list[str]
    skills: list[str] = []


class Autopilot(BaseModel):
    enabled: bool = False          # off by default: every application waits for a human
    min_score: float = Field(0.9, ge=0.5, le=1)
    daily_cap: int = Field(5, ge=1, le=50)


class Preferences(BaseModel):
    """Per-person customization. Stored inside CandidateProfile.preferences; unknown keys are preserved."""
    model_config = {"extra": "allow"}
    target_titles: list[str] = []
    target_locations: list[str] = []
    work_modes: list[Literal["remote", "hybrid", "onsite"]] = ["remote", "hybrid", "onsite"]
    exclude_keywords: list[str] = []
    exclude_companies: list[str] = []
    min_match: float = Field(0.30, ge=0, le=1)
    tone: Literal["conservative", "technical", "impact", "narrative"] = "technical"
    auto_tailor_top: int = Field(8, ge=0, le=50)
    sources: dict[str, bool] = {"feeds": True, "companies": True, "gmail_alerts": True}
    watch_companies: list[str] | None = None
    autopilot: Autopilot = Autopilot()
    sweep_hours: float = Field(0, ge=0, le=72)        # 0 = only when you click Refresh
    auto_research: int = Field(15, ge=0, le=60)       # after each search, look up full descriptions for the best N thin listings
    follow_up_days: int = Field(7, ge=2, le=60)
    min_salary_lpa: float = Field(0, ge=0, le=500)         # 0 = no filter; only applied when a listing states INR pay
    # ---- applying on company websites
    auto_submit_forms: bool = True        # after approval, submit Greenhouse/Lever/Ashby forms automatically
    decline_demographics: bool = True     # voluntary gender/race/veteran/disability questions -> "decline to answer"
    accept_privacy_consent: bool = True   # tick required "I agree to the privacy notice" boxes
    answers: dict[str, str] = Field(default_factory=dict)   # user-authored screening answers (never generated)
    # ---- motivation & reminders
    weekly_goal: int = Field(10, ge=1, le=100)            # applications per week
    outreach_daily_cap: int = Field(10, ge=1, le=30)      # cold emails per day, at most
    resume_template: Literal["classic", "modern", "compact", "elegant"] = "classic"
    auto_outreach: int = Field(5, ge=0, le=20)            # outreach drafts to prepare for the best new matches after each refresh (0 = off)
    digest_hour: int = Field(-1, ge=-1, le=23)            # daily summary email to yourself at this local hour; -1 = off


class Project(BaseModel):
    name: str
    technologies: list[str] = []
    bullets: list[str]


class CandidateProfile(BaseModel):
    """Source of truth. Tailoring may only *select and rephrase* from this."""
    full_name: str
    email: str
    phone: str | None = None
    location: str | None = None
    summary: str
    skills: list[str]
    experience: list[Experience]
    education: list[str] = []
    certifications: list[str] = []
    projects: list[Project] = []
    links: list[str] = []
    preferences: dict = Field(default_factory=dict)

    @property
    def prefs(self) -> "Preferences":
        return Preferences.model_validate(self.preferences or {})

    def roles(self) -> dict[str, Experience]:
        """Stable per-role keys: the company name, or 'Company (Title)' when a company appears more than once."""
        from collections import Counter
        n = Counter(e.company for e in self.experience)
        return {(e.company if n[e.company] == 1 else f"{e.company} ({e.title})"): e for e in self.experience}


class JobListing(BaseModel):
    id: str
    source: str
    url: str
    title: str
    company: str
    location: str = ""
    remote: bool = False
    description: str
    apply_email: str | None = None
    fingerprint: str = ""               # dedup key across boards
    apply_url: str | None = None        # the employer's own application page, when found (OSINT enrichment)
    enriched_from: str = ""             # where the full description came from, e.g. "greenhouse:rubrik"
    rating: float | None = None         # employer rating shown in the alert email (e.g. Glassdoor stars)
    discovered_at: datetime = Field(default_factory=utcnow)


class JDRequirements(BaseModel):
    must_have: list[str]
    nice_to_have: list[str] = []
    keywords: list[str]                 # ATS keywords, normalized lowercase
    seniority: Literal["junior", "mid", "senior", "staff", "unknown"] = "unknown"


class BulletAdaptation(BaseModel):
    source_company: str
    source_index: int
    original: str
    rewritten: str
    injected_keywords: list[str] = []


class ResumeAdaptation(BaseModel):
    """LLM output contract for resume tailoring vs. JD requirements.

    The validator below is the anti-hallucination gate: every injected keyword
    must already exist in the candidate's verified skill set or source bullet.
    """
    job_id: str
    match_score: float = Field(ge=0, le=1)
    matched_requirements: list[str]
    missing_requirements: list[str]     # reported honestly, never fabricated
    tailored_summary: str
    bullets: list[BulletAdaptation]
    ordered_skills: list[str]
    cover_letter: str

    @model_validator(mode="after")
    def _no_dupes(self) -> "ResumeAdaptation":
        if len({s.lower() for s in self.ordered_skills}) != len(self.ordered_skills):
            raise ValueError("duplicate skills")
        return self


class ApplicationRun(BaseModel):
    id: str
    job_id: str
    status: RunStatus = RunStatus.DISCOVERED
    match_score: float | None = None
    adaptation: ResumeAdaptation | None = None
    resume_path: str | None = None
    channel: Channel | None = None
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class InboundClass(StrEnum):
    INTERVIEW = "interview_request"
    REJECTION = "rejection"
    SCREENING = "screening_questions"
    ACK = "auto_acknowledgement"
    OTHER = "other"


class InboundEmail(BaseModel):
    id: str
    sender: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=utcnow)
    run_id: str | None = None
    sender_name: str = ""
    company: str = ""
    thread_id: str = ""
    action: str = ""                      # what the human should do next, in plain words
    replied_at: str = ""
    label: InboundClass | None = None
    calendar_links: list[str] = []
    proposed_slots: list[str] = []


class AuditEvent(BaseModel):
    id: int | None = None
    run_id: str | None
    actor: str                          # agent name or "user"
    event: str
    detail: dict = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)


class Interview(BaseModel):
    """A scheduled conversation with an employer. Everything here is entered or confirmed by the user."""
    id: str
    run_id: str | None = None
    company: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=200)
    starts_at: datetime                                     # timezone-aware
    duration_min: int = Field(45, ge=5, le=600)
    kind: Literal["phone", "video", "onsite", "technical", "hr", "final", "other"] = "video"
    with_whom: str = Field("", max_length=200)             # e.g. "Hiring manager" - free text from the user
    link: str = Field("", max_length=1000)
    location: str = Field("", max_length=300)
    notes: str = Field("", max_length=5000)
    status: Literal["scheduled", "done", "cancelled"] = "scheduled"
    thank_you_sent_at: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _aware(self) -> "Interview":
        if self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        if self.link and not self.link.startswith(("https://", "http://")):
            raise ValueError("meeting link must start with https://")
        return self


class OfferRatings(BaseModel):
    growth: int = Field(3, ge=1, le=5)
    team: int = Field(3, ge=1, le=5)
    work_life: int = Field(3, ge=1, le=5)
    learning: int = Field(3, ge=1, le=5)


class Offer(BaseModel):
    """An offer the user received. Money is annual, in the offer's currency (INR offers are in rupees)."""
    id: str
    run_id: str | None = None
    company: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=200)
    currency: Literal["INR", "USD", "EUR", "GBP", "SGD", "AED"] = "INR"
    base: float = Field(ge=0, le=1e9)
    bonus: float = Field(0, ge=0, le=1e9)                  # annual target bonus
    equity_per_year: float = Field(0, ge=0, le=1e9)        # vesting value per year, user's estimate
    joining_bonus: float = Field(0, ge=0, le=1e9)
    location: str = Field("", max_length=200)
    work_mode: Literal["remote", "hybrid", "onsite"] = "hybrid"
    notice_days: int = Field(0, ge=0, le=365)
    deadline: str = Field("", max_length=20)               # YYYY-MM-DD, optional
    benefits: str = Field("", max_length=2000)
    notes: str = Field("", max_length=5000)
    ratings: OfferRatings = OfferRatings()
    status: Literal["considering", "negotiating", "accepted", "declined"] = "considering"
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def recurring(self) -> float:
        return self.base + self.bonus + self.equity_per_year

    @property
    def first_year(self) -> float:
        return self.recurring + self.joining_bonus


class OutreachEvent(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    event: str
    detail: str = ""


class Outreach(BaseModel):
    """One person at one company: the email we drafted, whether it went out, and what happened next."""
    id: str
    company: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=200)
    contact_name: str = Field("", max_length=120)
    contact_title: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    linkedin_url: str = ""                 # a link the user found; never fetched or scraped
    run_id: str | None = None              # the saved job this is about, if any (its tailored CV is reused)
    job_text: str = Field("", max_length=20000)   # pasted job description, used to tailor the CV and the email
    note: str = Field("", max_length=600)  # the user's own sentence about why this company
    subject: str = ""
    body: str = ""
    method: str = ""                       # how the draft was written: template / ollama / claude
    status: Literal["draft", "approved", "sent", "replied", "interview", "declined", "bounced", "do_not_contact"] = "draft"
    attach: bool = True
    reviewed: bool = False                 # the user has opened and read this draft (required for one-click approve & send)
    auto: bool = False                     # prepared automatically from a strong match
    sent_at: datetime | None = None
    receipt: str = ""
    followups_sent: int = 0
    followup_subject: str = ""
    followup_body: str = ""
    last_followup_at: datetime | None = None
    replied_at: datetime | None = None
    reply_snippet: str = ""
    events: list[OutreachEvent] = []
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _check(self):
        import re
        if self.email and not re.match(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$", self.email.strip()):
            raise ValueError("that doesn't look like an email address")
        self.email = self.email.strip().lower()
        if self.linkedin_url and not re.match(r"^https://([a-z]{2,3}\.)?linkedin\.com/(in|company)/[\w%.\-]+/?(\?.*)?$", self.linkedin_url.strip()):
            raise ValueError("LinkedIn link should look like https://www.linkedin.com/in/name")
        self.linkedin_url = self.linkedin_url.strip()
        if self.sent_at and self.sent_at.tzinfo is None:
            self.sent_at = self.sent_at.replace(tzinfo=timezone.utc)
        return self


class Contact(BaseModel):
    """Someone you know at a company: a recruiter, a referrer, an interviewer."""
    id: str
    name: str = Field(min_length=1, max_length=120)
    company: str = Field("", max_length=120)
    title: str = Field("", max_length=120)
    relationship: Literal["recruiter", "referrer", "hiring_manager", "interviewer", "friend", "other"] = "recruiter"
    email: str = Field("", max_length=200)
    linkedin_url: str = Field("", max_length=300)
    notes: str = Field("", max_length=4000)
    last_contact: str = ""                 # YYYY-MM-DD
    next_follow_up: str = ""               # YYYY-MM-DD
    referral: Literal["none", "asked", "promised", "submitted"] = "none"
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _check(self):
        import re
        for f in ("last_contact", "next_follow_up"):
            v = getattr(self, f)
            if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
                raise ValueError("dates should look like 2026-10-31")
        if self.email and not re.match(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}$", self.email.strip()):
            raise ValueError("that doesn't look like an email address")
        if self.linkedin_url and not self.linkedin_url.startswith("https://"):
            raise ValueError("the LinkedIn link should start with https://")
        return self
