"""Assisted application form filler.  NEVER submits.

Opens the job page in a visible browser, fills only the standard, unambiguous fields from the candidate's own
profile (name, email, phone, LinkedIn, location, resume file, cover letter) and stops so the human reviews and
clicks Submit. Anything sensitive or uncertain (work authorisation, salary, demographics, CAPTCHAs, custom questions)
is deliberately left for the human. It does not try to evade bot detection or solve CAPTCHAs.

Run as a separate process so the browser window outlives the API request:
    python -m jobagent.agents.formfill <run_id>
"""
from __future__ import annotations

import re
import sys

# Fields we must never auto-fill, whatever else matches.
NEVER = re.compile(r"password|captcha|gender|race|ethnic|veteran|disabilit|salary|compensation|ctc|sponsor|"
                   r"authori[sz]|visa|notice|pronoun|birth|\bdob\b|ssn|social security|referr|hear about|expected|"
                   r"company|employer|school|university|degree|reference|relocat|citizen|clearance|criminal|"
                   r"consent|agree|terms|privacy|signature", re.I)
SKIP_TYPES = {"password", "checkbox", "radio", "hidden", "submit", "button", "search", "image", "reset", "file",
              "number", "date", "range", "color"}


def classify_field(label: str, typ: str = "text", tag: str = "input") -> str | None:
    """Map a field's visible label/name/placeholder to a profile key, or None (= leave for the human)."""
    t = re.sub(r"[_\-\[\].*]+", " ", (label or "").lower()).strip()
    if not t or typ in SKIP_TYPES or NEVER.search(t):
        return None
    if tag == "textarea":
        return "cover_letter" if re.search(r"cover letter|motivation|message (?:to|for) (?:the )?(?:hiring|recruit)", t) else None
    if re.search(r"e ?mail", t):
        return "email"
    if re.search(r"linked ?in", t):
        return "linkedin"
    if re.search(r"phone|mobile|contact number|\btel\b|whatsapp", t):
        return "phone"
    if re.search(r"first name|given name|\bfname\b", t):
        return "first_name"
    if re.search(r"last name|family name|surname|\blname\b", t):
        return "last_name"
    if re.search(r"full name|your name|^name$|legal name|candidate name|^name\b(?!.*(?:of|for))", t):
        return "full_name"
    if re.search(r"^(?:current )?(?:city|location)$|current location|where are you (?:based|located)|^city\b", t):
        return "location"
    return None


def profile_values(profile) -> dict[str, str]:
    first, _, last = profile.full_name.partition(" ")
    linkedin = next((l for l in profile.links if "linkedin" in l.lower()), "")
    if linkedin and not linkedin.startswith("http"):
        linkedin = "https://www." + linkedin
    return {"email": profile.email, "phone": profile.phone or "", "first_name": first,
            "last_name": last or first, "full_name": profile.full_name, "linkedin": linkedin,
            "location": profile.location or ""}


# JS run in each frame: describe every visible fillable control (label lookup lives here, in the page).
_DESCRIBE = """() => [...document.querySelectorAll('input, textarea')].map((el, i) => {
  const r = el.getBoundingClientRect(); if (!r.width || !r.height || el.disabled || el.readOnly) return null;
  const lab = el.labels && el.labels[0] ? el.labels[0].innerText : '';
  const by = (el.getAttribute('aria-labelledby') || '').split(' ').map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
  el.setAttribute('data-jaidx', i);
  return {i, tag: el.tagName.toLowerCase(), type: (el.type || 'text').toLowerCase(), value: el.value || '',
          label: [lab, by, el.getAttribute('aria-label'), el.placeholder, el.name, el.id].filter(Boolean).join(' ')};
}).filter(Boolean)"""


def prefill_frame(frame, values: dict[str, str], resume_path: str | None, done: dict) -> None:
    for f in frame.evaluate(_DESCRIBE):
        sel = f"[data-jaidx='{f['i']}']"
        if f["type"] == "file":
            if resume_path and not done.get("resume") and re.search(r"resume|cv|curriculum", f["label"], re.I) \
                    and not re.search(r"cover", f["label"], re.I):
                frame.set_input_files(sel, resume_path)
                done["resume"] = True
            continue
        key = classify_field(f["label"], f["type"], f["tag"])
        if not key or f["value"].strip() or done.get(key) == sel:
            continue
        val = values.get(key)
        if val:
            frame.fill(sel, val)
            frame.evaluate("s => { const e = document.querySelector(s); e.style.outline = '2px solid #0f8a5f'; }", sel)
            done[key] = sel


def main(run_id: str) -> int:
    from ..config import Settings
    from ..db import Store
    from ..schemas import AuditEvent, CandidateProfile
    from .documents import ensure_pdf
    from playwright.sync_api import sync_playwright

    cfg = Settings()
    store = Store(cfg.db_path)
    run = store.get_run(run_id)
    job = store.get_job(run.job_id) if run else None
    if not (run and job):
        print("unknown run", file=sys.stderr)
        return 2
    profile = CandidateProfile.model_validate_json(store.kv_get("profile"))
    values = profile_values(profile)
    values["cover_letter"] = run.adaptation.cover_letter if run.adaptation else ""
    resume = ensure_pdf(run.resume_path) if run.resume_path else None
    done: dict = {}

    def scan(page):
        try:
            for fr in page.frames:
                prefill_frame(fr, values, resume, done)
        except Exception:     # page navigating / frame detached: the next load event rescans
            pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        page.on("domcontentloaded", scan)
        target = job.apply_url or job.url
        page.goto(target, timeout=45_000)
        store.audit(AuditEvent(run_id=run.id, actor="formfill", event="opened", detail={"url": target}))
        # keep scanning (forms often appear after clicking "Apply"); exit when the human closes the window
        try:
            while not page.is_closed():
                page.wait_for_timeout(2000)
                scan(page)
        except Exception:
            pass
        store.audit(AuditEvent(run_id=run.id, actor="formfill", event="closed",
                               detail={"filled": sorted(k for k in done if k != "resume"), "resume_uploaded": "resume" in done}))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
