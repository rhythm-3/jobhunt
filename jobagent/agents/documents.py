"""Deterministic document build: same input -> byte-identical HTML. PDF via WeasyPrint when installed."""
from __future__ import annotations

import html
import re
from pathlib import Path

from ..schemas import CandidateProfile, ResumeAdaptation

CSS = ("body{font:10.5pt/1.35 Helvetica,Arial,sans-serif;margin:0.6in;color:#111}h1{font-size:20pt;margin:0}"
       "h2{font-size:11pt;border-bottom:1px solid #999;margin:14px 0 4px;text-transform:uppercase}"
       "ul{margin:2px 0 6px 18px;padding:0}.meta{color:#444}")  # single column, no tables/images => ATS-safe
e = html.escape


# Every template is one column of real text with standard headings, so applicant-tracking systems read them all the same.
TEMPLATES = {
    "classic": ("Classic", CSS),
    "modern": ("Modern", "body{font:10.5pt/1.4 Helvetica,Arial,sans-serif;margin:0.6in;color:#1a1a1a}h1{font-size:23pt;margin:0;letter-spacing:-.3px;color:#0b3a5e}"
               "h2{font-size:10pt;letter-spacing:1.2px;color:#0b5c8a;border-bottom:2px solid #0b5c8a;padding-bottom:2px;margin:16px 0 6px;text-transform:uppercase}"
               "h3{font-size:10.5pt;margin:8px 0 2px}ul{margin:2px 0 6px 18px;padding:0}.meta{color:#4a5560}"),
    "compact": ("Compact", "body{font:9.5pt/1.28 Helvetica,Arial,sans-serif;margin:0.45in;color:#111}h1{font-size:17pt;margin:0}"
                "h2{font-size:9.5pt;border-bottom:1px solid #777;margin:9px 0 3px;text-transform:uppercase}h3{font-size:9.5pt;margin:5px 0 1px}"
                "p{margin:2px 0}ul{margin:1px 0 4px 16px;padding:0}.meta{color:#444}"),
    "elegant": ("Elegant", "body{font:10.5pt/1.42 Georgia,'Times New Roman',serif;margin:0.7in;color:#151515}h1{font-size:22pt;margin:0;text-align:center;font-weight:normal;letter-spacing:.5px}"
                "body>.meta{text-align:center;margin-bottom:6px}h2{font:bold 10pt/1.2 Georgia,serif;letter-spacing:1.5px;border-bottom:1px solid #888;margin:16px 0 5px;text-transform:uppercase}"
                "h3{font-size:10.5pt;margin:8px 0 2px}ul{margin:2px 0 6px 18px;padding:0}.meta{color:#444}"),
}


def render_resume_html(p: CandidateProfile, a: ResumeAdaptation, template: str | None = None) -> str:
    CSS = TEMPLATES.get(template or p.prefs.resume_template, TEMPLATES["classic"])[1]      # noqa: N806 (shadows the default on purpose)
    by_co: dict[str, list[str]] = {}
    for b in a.bullets:
        by_co.setdefault(b.source_company, []).append(b.rewritten)
    exp = "".join(
        f"<h3>{e(x.title)} — {e(x.company)} <span class='meta'>({e(x.start)}–{e(x.end)})</span></h3><ul>"
        + "".join(f"<li>{e(b)}</li>" for b in by_co.get(key, [])) + "</ul>" for key, x in p.roles().items())
    contact = " · ".join(e(v) for v in (p.location, p.phone, p.email, *p.links) if v)
    proj = "".join(f"<h3>{e(x.name)}</h3><div class='meta'>Technologies: {e(', '.join(x.technologies))}</div><ul>"
                   + "".join(f"<li>{e(b)}</li>" for b in x.bullets) + "</ul>" for x in p.projects)
    proj = f"<h2>Projects</h2>{proj}" if proj else ""
    certs = f"<h2>Certifications</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in p.certifications)}</ul>" if p.certifications else ""
    return (f"<!doctype html><meta charset=utf-8><title>{e(p.full_name)} — Resume</title><style>{CSS}</style>"
            f"<h1>{e(p.full_name)}</h1><div class='meta'>{contact}</div>"
            f"<h2>Summary</h2><p>{e(a.tailored_summary)}</p><h2>Skills</h2><p>{e(', '.join(a.ordered_skills))}</p>"
            f"<h2>Experience</h2>{exp}{proj}<h2>Education</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in p.education)}</ul>{certs}")


def build_documents(p: CandidateProfile, a: ResumeAdaptation, out_dir: str, run_id: str) -> str:
    d = Path(out_dir) / run_id
    d.mkdir(parents=True, exist_ok=True)
    doc = render_resume_html(p, a)
    src = d / "resume.html"
    if not src.exists() or src.read_text(encoding="utf-8") != doc:      # unchanged resume: keep the file, so its PDF is reused
        src.write_text(doc, encoding="utf-8")
    (d / "cover_letter.txt").write_text(a.cover_letter, encoding="utf-8")
    return ensure_pdf(str(d / "resume.html"))


def cover_letter_pdf(p: CandidateProfile, company: str, role: str, text: str, out_dir: str, run_id: str) -> str:
    """Formatted, single-page cover letter (HTML -> PDF), rebuilt from the current text every time."""
    import datetime as _dt
    d = Path(out_dir) / run_id
    d.mkdir(parents=True, exist_ok=True)
    paras = [x.strip() for x in re.split(r"\n\s*\n", text.strip()) if x.strip()]
    body = "".join(f"<p>{e(x).replace(chr(10), '<br>')}</p>" for x in paras)
    contact = " · ".join(e(v) for v in (p.location, p.phone, p.email, *p.links) if v)
    doc = (f"<!doctype html><meta charset=utf-8><title>{e(p.full_name)} — Cover letter</title><style>{CSS}"
           f"p{{margin:0 0 12px}}.hd{{border-bottom:1px solid #999;padding-bottom:8px;margin-bottom:22px}}</style>"
           f"<div class=hd><h1>{e(p.full_name)}</h1><div class=meta>{contact}</div></div>"
           f"<p class=meta>{_dt.date.today():%d %B %Y}</p><p>{e(company)}{' — ' + e(role) if role else ''}</p>{body}")
    src = d / "cover_letter.html"
    src.write_text(doc, encoding="utf-8")
    out = src.with_suffix(".pdf")
    if out.exists():
        out.unlink()                     # always rebuild: the text may have been edited
    return ensure_pdf(str(src))


def ensure_pdf(html_path: str) -> str:
    """Best-effort HTML->PDF (WeasyPrint, else headless Chromium via Playwright). Returns the HTML path if neither works."""
    import os
    src = Path(html_path)
    if src.suffix == ".pdf" or os.getenv("JOBAGENT_PDF", "1") == "0":
        return html_path
    out = src.with_suffix(".pdf")
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return str(out)
    try:
        from weasyprint import HTML
        HTML(filename=str(src)).write_pdf(out)
        return str(out)
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page()
            pg.goto(src.resolve().as_uri())
            pg.pdf(path=str(out), format="A4", margin={"top": "0.4in", "bottom": "0.4in", "left": "0.4in", "right": "0.4in"})
            b.close()
        return str(out)
    except Exception:
        return html_path
