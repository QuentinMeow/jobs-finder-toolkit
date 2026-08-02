"""The candidate's three title word classes, and the first-search recency window.

Both are owner decisions (2026-08-01) whose failure mode is a SILENT loss, so what
these tests hold is not "the filter works" but "nothing disappears without saying
so": a hard drop is counted, a soft/include hit is never dropped AND never kept
without a mark, an unconfigured profile filters nothing, and a company nobody has
ever searched is not age-filtered out of its own first search.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \\
        -s skills/job-search/scripts/tests \\
        -t skills/job-search/scripts/tests

No network: everything here is a hand-built posting or a dict.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import search_jobs  # noqa: E402
import title_filter  # noqa: E402
from common import JobPosting  # noqa: E402
from registry import Registry  # noqa: E402

DROP = title_filter.ACTION_DROP
REVIEW = title_filter.ACTION_REVIEW
KEEP = title_filter.ACTION_KEEP


def _profile(hard=(), soft=(), include=(), **rest):
    prof = {"titles": {"word_filter": {"hard_exclude": list(hard),
                                       "soft_exclude": list(soft),
                                       "include": list(include)}}}
    prof.update(rest)
    return prof


def _filter(hard=(), soft=(), include=()):
    return title_filter.load_word_lists(_profile(hard, soft, include))


# --------------------------------------------------------------------------- #
# The three classes
# --------------------------------------------------------------------------- #
class ThreeClassesTests(unittest.TestCase):
    def test_hard_excluded_word_always_drops(self):
        wf = _filter(hard=["intern"])
        verdict = wf.classify("Software Engineering Intern")
        self.assertEqual(verdict.action, DROP)
        self.assertEqual(verdict.hard_hits, ("intern",))
        self.assertFalse(wf.prefilter("Software Engineering Intern"))

    def test_soft_excluded_word_is_kept_and_marked_never_dropped(self):
        wf = _filter(soft=["manager"])
        verdict = wf.classify("Software Engineer, Mission Manager")
        self.assertEqual(verdict.action, REVIEW)
        self.assertEqual(verdict.soft_hits, ("manager",))
        # Kept for the (expensive) detail fetch: the JD is what decides.
        self.assertTrue(wf.prefilter("Software Engineer, Mission Manager"))
        self.assertEqual(verdict.review_reasons, ["title_soft_excluded:manager"])
        self.assertTrue(verdict.reason_notes)

    def test_include_word_is_kept_and_marked_for_judgement(self):
        wf = _filter(include=["principal"])
        verdict = wf.classify("Principal Infrastructure Engineer")
        self.assertEqual(verdict.action, REVIEW)
        self.assertEqual(verdict.include_hits, ("principal",))
        self.assertTrue(wf.prefilter("Principal Infrastructure Engineer"))
        self.assertEqual(verdict.review_reasons, ["title_include_signal:principal"])

    def test_an_unhit_title_is_left_entirely_to_the_ordinary_gate(self):
        wf = _filter(hard=["intern"], soft=["manager"], include=["principal"])
        verdict = wf.classify("Senior Backend Engineer")
        self.assertEqual(verdict.action, KEEP)
        self.assertEqual(verdict.review_reasons, [])
        self.assertEqual(verdict.reason_notes, [])


# --------------------------------------------------------------------------- #
# Precedence: hard_exclude > include > soft_exclude
# --------------------------------------------------------------------------- #
class PrecedenceTests(unittest.TestCase):
    def test_hard_exclude_beats_include_on_the_same_title(self):
        wf = _filter(hard=["intern"], include=["principal"])
        verdict = wf.classify("Principal Engineer Intern")
        self.assertEqual(verdict.action, DROP)
        # The include hit is not even reported: the drop is not negotiable.
        self.assertEqual(verdict.include_hits, ())

    def test_hard_exclude_beats_soft_exclude_on_the_same_title(self):
        wf = _filter(hard=["intern"], soft=["manager"])
        self.assertEqual(wf.classify("Intern, Manager Tools").action, DROP)

    def test_the_same_word_in_two_classes_warns_and_hard_wins(self):
        wf = _filter(hard=["manager"], soft=["manager"])
        self.assertEqual(wf.classify("Engineering Manager").action, DROP)
        self.assertTrue(any("'manager'" in w and "hard_exclude" in w
                            for w in wf.warnings), wf.warnings)

    def test_padding_does_not_hide_a_cross_class_collision(self):
        """' manager' and 'manager' are the same word in two classes."""
        wf = _filter(hard=[" manager"], include=["manager"])
        self.assertTrue(any("'manager'" in w for w in wf.warnings), wf.warnings)

    def test_include_and_soft_hits_both_reach_review_together(self):
        wf = _filter(soft=["manager"], include=["principal"])
        verdict = wf.classify("Principal Engineer, Manager Tools")
        self.assertEqual(verdict.action, REVIEW)
        # Include is reported first (precedence), but neither is lost.
        self.assertEqual(verdict.review_reasons,
                         ["title_include_signal:principal",
                          "title_soft_excluded:manager"])


# --------------------------------------------------------------------------- #
# Matching rules: case-insensitive, whole-word (+ short English inflection)
# --------------------------------------------------------------------------- #
class MatchingRuleTests(unittest.TestCase):
    def test_matching_is_case_insensitive_in_both_directions(self):
        for words, title in ((["INTERN"], "software engineering intern"),
                             (["intern"], "SOFTWARE ENGINEERING INTERN"),
                             (["InTeRn"], "Software Engineering InTeRn")):
            with self.subTest(words=words, title=title):
                self.assertEqual(_filter(hard=words).classify(title).action, DROP)

    def test_a_word_glued_inside_a_longer_word_is_not_a_hit(self):
        cases = (("intern", "Software Engineer, Internal Developer Platform"),
                 ("director", "Systems Engineer, Active Directory"),
                 ("sales", "Software Engineer, Salesforce Platform"),
                 ("co-op", "Software Engineer, Co-operative Caching"))
        for word, title in cases:
            with self.subTest(word=word, title=title):
                self.assertEqual(_filter(hard=[word]).classify(title).action, KEEP)

    def test_manager_does_not_match_management(self):
        """The documented choice: '-ment' is not an English inflection."""
        wf = _filter(hard=["manager"])
        self.assertEqual(wf.classify("Engineer, Configuration Management").action,
                         KEEP)
        self.assertEqual(wf.classify("Engineering Manager").action, DROP)

    def test_a_short_inflection_still_counts(self):
        """Why a candidate writes 'recruit' instead of three spellings."""
        wf = _filter(hard=["recruit"])
        for title in ("Technical Recruiter", "Recruiting Coordinator",
                      "Recruiters, Engineering"):
            with self.subTest(title=title):
                self.assertEqual(wf.classify(title).action, DROP)

    def test_a_leading_space_demands_literal_whitespace(self):
        wf = _filter(hard=[" manager"])
        self.assertEqual(wf.classify("Engineering Manager").action, DROP)
        for kept in ("Software Engineer (Manager Tools)",
                     "Lead Software Engineer/Manager"):
            with self.subTest(title=kept):
                self.assertEqual(wf.classify(kept).action, KEEP)

    def test_odd_board_whitespace_is_normalised_before_matching(self):
        wf = _filter(hard=[" vp "])
        for title in ("VP\tEngineering", "VP  Engineering", " VP Engineering "):
            with self.subTest(title=title):
                self.assertEqual(wf.classify(title).action, DROP)

    def test_a_multiword_phrase_matches_as_a_phrase(self):
        wf = _filter(soft=["data scientist"])
        self.assertEqual(wf.classify("Data Scientist, Platform").action, REVIEW)
        self.assertEqual(wf.classify("Data Engineer, Scientist Tools").action, KEEP)


# --------------------------------------------------------------------------- #
# Missing / empty / malformed config
# --------------------------------------------------------------------------- #
class DegradationTests(unittest.TestCase):
    def test_a_profile_with_no_word_filter_block_is_inert(self):
        wf = title_filter.load_word_lists({"titles": {"include": ["engineer"]}})
        self.assertFalse(wf.configured)
        self.assertEqual(wf.warnings, ())
        for title in ("Software Engineering Intern", "Engineering Manager",
                      "Principal Engineer", ""):
            with self.subTest(title=title):
                self.assertEqual(wf.classify(title).action, KEEP)
                self.assertTrue(wf.prefilter(title))

    def test_an_empty_profile_and_none_are_inert(self):
        for profile in ({}, None, {"titles": None}, {"titles": {"word_filter": None}}):
            with self.subTest(profile=profile):
                self.assertFalse(title_filter.load_word_lists(profile).configured)

    def test_three_empty_lists_are_inert(self):
        wf = _filter(hard=[], soft=[], include=[])
        self.assertFalse(wf.configured)
        self.assertEqual(wf.classify("Software Engineering Intern").action, KEEP)

    def test_blank_and_whitespace_only_entries_are_dropped_from_the_lists(self):
        wf = _filter(hard=["intern", "", "   ", None])
        self.assertEqual(wf.hard_exclude, ("intern",))

    def test_a_non_list_class_is_reported_and_treated_as_empty(self):
        wf = title_filter.load_word_lists(
            {"titles": {"word_filter": {"hard_exclude": "intern"}}})
        self.assertEqual(wf.hard_exclude, ())
        self.assertTrue(any("must be a list" in w for w in wf.warnings), wf.warnings)

    def test_a_non_mapping_word_filter_is_reported_and_inert(self):
        wf = title_filter.load_word_lists(
            {"titles": {"word_filter": ["intern", "manager"]}})
        self.assertFalse(wf.configured)
        self.assertTrue(wf.warnings)

    def test_duplicate_words_are_collapsed_without_a_collision_warning(self):
        wf = _filter(hard=["intern", "Intern", "INTERN"])
        self.assertEqual(wf.hard_exclude, ("intern",))
        self.assertEqual(wf.warnings, ())


# --------------------------------------------------------------------------- #
# The pipeline: a hard drop is COUNTED, a soft/include hit reaches the AI step
# --------------------------------------------------------------------------- #
_NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _posting(title, company="Example Corp", age_days=1.0):
    # `filter_score_rank` recomputes age from `posted_at`, so the fixture sets the
    # date rather than the derived field.
    return JobPosting(
        source="board", company=company, title=title,
        url=f"https://example.test/{abs(hash((company, title))) % 99999}",
        location="Remote, US",
        description="Build and operate backend services in Python.",
        posted_at=_NOW - timedelta(days=age_days))


class _PipelineCase(unittest.TestCase):
    """filter_score_rank against a hand-built posting set (no fetch, no network)."""

    NOW = _NOW

    def _ctx(self, profile, search_tokens=None):
        ctx = {
            "considered_urls": set(),
            "considered_pairs": set(),
            "skip_days": 7,
            "search_tokens": search_tokens or {},
            "ignore_search_log": False,
            "ai_native_keys": set(),
            "widen_first_search": bool(
                (profile.get("company_search_log") or {}).get(
                    "widen_first_search", True)),
            "first_search_max_age_days": (
                profile.get("company_search_log") or {}).get(
                    "first_search_max_age_days"),
            "title_word_filter": title_filter.load_word_lists(profile),
        }
        return ctx

    def _run(self, postings, profile, *, max_age=None, search_tokens=None):
        return search_jobs.filter_score_rank(
            postings, profile, self._ctx(profile, search_tokens),
            max_age=max_age, top_k=None, max_per_company=0,
            sponsor_index=None, company_levels={}, registry=Registry({}),
            now=self.NOW)


class HardExcludeIsCountedNotSilentTests(_PipelineCase):
    def setUp(self):
        self.profile = {"titles": {"include": ["software engineer"],
                                   "word_filter": {"hard_exclude": ["intern"]}},
                        "location": {"us_only": False, "allow_remote": True}}

    def test_a_hard_excluded_posting_is_dropped_and_counted(self):
        kept, counts = self._run(
            [_posting("Software Engineering Intern"),
             _posting("Software Engineer, Platform")], self.profile)
        self.assertEqual([p.title for p in kept], ["Software Engineer, Platform"])
        self.assertEqual(counts["n_title_hard_excluded"], 1)
        self.assertEqual(counts["n_review"], 0)


class SoftAndIncludeReachTheAiJudgementStepTests(_PipelineCase):
    def _profile_with(self, **word_filter):
        return {"titles": {"include": ["software engineer"],
                           "exclude": ["manager", "principal"],
                           "word_filter": word_filter},
                "location": {"us_only": False, "allow_remote": True}}

    def test_a_soft_hit_survives_a_title_gate_that_would_have_dropped_it(self):
        """`titles.exclude` says manager; `soft_exclude` says let the AI read it."""
        profile = self._profile_with(soft_exclude=["manager"])
        kept, counts = self._run([_posting("Engineering Manager")], profile)
        self.assertEqual(kept, [])                    # not on the shortlist
        self.assertEqual(counts["n_review"], 1)       # but NOT dropped either
        review = counts["review_postings"][0]
        self.assertIn("title_soft_excluded:manager", review.review_reasons)
        self.assertIn("title_word_filter_override", review.review_reasons)
        self.assertEqual(counts["n_title_word_filter_review"], 1)
        self.assertEqual(counts["n_title_hard_excluded"], 0)

    def test_an_include_hit_survives_the_same_gate(self):
        profile = self._profile_with(include=["principal"])
        _, counts = self._run([_posting("Principal Software Engineer")], profile)
        self.assertEqual(counts["n_review"], 1)
        self.assertIn("title_include_signal:principal",
                      counts["review_postings"][0].review_reasons)

    def test_the_review_row_carries_the_reason_a_human_or_ai_reads(self):
        profile = self._profile_with(include=["principal"])
        _, counts = self._run([_posting("Principal Software Engineer")], profile)
        why = " ".join(counts["review_postings"][0].reasons)
        self.assertIn("title include signal: principal", why)
        self.assertIn("read the JD", why)

    def test_a_matching_title_with_a_soft_hit_stays_on_the_shortlist_but_marked(self):
        """A soft/include hit must not be a silent KEEP either."""
        profile = {"titles": {"include": ["software engineer"],
                              "word_filter": {"include": ["platform"]}},
                   "location": {"us_only": False, "allow_remote": True}}
        kept, counts = self._run([_posting("Software Engineer, Platform")], profile)
        self.assertEqual(counts["n_review"], 0)
        self.assertEqual(len(kept), 1)
        self.assertTrue(any("title include signal: platform" in r
                            for r in kept[0].reasons), kept[0].reasons)

    def test_a_soft_hit_does_not_override_a_non_title_gate(self):
        """Scope: the word classes answer the TITLE question, nothing else."""
        profile = {"titles": {"include": ["software engineer"],
                              "word_filter": {"include": ["principal"]}},
                   "location": {"us_only": True, "allow_remote": False,
                                "require_match": True, "preferred": ["boston"]}}
        posting = _posting("Principal Software Engineer")
        posting.location = "Berlin, Germany"
        kept, counts = self._run([posting], profile)
        self.assertEqual(kept, [])
        self.assertEqual(counts["n_review"], 0)

    def test_an_unconfigured_profile_changes_nothing_in_the_pipeline(self):
        profile = {"titles": {"include": ["software engineer"],
                              "exclude": ["manager"]},
                   "location": {"us_only": False, "allow_remote": True}}
        kept, counts = self._run(
            [_posting("Software Engineer, Platform"),
             _posting("Engineering Manager")], profile)
        self.assertEqual([p.title for p in kept], ["Software Engineer, Platform"])
        self.assertEqual(counts["n_title_hard_excluded"], 0)
        self.assertEqual(counts["n_title_word_filter_review"], 0)


# --------------------------------------------------------------------------- #
# First-search recency window
# --------------------------------------------------------------------------- #
class FirstSearchDetectionTests(unittest.TestCase):
    def test_a_company_absent_from_the_log_is_a_first_search(self):
        p = _posting("Software Engineer", company="Never Searched Inc")
        self.assertTrue(search_jobs.is_first_search(p, {}, None))

    def test_a_company_present_under_any_match_key_is_not(self):
        p = _posting("Software Engineer", company="Example Corp")
        tokens = {"example corp": date(2025, 1, 1)}
        self.assertFalse(search_jobs.is_first_search(p, tokens, None))

    def test_an_ancient_log_row_still_counts_as_searched_before(self):
        """'Ever' is the question, not 'lately' — that is is_recently_searched."""
        p = _posting("Software Engineer", company="Example Corp")
        tokens = {"example corp": date(2019, 1, 1)}
        self.assertFalse(search_jobs.is_first_search(p, tokens, None))
        self.assertFalse(search_jobs.is_recently_searched(
            p, tokens, 7, date(2026, 1, 2), None))


class FirstSearchWindowTests(_PipelineCase):
    PROFILE = {
        "titles": {"include": ["software engineer"]},
        "location": {"us_only": False, "allow_remote": True},
        "company_search_log": {"skip_within_days": 7,
                               "first_search_max_age_days": None},
    }

    def _old_and_new(self, company):
        return [_posting("Software Engineer, Platform", company=company,
                         age_days=90.0),
                _posting("Software Engineer, Core", company=company, age_days=1.0)]

    def test_a_first_search_is_not_age_filtered(self):
        kept, counts = self._run(self._old_and_new("Never Searched Inc"),
                                 self.PROFILE, max_age=3)
        self.assertEqual(len(kept), 2, [p.title for p in kept])
        self.assertEqual(counts["n_first_search_widened"], 1)
        self.assertTrue(counts["widening_active"])

    def test_a_previously_searched_company_keeps_the_narrow_window(self):
        kept, counts = self._run(
            self._old_and_new("Example Corp"), self.PROFILE, max_age=3,
            search_tokens={"example corp": date(2025, 6, 1)})
        self.assertEqual([p.title for p in kept], ["Software Engineer, Core"])
        self.assertEqual(counts["n_first_search_widened"], 0)

    def test_a_bounded_first_search_window_is_honoured(self):
        profile = dict(self.PROFILE)
        profile["company_search_log"] = {"first_search_max_age_days": 30}
        kept, counts = self._run(self._old_and_new("Never Searched Inc"),
                                 profile, max_age=3)
        self.assertEqual([p.title for p in kept], ["Software Engineer, Core"])
        self.assertEqual(counts["first_search_max_age_days"], 30)

    def test_widening_can_be_turned_off(self):
        profile = dict(self.PROFILE)
        profile["company_search_log"] = {"widen_first_search": False}
        kept, counts = self._run(self._old_and_new("Never Searched Inc"),
                                 profile, max_age=3)
        self.assertEqual([p.title for p in kept], ["Software Engineer, Core"])
        self.assertFalse(counts["widening_active"])

    def test_no_age_filter_at_all_makes_the_widening_a_no_op(self):
        kept, counts = self._run(self._old_and_new("Never Searched Inc"),
                                 self.PROFILE, max_age=None)
        self.assertEqual(len(kept), 2)
        self.assertFalse(counts["widening_active"])
        self.assertEqual(counts["n_first_search_widened"], 0)

    def test_the_header_says_why_the_run_looks_different(self):
        meta = {"max_age_days": 3, "first_search_widening": True,
                "first_search_max_age_days": None, "profile": "example",
                "generated": "2026-01-02 00:00 UTC", "visa_policy": "exclude_negative",
                "n_companies": 1, "aggregators": [], "n_raw": 2, "errors": [],
                "max_per_company": 0}
        md = search_jobs.render_markdown([], {"name": "Example"}, meta)
        self.assertIn("first search at an employer", md)


if __name__ == "__main__":
    unittest.main()
