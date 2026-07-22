"""Small deterministic invariants for non-semantic hard filters."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
for path in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common import JobPosting  # noqa: E402
from scoring import ai_company_ok, date_ok  # noqa: E402


def _posting(description=""):
    return JobPosting(
        source="test",
        company="Example Corp",
        title="Platform Engineer",
        url="https://example.test/jobs/1",
        description=description,
    )


class RecencyInvariants(unittest.TestCase):
    def test_unknown_date_fails_open(self):
        posting = _posting()
        posting.age_days = None
        self.assertTrue(date_ok(posting, 2))

    def test_known_boundary_is_inclusive(self):
        posting = _posting()
        posting.age_days = 2
        self.assertTrue(date_ok(posting, 2))
        posting.age_days = 2.01
        self.assertFalse(date_ok(posting, 2))


class AiNativeProvenanceInvariants(unittest.TestCase):
    def test_registry_tag_can_satisfy_explicit_hard_gate(self):
        profile = {"ai_company": {"require": True, "signals": ["frontier model"]}}
        self.assertTrue(ai_company_ok(
            _posting("Build storage systems."), profile,
            is_ai_native_company=True))

    def test_jd_signal_can_satisfy_explicit_hard_gate(self):
        profile = {"ai_company": {"require": True, "signals": ["frontier model"]}}
        self.assertTrue(ai_company_ok(
            _posting("Build infrastructure for a frontier model."), profile,
            is_ai_native_company=False))

    def test_missing_registry_and_jd_provenance_fails_closed(self):
        profile = {"ai_company": {"require": True, "signals": ["frontier model"]}}
        self.assertFalse(ai_company_ok(
            _posting("Build storage systems."), profile,
            is_ai_native_company=False))

    def test_default_soft_mode_never_hard_filters(self):
        profile = {"ai_company": {"require": False, "signals": ["frontier model"]}}
        self.assertTrue(ai_company_ok(
            _posting("Build storage systems."), profile,
            is_ai_native_company=False))


if __name__ == "__main__":
    unittest.main()
