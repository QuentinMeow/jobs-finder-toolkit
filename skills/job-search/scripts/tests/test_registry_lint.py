"""The SHIPPED company registry lints clean — and the lint is not vacuous.

Run with (from the repo root):
    JOBHUNT_CONFIG=config.example.yaml .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests

``registry.lint_entries`` is pure, deterministic, offline and fatal-by-return, but
its only caller is ``validate_companies.py`` — a manual CLI wired into neither
pre-commit nor CI, so nothing ever ran it. Meanwhile ``Registry._build_index``
prints a warning and KEEPS THE FIRST ENTRY on a colliding identity key, which makes
a collision invisible in every non-interactive run. A collision changes
``match_keys``, which changes the pair set in ``search_jobs.load_considered``,
which changes WHICH POSTINGS GET SKIPPED — silently.

A unit test is strictly better here than a CI step: it runs in CI *and* in the
pre-commit test sweep, needs no workflow edit, and can carry the planted-defect
twin below that proves it can actually go red.

The registry is loaded from ``registry.REGISTRY_PATH`` EXPLICITLY, never through
``load_registry(None)`` — the default path merges the git-ignored overlay
blacklist, so this suite would otherwise read the owner's private tree and its
result would depend on whether an overlay is mounted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from registry import REGISTRY_PATH, lint_entries  # noqa: E402


def shipped_entries() -> list[dict]:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    return list(data.get("companies") or [])


class ShippedRegistryTests(unittest.TestCase):

    def test_shipped_registry_lints_clean(self):
        errors = lint_entries(shipped_entries())
        self.assertEqual(errors, [], "\n".join(errors))

    def test_the_registry_is_not_empty(self):
        """Guards the test above: an empty list lints clean for the wrong reason."""
        self.assertGreater(len(shipped_entries()), 100)

    def test_planted_collision_is_caught(self):
        """The lint is not vacuous — plant one and it goes red."""
        entries = shipped_entries()
        first = entries[0]
        clash = {
            "name": "Zzz Planted Collision Co",
            "ats": first.get("ats"),
            "token": "zzz-planted-collision",
            "tags": ["planted"],
            "aliases": [first["name"]],
        }
        if clash["ats"] == "workday":
            clash.update(host=first.get("host"), site=first.get("site"))
        errors = lint_entries([*entries, clash])
        self.assertTrue(any("collides" in e for e in errors), errors)

    def test_planted_schema_defect_is_caught(self):
        """The other half of the lint: a non-polled row needs a blacklist reason."""
        errors = lint_entries([*shipped_entries(),
                               {"name": "Zzz Planted Identity Only Co"}])
        self.assertTrue(any("blacklist reason" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
