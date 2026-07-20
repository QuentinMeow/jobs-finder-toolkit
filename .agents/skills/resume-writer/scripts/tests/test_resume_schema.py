"""Unit tests for the canonical multi-employer resume schema."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from resume_schema import ResumeSchemaError, normalize_resume  # noqa: E402


def _employer(company="Fictional Systems"):
    return {
        "company": company,
        "role": "Software Engineer",
        "dates": "2020 – Present",
        "location": "Remote (US)",
        "bullets": ["Built a reliable synthetic service for deterministic tests."],
        "projects": [],
    }


class ResumeSchemaTests(unittest.TestCase):
    def test_canonical_employers_preserve_direct_bullets(self):
        data = {"name": "Jordan Rivers", "employers": [_employer(), _employer("Example Labs")]}
        normalized = normalize_resume(data)
        self.assertEqual([e["company"] for e in normalized["employers"]],
                         ["Fictional Systems", "Example Labs"])
        self.assertEqual(normalized["employers"][0]["bullets"][0],
                         _employer()["bullets"][0])

    def test_singular_employer_is_backward_compatible(self):
        normalized = normalize_resume({"employer": _employer()})
        self.assertNotIn("employer", normalized)
        self.assertEqual(len(normalized["employers"]), 1)

    def test_experience_alias_keeps_flat_bullets_direct(self):
        normalized = normalize_resume({"experience": [_employer()]})
        employer = normalized["employers"][0]
        self.assertEqual(len(employer["bullets"]), 1)
        self.assertEqual(employer["projects"], [])

    def test_skills_mapping_normalizes_to_render_shape(self):
        normalized = normalize_resume({
            "skills": {"programming_languages": ["Python", "Go"]},
            "employers": [_employer()],
        })
        self.assertEqual(normalized["skills"], [
            {"label": "Programming Languages", "items": "Python, Go"},
        ])

    def test_conflicting_experience_representations_fail(self):
        with self.assertRaisesRegex(ResumeSchemaError, "exactly one experience"):
            normalize_resume({"employer": _employer(), "employers": [_employer()]})

    def test_wrong_root_and_collection_types_fail_cleanly(self):
        cases = [
            ([], "root must be a mapping"),
            ({"employers": {}}, "employers must be a list"),
            ({"employers": ["bad"]}, r"employers\[0\] must be a mapping"),
            ({"employers": [_employer()], "skills": "Python"}, "skills must be a list"),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                with self.assertRaisesRegex(ResumeSchemaError, message):
                    normalize_resume(data)

    def test_input_is_not_mutated(self):
        data = {"employer": _employer()}
        normalize_resume(data)
        self.assertIn("employer", data)
        self.assertNotIn("employers", data)


if __name__ == "__main__":
    unittest.main()
