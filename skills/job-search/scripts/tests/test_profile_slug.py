"""Tests for the discoveries-filename slug derived from --profile.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from search_jobs import profile_slug  # noqa: E402


class ProfileSlugTests(unittest.TestCase):
    def test_bare_label_unchanged(self):
        self.assertEqual(profile_slug("example"), "example")

    def test_path_style_arg_reduces_to_stem(self):
        # A filesystem path must never leak its separators into the filename.
        self.assertEqual(profile_slug("/abs/path/to/example.yaml"), "example")
        self.assertEqual(profile_slug("profiles/example.yaml"), "example")
        self.assertEqual(profile_slug("./example.yml"), "example")

    def test_no_path_separators_survive(self):
        slug = profile_slug("/abs/path/to/profile.yaml")
        self.assertNotIn("/", slug)

    def test_unsafe_characters_are_sanitized(self):
        self.assertEqual(profile_slug("weird name!.yaml"), "weird-name")

    def test_empty_or_dotfile_falls_back(self):
        self.assertEqual(profile_slug(""), "profile")
        self.assertEqual(profile_slug("/"), "profile")


if __name__ == "__main__":
    unittest.main()
