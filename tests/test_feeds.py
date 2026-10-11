import json
import unittest

from jobagent.agents.feeds import RemoteOKSource, RemotiveSource, WWRSource, html_to_text
from jobagent.agents.sourcing import passes_filters, run_sourcing
from jobagent.fixtures import SAMPLE_PROFILE
from jobagent.schemas import CandidateProfile, JobListing
from tests.test_system import make

P = CandidateProfile(**{**SAMPLE_PROFILE, "preferences": {"target_titles": ["security", "detection"],
                                                          "target_locations": ["Bengaluru, India", "India - Remote"]}})


def job(**kw):
    return JobListing(**{"id": "x", "source": "t", "url": "u", "title": "Security Engineer", "company": "c",
                         "description": "d", "remote": True, **kw})


class Feeds(unittest.TestCase):
    def test_html_to_text_keeps_lines(self):
        t = html_to_text("<p>Requirements</p><ul><li>Python</li><li>Splunk &amp; SPL</li></ul>")
        self.assertEqual(t.split("\n"), ["Requirements", "Python", "Splunk & SPL"])

    def test_escaped_html_from_rss(self):
        self.assertIn("Hello", html_to_text("&lt;p&gt;Hello&lt;/p&gt;"))

    def test_remotive_parse_and_dedupe_across_queries(self):
        payload = json.dumps({"jobs": [{"id": 1, "url": "u", "title": "Detection Engineer", "company_name": "A",
                                        "candidate_required_location": "Worldwide", "description": "<p>x</p>"}]}).encode()
        jobs = RemotiveSource(searches=("a", "b"), get=lambda u: payload).fetch()
        self.assertEqual([j.id for j in jobs], ["remotive:1"])
        self.assertEqual(jobs[0].location, "Worldwide")

    def test_remoteok_skips_legal_notice(self):
        payload = json.dumps([{"legal": "x"}, {"id": "9", "position": "SOC Engineer", "company": "B", "url": "u",
                                               "location": "", "description": "<b>d</b>"}]).encode()
        self.assertEqual(len(RemoteOKSource(tags=("security",), get=lambda u: payload).fetch()), 1)

    def test_wwr_rss(self):
        rss = (b"<rss><channel><item><title>Acme: Senior Detection Engineer</title><link>https://x/1</link>"
               b"<region>Anywhere in the World</region><description>&lt;p&gt;Splunk&lt;/p&gt;</description></item>"
               b"</channel></rss>")
        j = WWRSource(get=lambda u: rss).fetch()[0]
        self.assertEqual((j.company, j.title, j.location), ("Acme", "Senior Detection Engineer", "Anywhere in the World"))

    def test_location_filter(self):
        self.assertIsNone(passes_filters(job(location="Worldwide"), P))
        self.assertIsNone(passes_filters(job(location="India"), P))
        self.assertIsNone(passes_filters(job(location=""), P))
        self.assertIsNone(passes_filters(job(location="Remote"), P))          # bare "Remote" = unspecified
        self.assertIsNone(passes_filters(job(location="Mumbai,", remote=False), P))   # India city via target country
        self.assertIn("restricted", passes_filters(job(location="USA"), P))
        self.assertIn("restricted", passes_filters(job(location="Americas, Europe, Israel"), P))
        self.assertIn("outside", passes_filters(job(location="Austin, TX", remote=False), P))

    def test_failing_feed_does_not_stop_others(self):
        _, store, _ = make()
        def boom(u): raise OSError("down")
        ok = json.dumps({"jobs": [{"id": 5, "url": "u", "title": "Security Engineer", "company_name": "Z",
                                   "candidate_required_location": "Worldwide", "description": "Python"}]}).encode()
        new = run_sourcing(store, [RemoteOKSource(get=boom), RemotiveSource(searches=("s",), get=lambda u: ok)], P)
        self.assertEqual(len(new), 1)


if __name__ == "__main__":
    unittest.main()
