import sys
import unittest
from pathlib import Path

import yaml

from _canonical_imports import pin_shared_modules

pin_shared_modules()

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from job_metadata import (  # noqa: E402
    APPLICATION_SCHEMA_VERSION,
    default_progress_for_status,
    validate_meta,
)
from metadata_editor import plan_v5_to_v6_migration  # noqa: E402


def _job(*, progress: dict | None = None) -> dict:
    return {
        "role": "Senior Engineer",
        "jd_file": "JD-senior-engineer.md",
        "status": "in_progress",
        "progress": progress or {
            "phase": "interview_loop",
            "state": "scheduled",
        },
        "workplace": "remote",
        "sponsorship": "unknown",
        "job_level": {
            "normalized": "senior",
            "min": 5.0,
            "max": 5.8,
            "confidence": "low",
            "source": "title",
        },
        "required_yoe": {
            "min": 5,
            "max": None,
            "confidence": "high",
            "source": "job_description",
        },
        "salary_range": None,
    }


def _meta(*, progress: dict | None = None) -> dict:
    return {
        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
        "company": "Acme",
        "jobs": [_job(progress=progress)],
    }


def _v5_bytes(*, calendar_line: bytes = b"") -> bytes:
    return (
        b"job_metadata_schema_version: 5  # keep version comment\n"
        b"company: 'Acme'\n"
        b"jobs:\n"
        b"  - role: Senior Engineer  # keep role comment\n"
        b"    jd_file: JD-senior-engineer.md\n"
        b"    status: in_progress\n"
        b"    progress:\n"
        b"      phase: interview_loop\n"
        b"      state: scheduled\n"
        + calendar_line
        + b"    workplace: remote\n"
        b"    sponsorship: unknown\n"
        b"    job_level: {normalized: senior, min: 5.0, max: 5.8, confidence: low, source: title}\n"
        b"    required_yoe: {min: 5, max: null, confidence: high, source: job_description}\n"
        b"    salary_range: null\n"
    )


class SchemaV6ValidationTests(unittest.TestCase):
    def test_current_schema_is_v6_and_accepts_ordered_unique_calendar_items(self):
        self.assertEqual(APPLICATION_SCHEMA_VERSION, 6)
        meta = _meta(progress={
            "phase": "interview_loop",
            "state": "scheduled",
            "calendar_items": ["cal-acme-day-one", "cal-acme-day-two"],
        })
        self.assertEqual(validate_meta(meta), [])

    def test_legacy_scalar_is_rejected_even_when_empty(self):
        meta = _meta(progress={
            "phase": "interview_loop",
            "state": "scheduled",
            "calendar_item": "cal-acme-day-one",
        })
        errors = validate_meta(meta)
        self.assertTrue(any("calendar_item is not allowed" in error for error in errors))

    def test_calendar_items_must_be_a_list_of_unique_valid_ids(self):
        not_a_list = _meta(progress={
            "phase": "interview_loop",
            "state": "scheduled",
            "calendar_items": "cal-acme-day-one",
        })
        self.assertTrue(any(
            "calendar_items must be a list" in error
            for error in validate_meta(not_a_list)
        ))

        duplicates = _meta(progress={
            "phase": "interview_loop",
            "state": "scheduled",
            "calendar_items": ["cal-acme-day-one", "cal-acme-day-one", "BAD"],
        })
        errors = validate_meta(duplicates)
        self.assertTrue(any("duplicates calendar entry id" in error for error in errors))
        self.assertTrue(any("calendar_items[2]" in error for error in errors))

    def test_default_status_transition_preserves_ordered_calendar_items(self):
        current = {
            "phase": "interview_loop",
            "state": "scheduled",
            "calendar_items": ["cal-acme-day-one", "cal-acme-day-two"],
        }
        result = default_progress_for_status("rejected", current=current)
        self.assertEqual(result["calendar_items"], current["calendar_items"])
        self.assertIsNot(result["calendar_items"], current["calendar_items"])


class SchemaV5ToV6MigrationTests(unittest.TestCase):
    def test_scalar_calendar_reference_becomes_one_element_ordered_list(self):
        raw = _v5_bytes(
            calendar_line=b"      calendar_item: cal-acme-day-one  # keep link comment\n"
        )
        plan = plan_v5_to_v6_migration(raw)
        self.assertEqual(plan.errors, ())
        self.assertTrue(plan.changed)
        self.assertIn(
            b"job_metadata_schema_version: 6  # keep version comment",
            plan.output_bytes,
        )
        self.assertIn(
            b"calendar_items: [cal-acme-day-one]  # keep link comment",
            plan.output_bytes,
        )
        self.assertIn(b"role: Senior Engineer  # keep role comment", plan.output_bytes)
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(
            result["jobs"][0]["progress"]["calendar_items"],
            ["cal-acme-day-one"],
        )
        self.assertNotIn("calendar_item", result["jobs"][0]["progress"])
        self.assertEqual(validate_meta(result), [])

    def test_absent_calendar_reference_only_bumps_version(self):
        raw = _v5_bytes()
        plan = plan_v5_to_v6_migration(raw)
        self.assertEqual(plan.errors, ())
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["job_metadata_schema_version"], 6)
        self.assertNotIn("calendar_items", result["jobs"][0]["progress"])
        self.assertEqual(
            plan.output_bytes.replace(b"schema_version: 6", b"schema_version: 5"),
            raw,
        )

    def test_explicit_empty_placeholder_becomes_empty_list_without_data_loss(self):
        raw = _v5_bytes(calendar_line=b"      calendar_item: ''\n")
        plan = plan_v5_to_v6_migration(raw)
        self.assertEqual(plan.errors, ())
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["jobs"][0]["progress"]["calendar_items"], [])

    def test_invalid_v5_input_and_already_v6_fail_closed(self):
        invalid = _v5_bytes(calendar_line=b"      calendar_item: NOT-A-CALENDAR-ID\n")
        invalid_plan = plan_v5_to_v6_migration(invalid)
        self.assertTrue(any("input validation failed" in e for e in invalid_plan.errors))
        self.assertFalse(invalid_plan.changed)
        self.assertEqual(invalid_plan.output_bytes, invalid)

        already_v6 = _v5_bytes().replace(
            b"job_metadata_schema_version: 5",
            b"job_metadata_schema_version: 6",
        )
        v6_plan = plan_v5_to_v6_migration(already_v6)
        self.assertTrue(any("already schema v6" in e for e in v6_plan.errors))
        self.assertEqual(v6_plan.output_bytes, already_v6)


if __name__ == "__main__":
    unittest.main()
