"""Inbox & Triage Agent: classify inbound mail, extract calendar links and proposed slots."""
from __future__ import annotations

import re

from ..db import Store
from ..schemas import AuditEvent, InboundClass, InboundEmail, RunStatus

CAL = re.compile(r"https?://(?:calendly\.com|cal\.com|meet\.google\.com|[\w.-]*zoom\.us/(?:j|my|meeting)|"
                 r"outlook\.office365\.com/book|teams\.microsoft\.com/l/meetup-join|[\w.-]*webex\.com/(?:meet|join)|"
                 r"[\w.-]*chilipiper\.com|savvycal\.com|[\w.-]*goodtime\.io|app\.greenhouse\.io/interviews?)[^\s<>\")\]]*", re.I)
GENERIC = ("gmail.", "yahoo.", "outlook.", "hotmail.", "naukri.", "greenhouse", "lever.co", "ashbyhq", "workday", "myworkday",
           "smartrecruiters", "icims", "linkedin.", "indeed.", "glassdoor.", "instahyre.", "ats.", "successfactors",
           "taleo", "jobvite", "breezy", "recruitee", "zohorecruit", "freshteam", "oraclecloud", "oracle.com",
           "gsconsulting", "careernet", "phenompeople", "eightfold", "beamery")
ACK_SUBJECTS = [re.compile(p, re.I) for p in (
    r"your application (?:for|to) (?:the )?(?P<title>.+?) (?:with|at) (?P<company>[^!.|]+)",
    r"thank you for (?:applying|your application)(?: to| for)? (?:the )?(?:(?P<title>.+?) (?:position |role )?at )?(?P<company>[^!.|]+)",
    r"application (?:received|submitted)[:\- ]+(?P<title>.+?) (?:at|with) (?P<company>[^!.|]+)",
    r"(?P<company>[^,]+?), we(?: have|'ve) received your application",
    r"we(?: have|'ve) received your application (?:for|to) (?P<title>.+?) at (?P<company>[^!.|]+)",
    r"your application to \[(?P<company>[^\]]+)\]",
    r"job opportunity (?:for|at|with) (?P<company>[^_|\-]+?)(?:[_|\-]|$)",
    r"your (?:recent )?(?:job )?application for (?P<title>.+?) at (?P<company>[^!.|]+)",
    r"your application was sent to (?P<company>[^!.|\n]+)",                                    # LinkedIn Easy Apply
    r"your application was viewed by (?P<company>[^!.|\n]+)",
    r"^(?P<company>[^:|–—]{2,50}?)\s+[-–—|:]\s+thank you for (?:applying|your application)",   # "Volvo Group - Thank you for your application!"
    r"^(?P<company>[^:|–—]{2,50}?)\s+[-–—|:]\s+application (?:received|confirmation)",
    r"update (?:about|on) your application(?: for (?P<title>.+?))?(?: (?:at|with) (?P<company>[^!.|]+))?$")]
SLOT = re.compile(r"\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+(?:[A-Z][a-z]+\s+\d{1,2}|\d{1,2}/\d{1,2})"
                  r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s?(?:am|pm)?(?:\s?[A-Z]{2,4})?)?", re.I)
RULES: list[tuple[InboundClass, re.Pattern]] = [
    (InboundClass.REJECTION, re.compile(r"unfortunately|not (?:be )?moving forward|other candidates|"
                                        r"decided not to|will not be proceeding|position has been filled", re.I)),
    (InboundClass.INTERVIEW, re.compile(
        r"(?:schedule|book|set up|arrange|find a time for)\s+(?:a|an|your|the|some)?\s*(?:\w+\s+){0,2}?"
        r"(?:call|interview|chat|meeting|screen|conversation)|invite you to (?:an? )?(?:interview|call|chat)|"
        r"interview (?:invitation|request|slot|schedule)|your availability|phone screen|"
        r"(?:like|love) to (?:speak|chat|connect|talk) with you|please (?:pick|choose|select) a (?:time|slot)", re.I)),
    (InboundClass.SCREENING, re.compile(r"please (?:answer|complete|fill)|screening questions|salary expectations|"
                                        r"work authori[sz]ation|notice period", re.I)),
    (InboundClass.SCREENING, re.compile(r"pleased to (?:offer|extend)|offer letter|we(?:'d| would) like to offer you|job offer|formal offer", re.I)),
    (InboundClass.ACK, re.compile(r"thank you for (?:applying|your application)|we(?:'ve| have) received|"
                                  r"application (?:received|submitted)", re.I)),
]


# job boards / coaching / newsletter senders: their mail mentions "interview", "roles", "hiring" constantly
BULK_DOMAINS = ("glassdoor.", "ambitionbox.", "crio.in", "naukri.", "indeed.", "foundit.", "monster.", "shine.com",
                "instahyre.", "cutshort.", "wellfound.", "hirist.", "unstop.", "internshala.", "medium.com", "substack.", "hackajob.")
BULK_MARKERS = re.compile(r"unsubscribe|view (?:this email )?in (?:your )?browser|manage (?:your )?(?:email )?preferences|"
                          r"you(?:'re| are) receiving this (?:email|message) because", re.I)


def is_bulk(m: InboundEmail) -> bool:
    dom = m.sender.lower().split("@")[-1]
    return any(d in dom for d in BULK_DOMAINS) or (
        "linkedin." in dom and "jobalerts" in m.sender.lower()) or bool(BULK_MARKERS.search(m.body))


def guess_company(m: InboundEmail) -> str:
    """Display name ('Jane at Acme', 'Acme Talent') > subject pattern > sender domain."""
    for rx in ACK_SUBJECTS:
        g = rx.search(m.subject)
        if g and g.groupdict().get("company"):
            c = g.group("company").strip(" -:[]")
            if c and len(c) < 60 and not re.match(r"(?i)aditya|you$", c):
                return c
    nm = re.sub(r"(?i)\b(talent|acquisition|recruiting|recruitment|recruiter|careers?|jobs?|hiring|team|hr|people|"
                r"no-?reply|notifications?|updates?)\b", "", m.sender_name.strip("'\"")).strip(" -|,()")
    at = re.search(r"(?i)\b(?:at|from|@)\s+(.+)$", m.sender_name)
    if at:
        return at.group(1).strip()
    dom = m.sender.lower().split("@")[-1]
    if not any(g in dom for g in GENERIC):
        base = dom.split(".")
        name = base[-2] if len(base) >= 2 else base[0]
        return name.upper() if len(name) <= 3 else name.title()        # "ey" -> EY, "acme" -> Acme
    return nm if nm and "@" not in nm and "(" not in nm and len(nm.split()) <= 4 else ""


ACTIONS = {InboundClass.INTERVIEW: "Pick a slot / reply to schedule", InboundClass.SCREENING: "Answer the recruiter's questions",
           InboundClass.REJECTION: "", InboundClass.ACK: "", InboundClass.OTHER: ""}


# "you started applying but haven't finished" / reminders are not applications
UNFINISHED = re.compile(r"incomplete|(?:complete|continue|finish|resume) your application|application is (?:still )?(?:pending|incomplete)|"
                        r"don'?t miss|hurry|almost (?:done|there)", re.I)
SUBJECT_ACK = re.compile(r"your (?:recent )?(?:job )?application for .+ (?:at|with) \S|your application was (?:sent to|viewed by)|thank you for (?:applying|your application)|application (?:received|confirmation)", re.I)
STATUS_UPDATE = re.compile(r"update (?:about|on) your application|application status|status of your application", re.I)
LINKEDIN_MSG = ("messages-noreply@linkedin.com", "inmail-hit-reply@linkedin.com")
RECRUITER_WORDS = re.compile(r"opportunit|opening|position|role\b|hiring|interview|job|offer|join (?:our|the) team|your (?:profile|background|experience)", re.I)
OFFER = re.compile(r"pleased to (?:offer|extend)|offer letter|we(?:'d| would) like to offer you|job offer|formal offer", re.I)


def classify(m: InboundEmail) -> InboundEmail:
    text = f"{m.subject}\n{m.body}"
    m.calendar_links = list(dict.fromkeys(CAL.findall(text)))
    m.proposed_slots = list(dict.fromkeys(s.strip() for s in SLOT.findall(text)))
    # rejection outranks ack ("thank you for applying... unfortunately") and interview phrasing
    m.label = next((c for c, rx in RULES if rx.search(text)), InboundClass.OTHER)
    if m.calendar_links and m.label in (InboundClass.ACK, InboundClass.OTHER, InboundClass.SCREENING):
        m.label = InboundClass.INTERVIEW          # a scheduling link is itself a strong invite signal
    if m.label == InboundClass.OTHER and SUBJECT_ACK.search(m.subject):
        m.label = InboundClass.ACK                 # the subject alone says so ("Your application was sent to Acme")
    if STATUS_UPDATE.search(m.subject) and m.label == InboundClass.OTHER:
        m.label = InboundClass.ACK                 # "Update on your application" is evidence you applied, and may say more
    if m.sender.lower() in LINKEDIN_MSG and m.label == InboundClass.OTHER and RECRUITER_WORDS.search(text):
        m.label = InboundClass.SCREENING           # a recruiter wrote to you on LinkedIn
    unfinished = bool(UNFINISHED.search(m.subject))
    # marketing/alerts never count as a reply to an application (real rejections/acks still pass through)
    if is_bulk(m) and m.label not in (InboundClass.REJECTION, InboundClass.ACK):
        m.label = InboundClass.OTHER
    if unfinished and m.label != InboundClass.REJECTION:
        m.label = InboundClass.OTHER
    m.company = m.company or guess_company(m)
    m.action = ACTIONS.get(m.label, "")
    if m.label == InboundClass.SCREENING and OFFER.search(text):
        m.action = "Looks like a job offer — read it, then add it under Interviews › Offers"
    elif m.label == InboundClass.SCREENING and m.sender.lower() in LINKEDIN_MSG:
        m.action = "A recruiter messaged you on LinkedIn — reply there"
    return m


def _words(s: str) -> list[str]:
    stop = {"inc", "ltd", "llc", "limited", "pvt", "private", "corp", "corporation", "co", "the", "technologies",
            "technology", "solutions", "services", "india", "group", "and"}
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in stop]


def same_company(company: str, m: InboundEmail) -> bool:
    """Whole-word company matching. Substrings are unsafe: 'EY' must not match 'INDmonEY'."""
    cw = _words(company)
    if not cw:
        return False
    key = " ".join(cw)
    dom = m.sender.lower().split("@")[-1].split(".")
    if len(cw) == 1 and len(key) >= 3 and key in dom:               # jobs@rubrik.com -> Rubrik
        return True
    if m.company and _words(m.company) == cw:
        return True
    return re.search(rf"\b{re.escape(key)}\b", " ".join(_words(m.subject))) is not None


def link_to_run(store: Store, m: InboundEmail) -> str | None:
    """Match sender domain / company name in subject to a submitted run."""
    dom = m.sender.split("@")[-1].lower().split(".")[0]
    for run in store.list_runs():
        job = store.get_job(run.job_id)
        if job and run.status in (RunStatus.SUBMITTED, RunStatus.INTERVIEW, RunStatus.OFFER) and same_company(job.company, m):
            return run.id
    return None


def poll_inbox(store: Store, reader, own_address: str = "", days: int = 14) -> dict:
    """Pull job-related mail, classify, keep only what matters (classified or tied to a run). Idempotent."""
    stats = {"seen": 0, "kept": 0, "ignored": 0, "imported": 0}
    first = not store.kv_get("inbox:backfill:v2")          # the first scan looks further back, to find what you already applied to
    for mid in reader.list_ids(days=max(days, 60) if first else days):
        if store.kv_get(f"seen:{mid}"):
            continue
        m = reader.fetch(mid)
        stats["seen"] += 1
        store.kv_set(f"seen:{mid}", "1")
        if own_address and m.sender.lower() == own_address.lower():
            continue
        m = classify(m)
        m.run_id = link_to_run(store, m)
        if m.label in (InboundClass.ACK, InboundClass.REJECTION) and not m.run_id and m.company:
            m.run_id = import_application(store, m)
            stats["imported"] = stats.get("imported", 0) + 1
        if m.label == InboundClass.OTHER and not m.run_id:
            stats["ignored"] += 1          # not stored: unrelated mail never persists in our DB
            continue
        process_inbound(store, m)
        stats["kept"] += 1
    if first:
        store.kv_set("inbox:backfill:v2", "1")
    return stats


BODY_TITLE = [re.compile(p) for p in (
    r"(?i:application for (?:the )?(?:role of |position of )?)(?P<t>[A-Z][\w&/,+\- ]{3,70}?)(?:\s+(?i:at|with|role|position)\b|[.,!\n(]|$)",
    r"(?i:the )(?P<t>[A-Z][\w&/+\- ]{3,60}?) (?i:role|position)\b",
    r"(?i:role of )(?P<t>[A-Z][\w&/,+\- ]{3,70}?)(?: (?i:at)\b|[.!\n]|$)")]


def role_title(m: InboundEmail) -> str:
    """Role name from the subject, else from the first lines of the body."""
    for rx in ACK_SUBJECTS:
        g = rx.search(m.subject)
        if g and g.groupdict().get("title"):
            return g.group("title").strip()
    g = re.search(r"(?i)application for (?:the )?(?:role of |position of )?(?P<t>.+?)(?:\s+(?:at|with)\s+.+)?$", m.subject)
    if g and len(g.group("t").split()) <= 12:
        return g.group("t").strip(" -")
    head = m.body[:600]
    for rx in BODY_TITLE:
        g = rx.search(head)
        if g:
            t = g.group("t").strip(" ,-")
            if not re.match(r"(?i)(your|our|this|a|an|the|interest)\b", t) and len(t.split()) <= 10:
                return t
    return ""


def import_application(store: Store, m: InboundEmail) -> str:
    """An application confirmation for something applied outside the app becomes a tracked application."""
    import uuid
    from ..schemas import ApplicationRun, Channel, JobListing
    from ..text import fingerprint
    title = role_title(m)
    job = JobListing(id=f"import:{m.id}", source="gmail-import", url="", title=title or "Application",
                     company=m.company, description=f"Imported from confirmation email: {m.subject}",
                     fingerprint=fingerprint(title or m.id, m.company))
    store.add_job(job)
    existing = store.run_for_job(job.id)
    if existing:
        return existing.id
    status = RunStatus.CLOSED if m.label == InboundClass.REJECTION else RunStatus.SUBMITTED
    run = ApplicationRun(id=uuid.uuid4().hex[:12], job_id=job.id, status=status, channel=Channel.EXTERNAL,
                         created_at=m.received_at)
    store.save_run(run)
    store.audit(AuditEvent(run_id=run.id, actor="triage", event="imported_application",
                           detail={"company": m.company, "title": title, "email": m.id}))
    return run.id


def process_inbound(store: Store, m: InboundEmail) -> InboundEmail:
    if store.has_email(m.id):
        return m                            # idempotent on provider message-id
    m = classify(m)
    m.run_id = link_to_run(store, m)
    store.save_email(m)
    store.audit(AuditEvent(run_id=m.run_id, actor="triage", event="classified",
                           detail={"email": m.id, "label": m.label, "links": m.calendar_links}))
    if m.run_id:
        run = store.get_run(m.run_id)
        if run:
            if m.label == InboundClass.INTERVIEW:
                run.status = RunStatus.INTERVIEW
            elif m.label == InboundClass.REJECTION:
                run.status = RunStatus.CLOSED
            store.save_run(run)
    return m
