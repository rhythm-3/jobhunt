"""Auto-apply against LOCAL fake application forms (never a real company site)."""
import tempfile
import unittest
from pathlib import Path

from jobagent.agents.autoapply import _attempt, answer_for, ats_of, application_url, pick_option, question_key
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile, Preferences

P = CandidateProfile(**{**SAMPLE_PROFILE, "links": ["linkedin.com/in/alex"]})

FORM = """<!doctype html><html><body><form id=f onsubmit="event.preventDefault(); %s">
<label for=fn>First Name *</label><input id=fn required>
<label for=ln>Last Name *</label><input id=ln required>
<label for=em>Email *</label><input id=em type=email required>
<label for=ph>Phone</label><input id=ph>
<label for=li>LinkedIn Profile</label><input id=li>
<label for=cv>Resume/CV *</label><input id=cv type=file required>
<label for=cl>Cover Letter</label><textarea id=cl></textarea>
<label for=wa>Are you legally authorized to work in India? *</label><select id=wa required><option></option><option>Yes</option><option>No</option></select>
<fieldset><legend>Will you now or in the future require visa sponsorship? *</legend>
  <label><input type=radio name=sp value=y required>Yes</label><label><input type=radio name=sp value=n>No</label></fieldset>
<label for=g>Gender</label><select id=g><option></option><option>Male</option><option>Female</option><option>Decline To Self Identify</option></select>
<label><input type=checkbox id=pc required> I agree to the privacy policy *</label>
%s
<button type=submit>Submit application</button></form>
<iframe %s style="width:%dpx;height:%dpx"></iframe></body></html>"""
OK = "document.body.innerHTML='<h1>Thank you for applying!</h1>'"
NOOP = "void 0"


def page_with(tmp, name, onsubmit=OK, extra="", captcha=False):
    p = Path(tmp, name)
    p.write_text(FORM % (onsubmit, extra, 'src="about:blank" title="hcaptcha challenge"' if captcha else 'src="about:blank"',
                         300 if captcha else 0, 80 if captcha else 0))
    return p.as_uri()


class Pure(unittest.TestCase):
    def test_site_detection_and_urls(self):
        self.assertEqual(ats_of("https://boards.greenhouse.io/rubrik/jobs/1"), "greenhouse")
        self.assertEqual(ats_of("https://job-boards.greenhouse.io/twilio/jobs/2"), "greenhouse")
        self.assertEqual(ats_of("https://jobs.lever.co/meesho/abc"), "lever")
        self.assertIsNone(ats_of("https://www.linkedin.com/jobs/view/1"))          # never automated
        self.assertIsNone(ats_of("https://www.glassdoor.co.in/partner/x"))
        self.assertEqual(application_url("lever", "https://jobs.lever.co/a/b"), "https://jobs.lever.co/a/b/apply")
        self.assertEqual(application_url("ashby", "https://jobs.ashbyhq.com/a/b/"), "https://jobs.ashbyhq.com/a/b/application")

    def test_answers_come_only_from_bank_or_profile(self):
        self.assertEqual(question_key("Will you require visa sponsorship?"), "sponsorship")
        self.assertEqual(question_key("What is your notice period?"), "notice_period")
        self.assertIsNone(answer_for("What are your salary expectations?", {}, P))            # never guessed
        self.assertEqual(answer_for("What are your salary expectations?", {"expected_ctc": "30 LPA"}, P), "30 LPA")
        self.assertEqual(answer_for("Current company", {}, P), "Northwind")                    # factual, from profile
        self.assertEqual(answer_for("Do you know Rust? (required)", {"q:know rust": "No"}, P), "No")   # custom pair
        self.assertEqual(pick_option(["", "Yes", "No"], "yes"), "Yes")
        self.assertEqual(pick_option(["Immediately", "30 days", "60 days"], "30"), "30 days")


class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start(); cls.b = cls.pw.chromium.launch()
        except Exception as e:
            raise unittest.SkipTest(f"chromium unavailable: {e}")
        cls.tmp = tempfile.mkdtemp()
        cls.resume = str(Path(cls.tmp, "Alex_Resume.pdf")); Path(cls.resume).write_bytes(b"%PDF-1.4 test")

    @classmethod
    def tearDownClass(cls):
        cls.b.close(); cls.pw.stop()

    def go(self, url, answers=None, dry=False, **pref):
        page = self.b.new_page()
        prefs = Preferences(answers=answers if answers is not None else {"work_authorization": "Yes", "sponsorship": "No"}, **pref)
        shot = str(Path(self.tmp, "s.png"))
        res = _attempt(page, {"url": url}, "lever", P, prefs, self.resume, None, "Dear team, hello.", shot, dry)
        return res, page

    def test_fills_everything_truthfully_and_submits(self):
        res, page = self.go(page_with(self.tmp, "ok.html"))
        self.assertEqual(res["outcome"], "submitted", res)
        self.assertIn("Thank you for applying", res["confirmation"])
        self.assertIn("resume", res["filled"]); self.assertIn("privacy consent", res["filled"])

    def test_practice_mode_fills_but_never_submits(self):
        res, page = self.go(page_with(self.tmp, "dry.html"), dry=True)
        self.assertEqual(res["outcome"], "dry_run")
        self.assertEqual(page.input_value("#fn"), "Alex"); self.assertEqual(page.input_value("#em"), "alex@example.com")
        self.assertEqual(page.eval_on_selector("#wa", "e => e.value"), "Yes")
        self.assertTrue(page.is_checked("input[name=sp][value=n]"))                     # sponsorship: No
        self.assertEqual(page.eval_on_selector("#g", "e => e.value"), "Decline To Self Identify")
        self.assertEqual(page.input_value("#cl"), "Dear team, hello.")
        self.assertEqual(page.locator("text=Thank you").count(), 0)                       # not submitted

    def test_unanswered_required_question_stops_without_submitting(self):
        extra = "<label for=why>Why do you want to work here? *</label><textarea id=why required></textarea>"
        res, page = self.go(page_with(self.tmp, "q.html", extra=extra))
        self.assertEqual(res["outcome"], "needs_answers")
        self.assertTrue(any("Why do you want" in m for m in res["missing"]), res["missing"])
        self.assertEqual(page.locator("text=Thank you").count(), 0)

    def test_missing_bank_answer_for_visa_stops(self):
        res, _ = self.go(page_with(self.tmp, "v.html"), answers={})
        self.assertEqual(res["outcome"], "needs_answers")
        self.assertTrue(any("authorized" in m.lower() for m in res["missing"]))

    def test_demographics_left_blank_when_user_opts_out(self):
        res, page = self.go(page_with(self.tmp, "d.html"), dry=True, decline_demographics=False)
        self.assertEqual(page.eval_on_selector("#g", "e => e.value"), "")

    def test_captcha_stops(self):
        res, _ = self.go(page_with(self.tmp, "c.html", captcha=True))
        self.assertEqual(res["outcome"], "captcha")

    def test_no_confirmation_is_not_counted_as_applied(self):
        res, _ = self.go(page_with(self.tmp, "n.html", onsubmit=NOOP))
        self.assertEqual(res["outcome"], "failed")
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
