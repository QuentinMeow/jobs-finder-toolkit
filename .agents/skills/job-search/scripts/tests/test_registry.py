"""Offline tests for registry linting and opt-in polling batches."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from registry import Registry, lint_entries  # noqa: E402


def _entry(name: str, token: str, **extra) -> dict:
    return {
        "name": name,
        "ats": "greenhouse",
        "token": token,
        "tags": ["ai-native"],
        **extra,
    }


class RegistryLintTests(unittest.TestCase):
    def test_valid_polled_and_blacklist_rows(self):
        entries = [
            _entry("Acme AI", "acme", aliases=["Acme Labs"]),
            {"name": "No Sponsor Corp", "aliases": ["NSC"],
             "blacklist": "Company-wide no-sponsorship policy."},
        ]
        self.assertEqual(lint_entries(entries), [])

    def test_identity_collisions_are_fatal(self):
        errors = lint_entries([
            _entry("Acme AI", "acme", aliases=["Shared Name"]),
            _entry("Beacon AI", "beacon", aliases=["shared name"]),
        ])
        self.assertTrue(any("collides" in error for error in errors), errors)

    def test_workday_requires_host_and_site(self):
        row = _entry("Acme AI", "acme", ats="workday")
        errors = lint_entries([row])
        self.assertTrue(any("host is required" in error for error in errors), errors)
        self.assertTrue(any("site is required" in error for error in errors), errors)

    def test_invalid_batch_is_rejected(self):
        errors = lint_entries([
            _entry("Acme AI", "acme", poll_batch="AI Expansion 01")
        ])
        self.assertTrue(any("poll_batch" in error for error in errors), errors)


class PollBatchTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            _entry("Legacy AI", "legacy"),
            _entry("Expansion One", "one", poll_batch="ai-expansion-01"),
            _entry("Expansion Two", "two", poll_batch="ai-expansion-02",
                   tags=["data-platform"]),
        ]
        self.registry = Registry(self.entries)

    def test_default_poll_excludes_batched_rows(self):
        self.assertEqual(
            [row["name"] for row in self.registry.poll_companies()],
            ["Legacy AI"],
        )

    def test_explicit_batch_selects_only_that_batch(self):
        self.assertEqual(
            [row["name"] for row in self.registry.poll_companies(
                batches=["ai-expansion-01"])],
            ["Expansion One"],
        )

    def test_tags_and_batches_are_both_required(self):
        selected = self.registry.poll_companies(
            tags=["data-platform"], batches=["ai-expansion-02"])
        self.assertEqual([row["name"] for row in selected], ["Expansion Two"])
        self.assertEqual(
            self.registry.poll_companies(
                tags=["ai-native"], batches=["ai-expansion-02"]),
            [],
        )


class BlacklistIdentityTests(unittest.TestCase):
    def test_blacklist_applies_to_aliases(self):
        registry = Registry([
            {"name": "Example Holdings", "aliases": ["Example Labs"],
             "blacklist": "Explicit policy mismatch."},
        ])
        blocked, reason = registry.is_blacklisted("example labs")
        self.assertTrue(blocked)
        self.assertIn("policy mismatch", reason.lower())


if __name__ == "__main__":
    unittest.main()
