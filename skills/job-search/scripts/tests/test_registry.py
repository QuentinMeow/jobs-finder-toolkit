"""Offline tests for registry linting and opt-in polling batches."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from registry import Registry, comparable_base, lint_entries  # noqa: E402


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

    def test_blacklist_applies_across_legal_suffix_variant(self):
        registry = Registry([
            {"name": "Acme", "aliases": [],
             "blacklist": "No sponsorship."},
        ])
        # Aggregator variant with a trailing legal suffix still resolves.
        self.assertTrue(registry.is_blacklisted("Acme Ltd.")[0])
        self.assertTrue(registry.is_blacklisted("Acme, Inc.")[0])


class ComparableBaseTests(unittest.TestCase):
    def test_strips_trailing_legal_suffixes_and_punctuation(self):
        self.assertEqual(comparable_base("Acme"), "acme")
        self.assertEqual(comparable_base("Acme Ltd."), "acme")
        self.assertEqual(comparable_base("Acme Corp, Inc."), "acme")
        self.assertEqual(comparable_base("Acme Technologies"), "acme")

    def test_trailing_possessive_is_stripped(self):
        self.assertEqual(comparable_base("McDonald's Co"), "mcdonald")
        self.assertEqual(comparable_base("Acme's"), "acme")

    def test_suffix_word_that_is_not_trailing_is_left_intact(self):
        # "inc"/"technology" are only stripped from the trailing edge — a
        # suffix-like word elsewhere in the name is a real word, not a suffix.
        self.assertEqual(comparable_base("Inc Magazine"), "inc magazine")
        self.assertEqual(comparable_base("Technology Credit Union"),
                         "technology credit union")
        # Embedded look-alikes are whole-token safe.
        self.assertEqual(comparable_base("Coinbase"), "coinbase")
        self.assertEqual(comparable_base("Incubator Labs"), "incubator labs")

    def test_short_legal_name_is_not_emptied(self):
        # A name that is ONLY a suffix word keeps itself (never reduced to "").
        self.assertEqual(comparable_base("Co"), "co")
        self.assertEqual(comparable_base("LLC"), "llc")


class MatchKeyVariantTests(unittest.TestCase):
    def _registry(self):
        return Registry([_entry("Acme", "acme")])

    def test_match_keys_intersect_across_suffix_variant(self):
        reg = self._registry()
        # Short registry name vs longer aggregator variant, both directions.
        self.assertTrue(reg.match_keys("Acme") & reg.match_keys("Acme Ltd."))
        self.assertTrue(reg.match_keys("Acme Corp, Inc.") & reg.match_keys("Acme"))

    def test_aggregator_only_variants_still_intersect(self):
        reg = self._registry()
        # Neither string is in the registry; comparable fallback still links them.
        self.assertTrue(reg.match_keys("Foo") & reg.match_keys("Foo Technologies"))

    def test_distinct_companies_do_not_conflate(self):
        reg = self._registry()
        self.assertFalse(reg.match_keys("Acme") & reg.match_keys("Beacon Labs"))

    def test_ambiguous_base_is_not_conflated(self):
        # Two DISTINCT registered companies whose stripped base collides must not
        # be merged: the shared base is ambiguous, so no comparable key is emitted
        # and canonical() abstains.
        reg = Registry([_entry("Acme Inc", "acmeinc"),
                        _entry("Acme LLC", "acmellc")])
        self.assertIsNone(reg.canonical("Acme"))
        self.assertFalse(reg.match_keys("Acme Inc") & reg.match_keys("Acme LLC"))

    def test_canonical_resolves_unambiguous_variant(self):
        reg = self._registry()
        self.assertEqual(reg.canonical("Acme Ltd."), "Acme")
        self.assertEqual(reg.canonical("acme, inc."), "Acme")


if __name__ == "__main__":
    unittest.main()
