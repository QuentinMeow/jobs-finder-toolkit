"""Skip-logic identity tests: company-name variants must not escape the skips.

Regression for the 2026-07-22 gap where an aggregator's longer legal-name variant
("Acme Ltd.") escaped both the company-search-log recently-searched skip and the
applications-log already-considered skip because the log rows stored the shorter
registry name ("Acme"). Both skips now resolve every company through the registry's
match keys (name/alias/token + suffix-variant comparable forms), so the variant is
recognized as the SAME employer regardless of which source supplied the string.

No network / no candidate data: a fictional registry + temp-dir skip logs.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
from common import JobPosting  # noqa: E402
from registry import Registry  # noqa: E402

TODAY = date(2026, 7, 22)


def _posting(company: str, title: str, url: str = "") -> JobPosting:
    return JobPosting(source="jobicy", company=company, title=title, url=url)


def _reg() -> Registry:
    # "Acme" is a polled registry entry; aggregators report it as "Acme Ltd.".
    return Registry([
        {"name": "Acme", "ats": "greenhouse", "token": "acme",
         "tags": ["ai-native"]},
    ])


class _LogFixture:
    """Write skip-log YAML into a temp dir and point profile_dir() at it."""

    def __init__(self, test: unittest.TestCase):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._orig = search_jobs.profile_dir
        search_jobs.profile_dir = lambda: self.dir  # type: ignore[assignment]
        test.addCleanup(self._restore)

    def _restore(self):
        search_jobs.profile_dir = self._orig  # type: ignore[assignment]
        self._tmp.cleanup()

    def write_search_log(self, name: str, day: date = TODAY):
        (self.dir / "company-search-log.yaml").write_text(
            "skip_within_days: 7\n"
            "companies:\n"
            f"  - name: {name!r}\n"
            f"    last_successful_search: '{day.isoformat()}'\n"
            "    outcome: created\n"
        )

    def write_applications_log(self, company: str, role: str):
        (self.dir / "applications-log.yaml").write_text(
            "postings:\n"
            f"  - company: {company!r}\n"
            f"    role: {role!r}\n"
            "    url: ''\n"
        )


class RecentlySearchedVariantTests(unittest.TestCase):
    def _fires(self, logged_name: str, incoming_company: str) -> bool:
        fx = _LogFixture(self)
        fx.write_search_log(logged_name)
        reg = _reg()
        skip_days, token_dates = search_jobs.load_company_search_log(
            profile=None, registry=reg)
        return search_jobs.is_recently_searched(
            _posting(incoming_company, "Backend Engineer"),
            token_dates, skip_days, TODAY, reg)

    def test_short_log_name_skips_longer_aggregator_variant(self):
        self.assertTrue(self._fires("Acme", "Acme Ltd."))

    def test_longer_log_name_skips_shorter_variant(self):  # symmetry
        self.assertTrue(self._fires("Acme Ltd.", "Acme"))

    def test_exact_name_still_skips(self):
        self.assertTrue(self._fires("Acme", "Acme"))

    def test_unrelated_company_is_not_skipped(self):
        self.assertFalse(self._fires("Acme", "Beacon Systems"))

    def test_aggregator_only_company_variant_skips(self):
        # Neither string is in the registry; comparable fallback still links them.
        self.assertTrue(self._fires("Globex", "Globex Technologies"))


class AlreadyConsideredVariantTests(unittest.TestCase):
    def _fires(self, logged_company: str, incoming_company: str,
               role: str = "Backend Engineer") -> bool:
        fx = _LogFixture(self)
        fx.write_applications_log(logged_company, "Backend Engineer")
        reg = _reg()
        urls, pairs = search_jobs.load_considered(reg)
        return search_jobs.already_considered(
            _posting(incoming_company, role), urls, pairs, reg)

    def test_short_log_name_skips_longer_aggregator_variant(self):
        self.assertTrue(self._fires("Acme", "Acme Ltd."))

    def test_longer_log_name_skips_shorter_variant(self):  # symmetry
        self.assertTrue(self._fires("Acme Ltd.", "Acme"))

    def test_aggregator_only_company_variant_skips(self):
        self.assertTrue(self._fires("Globex", "Globex Technologies"))

    def test_different_role_at_same_company_still_surfaces(self):
        # Only the exact (company, role) pair is suppressed; a new role surfaces.
        self.assertFalse(self._fires("Acme", "Acme Ltd.", role="ML Engineer"))

    def test_unrelated_company_is_not_considered(self):
        self.assertFalse(self._fires("Acme", "Beacon Systems"))


if __name__ == "__main__":
    unittest.main()
