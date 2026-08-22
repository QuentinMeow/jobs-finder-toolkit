"""Focused tests for the privacy-safe SKILL.md prompt-surface audit."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

METRICS_DIR = Path(__file__).resolve().parents[1]
if str(METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(METRICS_DIR))

import skill_prompt_audit as SPA  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class AuditTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class DiscoveryTests(AuditTestCase):
    def test_discovers_public_private_and_agents_then_deduplicates_symlinks(self) -> None:
        public = _write(self.root / "skills" / "public" / "SKILL.md", "# Public\n")
        _write(
            self.root / "private" / "skills" / "nested" / "private" / "SKILL.md",
            "# Private\n",
        )
        _write(self.root / ".agents" / "skills" / "adapter-only" / "SKILL.md", "# Adapter\n")
        link = self.root / ".agents" / "skills" / "public-link"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(public.parent, target_is_directory=True)
        file_link = self.root / "private" / "skills" / "public-file-link" / "SKILL.md"
        file_link.parent.mkdir(parents=True, exist_ok=True)
        file_link.symlink_to(public)

        found = SPA.discover_skill_files(self.root)

        self.assertEqual(
            [display for display, _real in found],
            [
                ".agents/skills/adapter-only/SKILL.md",
                "private/skills/nested/private/SKILL.md",
                "skills/public/SKILL.md",
            ],
        )
        self.assertEqual(len({os.stat(real).st_ino for _display, real in found}), 3)

    def test_explicit_public_root_replaces_default_but_keeps_optional_roots(self) -> None:
        _write(self.root / "skills" / "default" / "SKILL.md", "default\n")
        explicit = self.root / "custom-skills"
        _write(explicit / "custom" / "SKILL.md", "custom\n")
        _write(self.root / "private" / "skills" / "private" / "SKILL.md", "private\n")

        displays = [
            display
            for display, _real in SPA.discover_skill_files(self.root, [explicit])
        ]

        self.assertEqual(
            displays,
            ["custom-skills/custom/SKILL.md", "private/skills/private/SKILL.md"],
        )

    def test_absent_default_roots_produce_an_empty_report(self) -> None:
        report = SPA.build_audit(self.root)
        self.assertEqual(report["files"], [])
        self.assertEqual(report["summary"]["files"], 0)


class MeasurementTests(AuditTestCase):
    def test_measures_all_requested_dimensions(self) -> None:
        path = _write(
            self.root / "skills" / "x" / "SKILL.md",
            "---\n"
            "description: one two three four\n"
            "---\n"
            "# First\n"
            "MUST read `docs/one.md` and inspect every file.\n"
            "```text\n"
            "literal one\n"
            "literal two\n"
            "```\n"
            "## Second\n"
            "Use this unless the fast mode applies; otherwise use saved mode.\n",
        )

        row = SPA.measure_skill(path, "skills/x/SKILL.md")

        self.assertEqual(row["front_matter_description_words"], 4)
        self.assertEqual(row["longest_section_lines"], 6)
        self.assertGreaterEqual(row["strong_directive_count"], 1)
        self.assertEqual(row["literal_lines"], 2)
        self.assertEqual(row["longest_literal_block_lines"], 2)
        self.assertGreaterEqual(row["load_instruction_lines"], 1)
        self.assertGreaterEqual(row["bulk_load_count"], 1)
        self.assertGreaterEqual(row["referenced_path_count"], 1)
        self.assertEqual(row["opposing_mode_heuristic_count"], 1)


class ThresholdTests(unittest.TestCase):
    @staticmethod
    def metrics(**overrides) -> dict:
        base = {
            "direct_estimated_tokens": 0,
            "front_matter_description_words": 0,
            "longest_section_lines": 0,
            "strong_directive_count": 0,
            "strong_directives_per_1k_words": 0.0,
            "literal_lines": 0,
            "longest_literal_block_lines": 0,
            "load_instruction_lines": 0,
            "bulk_load_count": 0,
            "referenced_path_count": 0,
        }
        base.update(overrides)
        return base

    def test_direct_token_warning_tiers_and_exclusive_hard_limit(self) -> None:
        categories, failures = SPA._classify(
            self.metrics(direct_estimated_tokens=SPA.DIRECT_TOKEN_WARN[0])
        )
        self.assertIn("direct_prompt_elevated", categories)
        self.assertEqual(failures, [])

        categories, failures = SPA._classify(
            self.metrics(direct_estimated_tokens=SPA.DIRECT_TOKEN_WARN[1])
        )
        self.assertIn("direct_prompt_high", categories)
        self.assertNotIn("direct_prompt_elevated", categories)
        self.assertEqual(failures, [])

        _categories, at_limit = SPA._classify(
            self.metrics(direct_estimated_tokens=SPA.DIRECT_TOKEN_STRICT_GT)
        )
        _categories, over_limit = SPA._classify(
            self.metrics(direct_estimated_tokens=SPA.DIRECT_TOKEN_STRICT_GT + 1)
        )
        self.assertEqual(at_limit, [])
        self.assertEqual(over_limit, ["direct_prompt_hard_limit"])

    def test_only_three_dimensions_can_fail_strict(self) -> None:
        categories, failures = SPA._classify(self.metrics(
            front_matter_description_words=SPA.DESCRIPTION_WORDS_STRICT_GT + 1,
            longest_section_lines=SPA.SECTION_LINES_STRICT_GT + 1,
            strong_directive_count=10_000,
            strong_directives_per_1k_words=10_000,
            literal_lines=10_000,
            longest_literal_block_lines=10_000,
            load_instruction_lines=10_000,
            bulk_load_count=10_000,
            referenced_path_count=10_000,
        ))

        self.assertEqual(
            failures,
            ["description_hard_limit", "section_hard_limit"],
        )
        self.assertIn("directive_count", categories)
        self.assertIn("directive_density", categories)
        self.assertIn("bulk_loading", categories)

    def test_advisory_thresholds_are_inclusive(self) -> None:
        categories, failures = SPA._classify(self.metrics(
            front_matter_description_words=SPA.DESCRIPTION_WORDS_WARN,
            longest_section_lines=SPA.SECTION_LINES_WARN,
            strong_directive_count=SPA.DIRECTIVE_COUNT_WARN,
            strong_directives_per_1k_words=SPA.DIRECTIVE_DENSITY_WARN,
            literal_lines=SPA.LITERAL_LINES_WARN,
            longest_literal_block_lines=SPA.LITERAL_FENCE_LINES_WARN,
            load_instruction_lines=SPA.LOAD_LINES_WARN,
            bulk_load_count=SPA.BULK_LOADS_WARN,
            referenced_path_count=SPA.REFERENCE_PATHS_WARN,
        ))

        self.assertEqual(failures, [])
        self.assertEqual(len(categories), 9)


class PrivacyTests(AuditTestCase):
    def test_categories_are_fixed_sanitized_identifiers(self) -> None:
        secret = "Private-Customer/DoNotLeak"
        path = _write(
            self.root / "skills" / "safe-name" / "SKILL.md",
            (f"MUST read `{secret}` unless another mode applies.\n" * 50),
        )
        row = SPA.measure_skill(path, "skills/safe-name/SKILL.md")

        self.assertTrue(row["risk_categories"])
        for category in row["risk_categories"]:
            self.assertRegex(category, r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
            self.assertNotIn("private", category)

    def test_json_and_text_never_emit_matched_private_text(self) -> None:
        secret = "PRIVATE_MATCH_SENTINEL"
        _write(
            self.root / "skills" / "safe-name" / "SKILL.md",
            "---\n"
            f"description: {secret} {secret}\n"
            "---\n"
            + (f"MUST read `private/{secret}/profile.md` unless bulk-load applies.\n" * 50),
        )
        report = SPA.build_audit(self.root)
        outputs = (SPA.render_json(report), SPA.render_text(report, strict=True))

        for output in outputs:
            self.assertNotIn(secret, output)
            self.assertNotIn(f"private/{secret}", output)
        parsed = json.loads(outputs[0])
        self.assertEqual(parsed["files"][0]["path"], "skills/safe-name/SKILL.md")


if __name__ == "__main__":
    unittest.main()
