"""Real-browser check of the form assistant against a local page (skipped when Chromium isn't installed)."""
import tempfile
import unittest
from pathlib import Path

from jobagent.agents.formfill import prefill_frame, profile_values
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile

FORM = """<!doctype html><form id=f onsubmit="document.title='SUBMITTED';return false">
<label for=fn>First Name *</label><input id=fn name=fn>
<label>Last Name<input name=ln></label>
<input name=email placeholder="Email address" type=email>
<input name=ph aria-label="Phone number">
<input name=li placeholder="LinkedIn profile URL">
<input name=prefilled value="keep-me" placeholder="Email (work)">
<label for=cur>Current company</label><input id=cur>
<label for=sal>Expected salary</label><input id=sal>
<label for=auth>Are you legally authorized to work in this country?</label><input id=auth>
<label for=g>Gender</label><input id=g>
<input name=why placeholder="Why do you want to join us?">
<label for=cl>Cover letter</label><textarea id=cl></textarea>
<label for=cv>Resume/CV</label><input type=file id=cv>
<div style="display:none"><input name=hiddenemail placeholder="Email"></div>
<button type=submit id=sub>Submit application</button></form>"""


class Browser(unittest.TestCase):
    def test_fills_standard_fields_only_and_never_submits(self):
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
        except Exception as e:
            self.skipTest(f"chromium unavailable: {e}")
        try:
            d = Path(tempfile.mkdtemp()); (d / "form.html").write_text(FORM); (d / "resume.pdf").write_bytes(b"%PDF-1.4")
            p = CandidateProfile(**{**SAMPLE_PROFILE, "links": ["linkedin.com/in/alex"]})
            vals = profile_values(p); vals["cover_letter"] = "Dear team, hello."
            page = browser.new_page(); page.goto((d / "form.html").as_uri())
            done = {}
            prefill_frame(page.main_frame, vals, str(d / "resume.pdf"), done)
            prefill_frame(page.main_frame, vals, str(d / "resume.pdf"), done)          # idempotent rescan
            v = lambda sel: page.input_value(sel)
            self.assertEqual(v("#fn"), "Alex"); self.assertEqual(v("[name=ln]"), "Morgan")
            self.assertEqual(v("[name=email]"), "alex@example.com"); self.assertEqual(v("[name=ph]"), "+1 555 0100")
            self.assertEqual(v("[name=li]"), "https://www.linkedin.com/in/alex")
            self.assertEqual(v("#cl"), "Dear team, hello.")
            self.assertEqual(v("[name=prefilled]"), "keep-me")                          # never overwrites user data
            for untouched in ("#cur", "#sal", "#auth", "#g", "[name=why]", "[name=hiddenemail]"):
                self.assertEqual(v(untouched), "", untouched)
            self.assertEqual(page.eval_on_selector("#cv", "e => e.files.length && e.files[0].name"), "resume.pdf")
            self.assertNotEqual(page.title(), "SUBMITTED")                               # submit was never clicked
        finally:
            browser.close(); pw.stop()


if __name__ == "__main__":
    unittest.main()
