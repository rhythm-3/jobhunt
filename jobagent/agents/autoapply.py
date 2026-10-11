"""Automatic application on company career sites (Greenhouse, Lever, Ashby). Runs only AFTER human approval.

Principles
  * Facts come from the profile; screening answers only from the user's own answer bank - nothing is guessed.
  * Any required question without an answer, any visible CAPTCHA, or any validation error -> stop, don't submit,
    hand over to the human with the exact list of missing answers.
  * Success is claimed ONLY when the site shows a confirmation; a screenshot of it is kept as proof.
  * Job boards with personal accounts (LinkedIn, Naukri, Glassdoor, Indeed) are never automated.

Run as a subprocess (isolated from the API server):  python -m jobagent.agents.autoapply <run_id> [--dry]
Prints one JSON line: {"ok": bool, "outcome": "submitted|dry_run|needs_answers|captcha|failed|unsupported", ...}
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

SUPPORTED = {"greenhouse": r"(^|\.)greenhouse\.io$", "lever": r"^jobs\.lever\.co$", "ashby": r"^jobs\.ashbyhq\.com$"}

QUESTION_KEYS = [   # label pattern -> answer-bank key (order matters: first match wins)
    ("sponsorship", r"sponsor"),
    ("work_authorization", r"authori[sz]ed to work|legally (?:eligible|authori[sz]ed|able) to work|right to work|work permit|eligible to work"),
    ("expected_ctc", r"expected (?:ctc|salary|compensation|pay)|salary expectation|desired (?:salary|compensation)|compensation expectation"),
    ("current_ctc", r"current (?:ctc|salary|compensation|pay)"),
    ("notice_period", r"notice period|earliest (?:start|joining)|when can you (?:start|join)|available to start|start date"),
    ("relocate", r"relocat"),
    ("years_experience", r"years of (?:relevant |professional |total )?experience|how many years"),
    ("how_heard", r"how did you (?:hear|find|learn)|where did you (?:hear|find|see)|referral source|source of application"),
    ("website", r"website|portfolio|github|personal (?:site|url)"),
    ("current_company", r"current (?:company|employer)|most recent (?:company|employer)"),
    ("current_title", r"current (?:title|role|position|job title)"),
]
DEMOGRAPHIC = re.compile(r"gender|race|ethnic|hispanic|latin|veteran|disabilit|sexual orientation|transgender|pronoun", re.I)
CONSENT = re.compile(r"privacy|consent|agree|acknowledg|terms|data (?:processing|protection)|gdpr", re.I)
DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not to (?:answer|disclose|say)|choose not", re.I)
CONFIRM = re.compile(r"thank you for (?:applying|your application|your interest)|application (?:has been |was )?(?:submitted|received)|"
                     r"we(?:'ve| have) received your application|successfully (?:submitted|applied)", re.I)


def ats_of(url: str) -> str | None:
    from urllib.parse import urlparse
    host = urlparse(url or "").netloc.lower()
    return next((k for k, rx in SUPPORTED.items() if re.search(rx, host)), None)


def application_url(ats: str, url: str) -> str:
    u = url.split("#")[0].rstrip("/")
    if ats == "lever" and not u.endswith("/apply"):
        return u + "/apply"
    if ats == "ashby" and not u.endswith("/application"):
        return u + "/application"
    return u


def question_key(label: str) -> str | None:
    return next((k for k, rx in QUESTION_KEYS if re.search(rx, label or "", re.I)), None)


def answer_for(label: str, answers: dict, profile) -> str | None:
    k = question_key(label)
    if k == "current_company" and profile.experience:
        return answers.get(k) or profile.experience[0].company
    if k == "current_title" and profile.experience:
        return answers.get(k) or profile.experience[0].title.split("—")[0].strip()
    if k and answers.get(k):
        return answers[k]
    for key, val in answers.items():                 # custom "keyword -> answer" pairs added by the user
        if key.startswith("q:") and key[2:].strip() and key[2:].strip().lower() in (label or "").lower():
            return val
    return None


def pick_option(options: list[str], answer: str) -> str | None:
    """Choose the option that matches a free-text answer ('Yes', '30 days', ...)."""
    a = answer.strip().lower()
    for o in options:                                  # exact / prefix
        if o.strip().lower() == a or o.strip().lower().startswith(a):
            return o
    for o in options:
        if a and a in o.lower():
            return o
    yn = {"yes": r"^\s*yes\b", "no": r"^\s*no\b"}.get(a)
    return next((o for o in options if yn and re.search(yn, o, re.I)), None)


# JS: describe fields incl. required flag, options and radio/checkbox groups (label lookup happens in the page)
_SCAN = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return (r.width && r.height) || e.type === 'file'; };
  const lab = e => {
    const byFor = e.id ? document.querySelector(`label[for="${CSS.escape(e.id)}"]`) : null;
    const wrap = e.closest('label, fieldset, .field, .application-question, [class*="question"], [class*="Field"], [class*="field"]');
    const legend = e.closest('fieldset') ? (e.closest('fieldset').querySelector('legend') || {}).innerText : '';
    const by = (e.getAttribute('aria-labelledby') || '').split(' ').map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    return [byFor && byFor.innerText, by, e.getAttribute('aria-label'), legend, wrap && wrap.innerText.slice(0, 300), e.placeholder, e.name, e.id]
      .filter(Boolean).join(' | ').replace(/\s+/g, ' ').slice(0, 400);
  };
  const out = []; let i = 0;
  for (const e of document.querySelectorAll('input, textarea, select, [role=combobox]')) {
    if (e.disabled || !vis(e) || e.type === 'hidden' || e.type === 'submit' || e.type === 'button') continue;
    e.setAttribute('data-aa', ++i);
    const req = e.required || e.getAttribute('aria-required') === 'true' || /\*/.test((document.querySelector(`label[for="${CSS.escape(e.id || '_')}"]`) || {}).innerText || '');
    const f = { i, tag: e.tagName.toLowerCase(), type: (e.type || e.getAttribute('role') || '').toLowerCase(), name: e.name || '', label: lab(e), required: !!req,
                value: e.type === 'checkbox' || e.type === 'radio' ? (e.checked ? 'on' : '') : (e.value || '') };
    if (e.tagName === 'SELECT') f.options = [...e.options].map(o => o.text.trim()).filter(Boolean);
    if (e.type === 'radio' || e.type === 'checkbox') f.optlabel = ((e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest('label') || {}).innerText || e.value;
    out.push(f);
  }
  return out;
}"""

CAPTCHA_VISIBLE = """() => [...document.querySelectorAll('iframe')].some(f => /hcaptcha|recaptcha|turnstile|captcha/i.test(f.src + f.title)
  && !/invisible|size=invisible/i.test(f.src) && f.getBoundingClientRect().width > 60 && f.getBoundingClientRect().height > 60)"""


def fill_form(page, profile, answers: dict, prefs, resume: str | None, cover_path: str | None, cover_text: str) -> dict:
    """Fill every field we can answer truthfully. Returns {filled:[...], missing:[labels of required unanswered]}."""
    from .formfill import classify_field, profile_values
    vals = profile_values(profile)
    filled, missing, handled_groups = [], [], set()
    fields = page.evaluate(_SCAN)
    for f in fields:
        sel = f"[data-aa='{f['i']}']"
        label, typ, tag = f["label"], f["type"], f["tag"]
        short = label.split(" | ")[0][:80] or f["name"]
        try:
            if typ == "file":
                if re.search(r"cover", label, re.I) and cover_path:
                    page.set_input_files(sel, cover_path); filled.append("cover letter file")
                elif re.search(r"resume|cv|curriculum", label, re.I) and resume:
                    page.set_input_files(sel, resume); filled.append("resume")
                elif f["required"]:
                    missing.append(short)
                continue
            if typ in ("radio", "checkbox"):
                group = f["name"] or label
                if group in handled_groups:
                    continue
                opts = [x for x in fields if (x["name"] or x["label"]) == group and x["type"] == typ]
                done = False
                if DEMOGRAPHIC.search(label):
                    if prefs.decline_demographics:
                        o = next((x for x in opts if DECLINE.search(x.get("optlabel") or "")), None)
                        if o:
                            page.check(f"[data-aa='{o['i']}']", force=True); done = True
                elif typ == "checkbox" and CONSENT.search(label) and len(opts) == 1:
                    if prefs.accept_privacy_consent:
                        page.check(sel, force=True); done = True; filled.append("privacy consent")
                else:
                    ans = answer_for(label, answers, profile)
                    if ans:
                        o = pick_option([x.get("optlabel") or "" for x in opts], ans)
                        if o:
                            target = next(x for x in opts if (x.get("optlabel") or "") == o)
                            page.check(f"[data-aa='{target['i']}']", force=True); done = True; filled.append(short)
                handled_groups.add(group)
                if not done and any(x["required"] for x in opts) and not any(x["value"] for x in opts):
                    missing.append(short)
                continue
            if f["value"].strip():
                continue                                        # never overwrite what's already there
            if tag == "select" or typ == "combobox":
                if DEMOGRAPHIC.search(label):
                    ans = "Decline" if prefs.decline_demographics else None
                else:
                    ans = answer_for(label, answers, profile)
                    k = classify_field(label.split(" | ")[0]) or classify_field(label)
                    ans = ans or (vals.get(k) if k else None)
                if ans and tag == "select":
                    o = pick_option(f.get("options", []), ans) if not DEMOGRAPHIC.search(label) else next(
                        (x for x in f.get("options", []) if DECLINE.search(x)), None)
                    if o:
                        page.select_option(sel, label=o); filled.append(short); continue
                elif ans and typ == "combobox":
                    page.click(sel); page.fill(sel, ans if not DEMOGRAPHIC.search(label) else "Decline")
                    page.wait_for_timeout(500); page.keyboard.press("Enter"); filled.append(short); continue
                if f["required"]:
                    missing.append(short)
                continue
            # text-like inputs & textareas
            k = classify_field(label.split(" | ")[0], typ, tag) or classify_field(label, typ, tag)
            val = vals.get(k) if k else None
            if not val and tag == "textarea" and re.search(r"cover letter|additional information|anything else|message to", label, re.I):
                val = cover_text
            val = val or answer_for(label, answers, profile)
            if val:
                page.fill(sel, val); filled.append(short)
            elif f["required"]:
                missing.append(short)
        except Exception as e:   # noqa: BLE001 - one odd widget must not abort the run
            if f.get("required"):
                missing.append(f"{short} ({type(e).__name__})")
    return {"filled": filled, "missing": list(dict.fromkeys(missing))}


def run(run_id: str, dry: bool = False, headless: bool = True) -> dict:
    from ..config import Settings
    from ..db import Store
    from ..schemas import AuditEvent, CandidateProfile
    from .documents import ensure_pdf
    from playwright.sync_api import sync_playwright

    cfg = Settings(); store = Store(cfg.db_path)
    r = store.get_run(run_id); job = store.get_job(r.job_id) if r else None
    if not (r and job):
        return {"ok": False, "outcome": "failed", "reason": "unknown application"}
    ats = ats_of(job.url)
    if not ats:
        return {"ok": False, "outcome": "unsupported", "reason": "this site isn't one we can apply on automatically"}
    profile = CandidateProfile.model_validate_json(store.kv_get("profile"))
    prefs = profile.prefs
    out_dir = Path(cfg.out_dir) / run_id; out_dir.mkdir(parents=True, exist_ok=True)
    resume = None
    if r.resume_path:
        pdf = ensure_pdf(str(Path(r.resume_path).with_name("resume.html")))
        if pdf.endswith(".pdf"):
            resume = str(out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', profile.full_name)}_Resume.pdf")
            shutil.copyfile(pdf, resume)
    cover_text = r.adaptation.cover_letter if r.adaptation else ""
    cover_path = None
    if cover_text:
        cover_path = str(out_dir / "Cover_Letter.txt"); Path(cover_path).write_text(cover_text)
    shot = str(out_dir / ("preview.png" if dry else "application.png"))
    result: dict = {"ats": ats, "url": application_url(ats, job.url)}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1280, "height": 1800})
        try:
            res = _attempt(page, result, ats, profile, prefs, resume, cover_path, cover_text, shot, dry)
        except Exception as e:   # noqa: BLE001
            try:
                page.screenshot(path=shot, full_page=True); result["screenshot"] = shot
            except Exception:
                pass
            res = {**result, "ok": False, "outcome": "failed", "reason": f"{type(e).__name__}: {str(e)[:160]}"}
        finally:
            browser.close()
    store.kv_set(f"apply:{run_id}", json.dumps(res))
    store.audit(AuditEvent(run_id=run_id, actor="autoapply", event="attempt",
                           detail={k: v for k, v in res.items() if k in ("ats", "outcome", "reason", "missing", "confirmation")} | {"dry": dry}))
    return res


def _attempt(page, result, ats, profile, prefs, resume, cover_path, cover_text, shot, dry) -> dict:
    page.goto(result["url"], timeout=45_000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if ats == "greenhouse" and not page.locator("form").count():
        btn = page.get_by_role("button", name=re.compile("apply", re.I))
        if btn.count():
            btn.first.click(); page.wait_for_timeout(1500)
    if page.evaluate(CAPTCHA_VISIBLE):
        page.screenshot(path=shot, full_page=True)
        return {**result, "ok": False, "outcome": "captcha", "reason": "the site shows a CAPTCHA", "screenshot": shot}
    rep = fill_form(page, profile, prefs.answers, prefs, resume, cover_path, cover_text)
    result.update(rep)
    page.wait_for_timeout(800)
    page.screenshot(path=shot, full_page=True)
    result["screenshot"] = shot
    if rep["missing"]:
        return {**result, "ok": False, "outcome": "needs_answers",
                "reason": "required questions without an answer: " + "; ".join(rep["missing"][:6])}
    if not rep["filled"]:
        return {**result, "ok": False, "outcome": "failed", "reason": "couldn't find an application form on the page"}
    if dry:
        return {**result, "ok": True, "outcome": "dry_run", "reason": f"practice mode: filled {len(rep['filled'])} fields, not submitted"}
    submit = page.locator("button[type=submit], input[type=submit], button:has-text('Submit application'), button:has-text('Submit')")
    if not submit.count():
        return {**result, "ok": False, "outcome": "failed", "reason": "couldn't find the Submit button"}
    submit.first.click()
    for _ in range(25):                                  # up to ~25 s for the confirmation
        page.wait_for_timeout(1000)
        text = page.inner_text("body")[:20000]
        if CONFIRM.search(text) or re.search(r"confirmation|thank|success|submitted", page.url, re.I):
            page.screenshot(path=shot, full_page=True)
            m = CONFIRM.search(text)
            return {**result, "ok": True, "outcome": "submitted", "confirmation": m.group(0) if m else page.url}
        if page.evaluate(CAPTCHA_VISIBLE):
            page.screenshot(path=shot, full_page=True)
            return {**result, "ok": False, "outcome": "captcha", "reason": "a CAPTCHA appeared on submit - finish it yourself"}
    errs = page.evaluate("""() => [...document.querySelectorAll('[aria-invalid=true], .error, [class*="error"]')]
        .map(e => (e.innerText || e.getAttribute('aria-label') || e.name || '').trim()).filter(Boolean).slice(0, 5)""")
    page.screenshot(path=shot, full_page=True)
    return {**result, "ok": False, "outcome": "failed",
            "reason": "no confirmation after submitting" + (": " + "; ".join(errs) if errs else "") + " - please check it yourself"}


if __name__ == "__main__":
    args = sys.argv[1:]
    res = run(args[0], dry="--dry" in args, headless="--show" not in args)
    print(json.dumps(res))
