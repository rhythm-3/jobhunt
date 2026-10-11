import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from jobagent.agents import assistant as a, sourcing
from jobagent.app import build_app
from jobagent.config import Settings

OFF = SimpleNamespace(use_llm=False)
ON = SimpleNamespace(use_llm=True, llm_provider="ollama")
ST = {"new": 4, "ready": 2, "applied": 5, "interviews": 1, "offers": 0, "dry_run": False, "gmail": True, "has_profile": True,
      "interviews_soon": 1, "replies": 1, "outreach_due": 2, "outreach_drafts": 3, "outreach_sent": 6, "outreach_replied": 1}


class Guide(unittest.TestCase):
    def test_every_topic_is_well_formed_and_navigable(self):
        views = {"home", "jobs", "applications", "interviews", "outreach", "inbox", "companies", "insights", "settings", "help"}
        does = {"refresh", "addjob", "outreach_add", "interview_add", "offer_add"}
        self.assertEqual(len({t["id"] for t in a.GUIDE}), len(a.GUIDE))
        for t in a.GUIDE:
            self.assertTrue(t["text"] and t["kw"] and t["actions"], t["id"]); self.assertLess(len(t["text"]), 520, t["id"])
            for act in t["actions"]:
                self.assertTrue(act.get("view") in views or act.get("do") in does, (t["id"], act))

    def test_common_questions_hit_the_right_topic_instantly(self):
        cases = {"How do I email a recruiter?": "outreach", "how are jobs matched to me": "match-score",
                 "Can it apply on company websites for me?": "website-apply", "does it scrape linkedin": "linkedin",
                 "how do I save a job from another website": "save-job", "compare my offers": "offers",
                 "will it make up skills on my resume": "grounding", "download my cover letter as pdf": "downloads",
                 "how do I practise interview questions": "practice", "add a company to the watchlist": "career-sites",
                 "where is my data stored": "data", "switch to dark theme": "appearance", "what is practice mode": "modes",
                 "how to change minimum salary filter": "preferences", "check my resume health": "resume-health",
                 "how do I follow up": "followups", "is it free": "cost", "how do i add my resume": "profile", "autopilot": "autopilot",
                 "send a thank you note": "interviews", "why is my score low": "match-score"}
        for q, tid in cases.items():
            r = a.answer(OFF, q, ST)
            self.assertEqual(r["answer"], a.BY_ID[tid]["text"], q); self.assertIn(r["method"], ("guide",), q)

    def test_next_steps_and_status_use_live_numbers(self):
        r = a.answer(OFF, "What should I do next?", ST)
        self.assertEqual(r["method"], "status")
        lines = r["answer"].splitlines()
        self.assertIn("1 interview in the next two days", lines[1]); self.assertIn("2 applications are written", r["answer"])
        self.assertIn("2 recruiter emails are due a follow-up", r["answer"]); self.assertEqual(r["actions"][0]["view"], "interviews")
        empty = a.answer(OFF, "what do i do now", {"has_profile": True, "gmail": True})
        self.assertIn("up to date", empty["answer"]); self.assertEqual(empty["actions"][0]["do"], "refresh")
        self.assertIn("5 applied", a.answer(OFF, "how many have I applied to so far", ST)["answer"])
        self.assertIn("Upload your resume", a.answer(OFF, "next step", {})["answer"])

    def test_off_topic_greeting_and_related_chip(self):
        self.assertEqual(a.answer(OFF, "what is the capital of France", ST)["method"], "none")
        self.assertTrue(a.answer(OFF, "write me a poem", ST)["answer"].startswith("This is the closest"))     # one stray word: not claimed as an answer
        self.assertIn("Hi!", a.answer(OFF, "hello", ST)["answer"])
        self.assertEqual(a.answer(OFF, "topic:offers", ST)["answer"], a.BY_ID["offers"]["text"])
        self.assertIn("Acme", a.answer(OFF, "topic:save-job", ST, product="Acme")["answer"])

    def test_model_answers_are_checked_and_fall_back(self):
        q = "I got an invitation, how should I get ready and remember the time"
        good = a.Answer(answer="Add it on the Interviews page, then practise under Practice.", topic_ids=["interviews", "practice", "made-up"])
        with mock.patch("jobagent.agents.llm_tailor.llm_json", return_value=good):
            r = a.answer(ON, q, ST)
        self.assertEqual(r["method"], "ollama"); self.assertIn("Interviews page", r["answer"])
        self.assertTrue(any(x.get("view") == "interviews" for x in r["actions"]))
        bad = a.Answer(answer="It sends 500 emails a day automatically.", topic_ids=["outreach"])
        with mock.patch("jobagent.agents.llm_tailor.llm_json", return_value=bad):
            r = a.answer(ON, q, ST)
        self.assertNotIn("500", r["answer"]); self.assertEqual(r["method"], "guide")          # invented number: discarded
        with mock.patch("jobagent.agents.llm_tailor.llm_json", side_effect=RuntimeError("down")):
            self.assertEqual(a.answer(ON, q, ST)["method"], "guide")


class Api(unittest.TestCase):
    def test_endpoint(self):
        d = tempfile.mkdtemp()
        c = TestClient(build_app(Settings(db_path=f"{d}/a.db", out_dir=f"{d}/o"), [sourcing.FixtureSource()]))
        info = c.get("/api/assistant").json()
        self.assertEqual(len(info["topics"]), len(a.GUIDE)); self.assertTrue(info["starters"])
        r = c.post("/api/assistant", json={"message": "how do I email a recruiter", "history": [{"role": "user", "text": "hi"}]}).json()
        self.assertEqual(r["actions"][0]["view"], "outreach")
        nxt = c.post("/api/assistant", json={"message": "what should I do next?"}).json()
        self.assertIn("Upload your resume", nxt["answer"])                                    # fresh install: sample profile
        self.assertEqual(c.post("/api/assistant", json={"message": "x" * 5000}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
