"""Occupation-evidence regressions for GitHub issues #267 and #274.

All titles and profiles are fictional. The frozen matrix separates phrases that
establish the target occupation from broad words that merely retrieve adjacent
titles. A missing primary phrase is reviewable uncertainty, never a hard drop.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
for path in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import JobPosting  # noqa: E402
from registry import Registry  # noqa: E402
from scoring import assess_title  # noqa: E402
import search_jobs  # noqa: E402


PROFILES = {
    "mobile": {
        "include": ["software engineer", "ios engineer", "mobile engineer",
                    "android engineer", "react native developer", "ios",
                    "mobile", "android", "react native", "application"],
        "primary": ["ios engineer", "mobile platform engineer",
                    "android engineer", "react native developer"],
    },
    "ios_only": {
        # Keep the broad mobile retrieval surface, but make the candidate's
        # explicit platform negatives decisive before primary evidence.
        "include": ["software engineer", "ios engineer", "mobile engineer",
                    "android engineer", "react native developer", "ios",
                    "mobile", "android", "react native", "application"],
        "primary": ["ios engineer", "mobile platform engineer"],
        "exclude": ["android", "react native"],
    },
    "sdet": {
        "include": ["software engineer", "sdet", "qa automation",
                    "test infrastructure", "automation", "performance", "quality"],
        "primary": ["qa automation sdet",
                    "software engineer test infrastructure"],
    },
    "game": {
        "include": ["software engineer", "gameplay engineer", "engine programmer",
                    "graphics engineer", "gameplay", "rendering"],
        "primary": ["gameplay engineer"],
    },
    "robotics": {
        "include": ["software engineer", "robotics engineer", "autonomy engineer",
                    "motion planning", "robotics", "autonomy"],
        "primary": ["robotics engineer"],
    },
    "writer": {
        "include": ["technical writer", "developer documentation",
                    "api documentation", "docs engineer"],
        "primary": ["developer documentation", "api documentation", "docs engineer"],
    },
    "compiler": {
        "include": ["software engineer", "compiler engineer", "compiler", "toolchain"],
        "primary": ["compiler engineer"],
    },
    "database": {
        "include": ["software engineer", "database engineer", "storage engineer",
                    "postgres product engineer", "object storage", "database", "storage"],
        "primary": ["database engineer", "storage engineer",
                    "postgres product engineer", "object storage"],
    },
    "manager": {
        "include": ["engineering manager", "software engineering manager",
                    "platform engineering manager"],
        "primary": ["software engineering manager", "platform engineering manager"],
    },
}

CASES = (
    ("mobile_native_ios", "mobile", "Senior iOS Engineer", "match"),
    ("mobile_platform", "mobile", "Mobile Platform Engineer", "match"),
    ("mobile_android", "mobile", "Senior Android Engineer", "match"),
    ("mobile_react_native", "mobile", "React Native Developer", "match"),
    ("mobile_mechanic", "mobile", "Mobile Mechanic", "review"),
    ("mobile_sales", "mobile", "Mobile Sales Representative", "review"),
    ("mobile_application_security", "mobile",
     "Senior Security Engineer, Application Security", "review"),
    ("mobile_backend_notifications", "mobile",
     "Software Engineer, Notifications", "review"),
    ("mobile_web_experience", "mobile",
     "Senior Software Engineer, Web Experience", "review"),
    ("ios_only_android_negative", "ios_only",
     "Senior Android Engineer", "no_match"),
    ("ios_only_react_native_negative", "ios_only",
     "React Native Developer", "no_match"),
    ("sdet_qa_automation", "sdet", "QA Automation SDET", "match"),
    ("sdet_test_infrastructure", "sdet",
     "Software Engineer, Test Infrastructure", "match"),
    ("sdet_manual_qa", "sdet", "Manual QA Analyst", "review"),
    ("sdet_business_automation", "sdet", "IT Automation Engineer", "review"),
    ("sdet_backend_performance", "sdet",
     "Software Engineer, EKS Scalability and Performance", "review"),
    ("sdet_customer_quality", "sdet", "Customer Quality Analyst", "review"),
    ("sdet_manufacturing_quality", "sdet",
     "Manufacturing Quality Engineer", "review"),
    ("sdet_ai_automation", "sdet",
     "Software Engineer, Core AI Automation", "review"),
    ("game_gameplay", "game", "Senior Gameplay Engineer", "match"),
    ("game_storage", "game", "Senior Software Engineer, Storage", "review"),
    ("robotics_target", "robotics", "Senior Robotics Engineer", "match"),
    ("robotics_fullstack_tooling", "robotics",
     "Full Stack Software Engineer, Deployment Tooling", "review"),
    ("writer_developer_docs", "writer", "Developer Documentation Writer", "match"),
    ("writer_life_sciences", "writer", "Technical Writer, Life Sciences", "review"),
    ("compiler_target", "compiler", "GPU Compiler Engineer", "match"),
    ("compiler_generic_tools", "compiler", "Software Engineer, Build Tools", "review"),
    ("database_postgres", "database", "Postgres Product Engineer", "match"),
    ("database_administrator", "database", "Database Administrator", "review"),
    ("manager_software", "manager", "Software Engineering Manager", "match"),
    ("manager_power_generation", "manager",
     "Generation Engineering Manager", "review"),
)


class PrimaryOccupationEvidenceTests(unittest.TestCase):
    def test_frozen_cross_occupation_matrix(self):
        decisions = {}
        for case_id, profile_name, title, expected in CASES:
            with self.subTest(case=case_id):
                actual = assess_title(title, PROFILES[profile_name])
                self.assertEqual(actual["decision"], expected)
                decisions[case_id] = actual["decision"]
        self.assertEqual(sum(v == "match" for v in decisions.values()), 12)
        self.assertEqual(sum(v == "review" for v in decisions.values()), 17)
        self.assertEqual(sum(v == "no_match" for v in decisions.values()), 2)

    def test_ios_only_negatives_do_not_narrow_the_broad_mobile_profile(self):
        expected_rules = {
            "Senior Android Engineer": "title.excluded.android",
            "React Native Developer": "title.excluded.react native",
        }
        for title, rule_id in expected_rules.items():
            with self.subTest(profile="ios_only", title=title):
                actual = assess_title(title, PROFILES["ios_only"])
                self.assertEqual(actual["decision"], "no_match")
                self.assertEqual(actual["rule_ids"], [rule_id])
            with self.subTest(profile="mobile", title=title):
                actual = assess_title(title, PROFILES["mobile"])
                self.assertEqual(actual["decision"], "match")
                self.assertTrue(any(
                    item.startswith("title.primary_occupation.")
                    for item in actual["rule_ids"]
                ))

    def test_review_names_the_matched_and_missing_evidence(self):
        actual = assess_title(
            "Senior Security Engineer, Application Security", PROFILES["mobile"])
        self.assertEqual(actual["decision"], "review")
        self.assertIn("title.primary_occupation_missing", actual["rule_ids"])
        self.assertIn("title_occupation_ambiguous", actual["review_reasons"])
        self.assertIn("title_primary_occupation_missing", actual["review_reasons"])
        self.assertIn("included:application", actual["evidence"])
        self.assertIn(
            "primary_expected:ios engineer,mobile platform engineer,"
            "android engineer,react native developer",
            actual["evidence"])

    def test_main_match_names_the_decisive_primary_phrase(self):
        actual = assess_title("Senior iOS Engineer", PROFILES["mobile"])
        self.assertEqual(actual["decision"], "match")
        self.assertIn("title.primary_occupation.ios engineer",
                      actual["rule_ids"])
        self.assertIn("primary:ios engineer", actual["evidence"])

    def test_primary_is_opt_in_for_backward_compatibility(self):
        cfg = {"include": ["software engineer", "gameplay engineer", "gameplay"]}
        without_primary = assess_title("Senior Software Engineer, Storage", cfg)
        with_empty_primary = assess_title(
            "Senior Software Engineer, Storage", {**cfg, "primary": []})
        self.assertEqual(without_primary, with_empty_primary)
        self.assertEqual(without_primary["decision"], "match")

    def test_primary_cannot_rescue_an_include_miss(self):
        actual = assess_title(
            "Senior Android Engineer",
            {"include": ["ios engineer"], "primary": ["android engineer"]})
        self.assertEqual(actual["decision"], "review")
        self.assertEqual(
            actual["rule_ids"],
            ["title.not_included", "title.occupation_ambiguous"])
        self.assertNotIn("primary:android engineer", actual["evidence"])

    def test_primary_cannot_override_an_explicit_exclude(self):
        cfg = {
            **PROFILES["mobile"],
            "exclude": ["manager"],
            "primary": ["mobile engineering manager"],
        }
        actual = assess_title("Mobile Engineering Manager", cfg)
        self.assertEqual(actual["decision"], "no_match")
        self.assertEqual(actual["rule_ids"], ["title.excluded.manager"])

    def test_word_filter_can_only_rescue_an_exclude_to_pipeline_review(self):
        profile = {
            "titles": {
                "include": ["ios engineer"],
                "primary": ["ios engineer"],
                "exclude": ["manager"],
                "word_filter": {"soft_exclude": [" manager"]},
            },
        }
        posting = JobPosting(
            source="board", company="Example Telecom",
            title="Mobile Engineering Manager",
            url="https://example.test/jobs/manager",
            description="Lead a fictional engineering group.")
        ctx = {
            "considered_urls": set(), "considered_pairs": set(),
            "skip_days": 0, "search_tokens": [], "ignore_search_log": True,
            "ai_native_keys": set(),
            "title_word_filter": search_jobs.title_filter.load_word_lists(profile),
        }
        kept, counts = search_jobs.filter_score_rank(
            [posting], profile, ctx, max_age=None, top_k=10,
            max_per_company=10, sponsor_index=None, company_levels={},
            registry=Registry([]),
            now=datetime(2026, 8, 26, tzinfo=timezone.utc))
        self.assertEqual(kept, [])
        self.assertEqual(counts["n_review"], 1)
        review = counts["review_postings"][0]
        self.assertEqual(
            review.filter_assessments["title"]["rule_ids"],
            ["title.excluded.manager"])
        self.assertIn("title_word_filter_override", review.review_reasons)

    def test_pipeline_routes_a_sibling_to_review_without_losing_the_target(self):
        postings = [
            JobPosting(
                source="board", company="Example Telecom",
                title="Senior iOS Engineer", url="https://example.test/jobs/ios",
                description="Build native mobile features for a fictional product."),
            JobPosting(
                source="board", company="Example Telecom",
                title="Senior Security Engineer, Application Security",
                url="https://example.test/jobs/security",
                description="Protect a fictional web service from security threats."),
        ]
        ctx = {
            "considered_urls": set(), "considered_pairs": set(),
            "skip_days": 0, "search_tokens": [], "ignore_search_log": True,
            "ai_native_keys": set(),
        }
        kept, counts = search_jobs.filter_score_rank(
            postings, {"titles": PROFILES["mobile"]}, ctx,
            max_age=None, top_k=10, max_per_company=10, sponsor_index=None,
            company_levels={}, registry=Registry([]),
            now=datetime(2026, 8, 26, tzinfo=timezone.utc))
        self.assertEqual([p.title for p in kept], ["Senior iOS Engineer"])
        self.assertEqual(
            [p.title for p in counts["review_postings"]],
            ["Senior Security Engineer, Application Security"])
        self.assertEqual(counts["n_review"], 1)
        self.assertEqual(counts["n_occupation_ambiguous_overflow"], 0)
        self.assertIn(
            "title.primary_occupation.ios engineer",
            kept[0].filter_assessments["title"]["rule_ids"])
        self.assertIn(
            "primary:ios engineer",
            kept[0].filter_assessments["title"]["evidence"])


if __name__ == "__main__":
    unittest.main()
