"""What ``common.term_matches`` counts as a hit — in BOTH directions.

``term_matches`` is the single helper behind four different profile surfaces:
`titles.include`, `titles.exclude`, keyword scoring and AI-company signals. Two
of those decide whether a posting is KEPT and one decides whether it is DROPPED,
so every widening here is simultaneously a recall gain on one side and a recall
loss on the other. These tests pin both sides on purpose:

  * hyphenation is formatting, not a different occupation (GH #298) — and the
    same equivalence that rescues `Front-End Engineer` for an include list also
    drops `Data-Scientist` for an exclude list;
  * a word that is both ordinary English and a technology only counts where it
    reads as the technology (GH #279) — `go` no longer scores on "go-to-market";
  * the bounded-match protections the old implementation gave must survive the
    widening: `intern` is still not *Internal*, `java` is still not *javascript*,
    and `front end` still does not match *frontend*.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \\
        -s skills/job-search/scripts/tests \\
        -t skills/job-search/scripts/tests

No network: every input here is a literal string.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import normalize, term_matches  # noqa: E402
from scoring import assess_title  # noqa: E402


def hit(term: str, text: str) -> bool:
    """Match ``term`` against ``text`` the way production does (normalized text)."""
    return term_matches(term, normalize(text))


class SeparatorEquivalence(unittest.TestCase):
    """GH #298 — a hyphen and a space are the same word break."""

    SPELLINGS = [
        "Front End Engineer, Search Platform",
        "Front-End Engineer, Search Platform",
        "Front–End Engineer, Search Platform",   # en dash
        "Front‑End Engineer, Search Platform",   # non-breaking hyphen
        "Front—End Engineer, Search Platform",   # em dash
    ]

    def test_every_hyphen_spelling_matches_the_spaced_include_phrase(self):
        for title in self.SPELLINGS:
            with self.subTest(title=title):
                self.assertTrue(hit("front end engineer", title))

    def test_a_spaced_term_matches_a_hyphenated_title_and_the_reverse(self):
        self.assertTrue(hit("front end engineer", "Front-End Engineer"))
        self.assertTrue(hit("front-end engineer", "Front End Engineer"))

    def test_equivalent_decisions_for_every_spelling(self):
        """The reported symptom: identical titles, one routed to review."""
        cfg = {"include": ["frontend engineer", "front end engineer"]}
        decisions = {assess_title(t, cfg)["decision"] for t in self.SPELLINGS}
        self.assertEqual(decisions, {"match"})

    def test_hyphen_deep_inside_a_longer_title(self):
        cfg = {"include": ["frontend engineer", "front end engineer"]}
        result = assess_title("Sr. Front-End Engineer - Business Systems", cfg)
        self.assertEqual(result["decision"], "match")

    def test_separators_are_equivalent_but_never_elidable(self):
        """`front end` must not become `frontend`; a profile lists that spelling."""
        self.assertFalse(hit("front end engineer", "Frontend Engineer"))
        self.assertFalse(hit("full stack", "Fullstack Engineer"))

    def test_a_character_normalize_folds_away_can_still_match(self):
        """`&` is deleted from the TEXT, so a raw term carrying it never fired."""
        self.assertTrue(hit("fp&a analyst", "FP&A Analyst"))


class ExcludeSideMovesToo(unittest.TestCase):
    """The same widening, on the side where a match DROPS the posting."""

    CFG = {"include": ["software engineer"],
           "exclude": ["data scientist", "research scientist", "new grad"]}

    def test_hyphenated_title_now_hits_the_exclude_phrase(self):
        for title in ("Data Scientist", "Data-Scientist", "Data-Scientist, Ads"):
            with self.subTest(title=title):
                self.assertEqual(assess_title(title, self.CFG)["decision"], "no_match")

    def test_hyphenated_exclude_beats_a_matching_include(self):
        """`New-Grad Software Engineer` matches an include AND an exclude."""
        result = assess_title("New-Grad Software Engineer", self.CFG)
        self.assertEqual(result["decision"], "no_match")
        self.assertIn("title.excluded.new grad", result["rule_ids"])

    def test_plurals_still_reach_the_exclude_list(self):
        """A strict boundary would have LEAKED the plural spelling."""
        self.assertTrue(hit("data scientist", "Data Scientists, Ads"))
        self.assertEqual(assess_title("Data Scientists, Ads", self.CFG)["decision"],
                         "no_match")

    def test_an_unrelated_title_is_untouched(self):
        self.assertEqual(assess_title("Software Engineer", self.CFG)["decision"],
                         "match")


class BoundariesSurviveTheWidening(unittest.TestCase):
    """The protections the old `\\b` path gave must not be traded away."""

    def test_short_token_does_not_match_a_longer_word(self):
        self.assertFalse(hit("intern", "Internal Tools Engineer"))
        self.assertFalse(hit("intern", "Software Engineering Internship"))
        self.assertFalse(hit("java", "JavaScript Engineer"))
        self.assertFalse(hit("sales", "Salesforce Platform Engineer"))
        self.assertFalse(hit("director", "Directory Services Engineer"))
        self.assertFalse(hit("manager", "Management Software Engineer"))

    def test_a_trailing_english_inflection_still_counts(self):
        self.assertTrue(hit("intern", "Engineering Interns, Summer"))
        self.assertTrue(hit("software engineer", "Software Engineering, Backend"))
        self.assertTrue(hit("software engineer", "Software Engineers, Platform"))

    def test_a_symbol_term_keeps_matching_on_its_symbol_edge(self):
        self.assertTrue(hit("c++", "Senior C++ Engineer"))
        self.assertTrue(hit("ci/cd", "Owns CI/CD pipelines"))
        self.assertTrue(hit(".net", "ASP.NET services"))

    def test_an_empty_or_punctuation_only_term_never_matches(self):
        self.assertFalse(hit("", "Software Engineer"))
        self.assertFalse(hit("   ", "Software Engineer"))
        self.assertFalse(hit("!!", "Software Engineer"))


class GoIsNotEveryGo(unittest.TestCase):
    """GH #279 parts 1-2 — the Go language versus the English verb."""

    ENGLISH = [
        "You will go through a structured interview process. We work in C++, "
        "Python and Java.",
        "Partner with go-to-market teams on launch readiness.",
        "Our go-to-market motion is API-led and data-driven.",
        "Watch your code go live in production on day one.",
        "We go above and beyond for our customers.",
        "Your first pull request is ready to go by the end of week one.",
        "Manage your account on the go from our mobile app.",
        "The team runs a go/no-go review before every release.",
        "Financial Analyst, Go-To-Market (GTM) FP&A",
    ]

    LANGUAGE = [
        "You will write Go and Python microservices.",
        "5+ years of experience with Go.",
        "Languages: Go, Rust, Python.",
        "We are hiring a Go developer for the payments backend.",
        "Software Engineer, Go",
        "Go Engineer (Backend)",
        "Services are written in Go and deployed on Kubernetes.",
        "Migrating our Python services to Go.",
        "Go 1.22 generics experience preferred.",
        "Strong knowledge of Go, gRPC and protobuf.",
        "Familiar with Go modules and goroutines.",
    ]

    def test_ordinary_english_is_not_go_evidence(self):
        for text in self.ENGLISH:
            with self.subTest(text=text):
                self.assertFalse(hit("go", text))

    def test_genuine_language_context_still_scores(self):
        for text in self.LANGUAGE:
            with self.subTest(text=text):
                self.assertTrue(hit("go", text))

    def test_one_credible_occurrence_is_enough(self):
        """A JD may say both; the language mention must still win."""
        self.assertTrue(hit(
            "go",
            "Partner with go-to-market teams. Backend services are written in Go."))

    def test_an_english_only_title_is_not_rescued_by_a_go_include(self):
        """The title gate reads the same helper, so the rescue path closes too."""
        cfg = {"include": ["go", "backend engineer"]}
        result = assess_title("Financial Analyst, Go-To-Market (GTM) FP&A", cfg)
        self.assertNotEqual(result["decision"], "match")
        self.assertNotIn("title.included.go", result["rule_ids"])

    def test_a_real_go_title_still_matches(self):
        cfg = {"include": ["go", "backend engineer"]}
        result = assess_title("Senior Go Engineer, Payments", cfg)
        self.assertEqual(result["decision"], "match")

    def test_the_guard_does_not_invent_a_match_on_golang_alone(self):
        """`golang` is its own keyword; `go` must not double-count it."""
        self.assertFalse(hit("go", "We use Golang extensively."))
        self.assertTrue(hit("golang", "We use Golang extensively."))

    def test_unambiguous_keywords_are_untouched_by_the_guard(self):
        self.assertTrue(hit("python", "We use Python and Django."))
        self.assertTrue(hit("kubernetes", "Runs on Kubernetes."))
        self.assertFalse(hit("python", "We use Ruby and Rails."))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
