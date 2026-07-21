import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from metadata_editor import (  # noqa: E402
    MetadataChecksumMismatchError,
    atomic_write_bytes,
    plan_field_updates,
    plan_metadata_edit,
)


def _metadata(*, with_salary: bool = False) -> dict:
    """A schema-v4 flat metadata fragment for one jobs entry."""
    return {
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
        "salary_range": {
            "min": 150000,
            "max": 200000,
            "confidence": "high",
            "source": "job_description",
        } if with_salary else None,
    }


class MetadataEditorTests(unittest.TestCase):
    def test_preserves_comments_quotes_and_placeholder_comment(self):
        raw = (
            b"# application metadata\n"
            b'company: "Acme Corp"\n'
            b"jobs:\n"
            b"  - role: 'Senior Engineer' # exact title\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    status: drafted\n"
            b"    job_level: {} # generated placeholder\n"
            b"notes:\n"
            b'  - "Keep: quoted note"\n'
        )

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata()})

        self.assertFalse(plan.errors)
        self.assertTrue(plan.changed)
        self.assertIn(b"# application metadata", plan.output_bytes)
        self.assertIn(b'company: "Acme Corp"', plan.output_bytes)
        self.assertIn(b"role: 'Senior Engineer' # exact title", plan.output_bytes)
        self.assertIn(b"# generated placeholder", plan.output_bytes)
        self.assertIn(b'  - "Keep: quoted note"', plan.output_bytes)
        self.assertIn(("jobs", 0, "job_level"), plan.changed_field_paths)
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["job_metadata_schema_version"], 4)
        self.assertEqual(result["jobs"][0]["job_level"]["normalized"], "senior")

    def test_multi_role_metadata_is_anchored_to_exact_records(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Backend Engineer\n"
            b"    jd_file: JD-backend.md\n"
            b"    status: drafted\n"
            b"  - role: Platform Engineer\n"
            b"    jd_file: JD-platform.md\n"
            b"    status: drafted"
        )
        backend = _metadata()
        backend["job_level"] = {**backend["job_level"], "normalized": "mid"}
        generated = {
            ("jobs", 0): backend,
            ("jobs", 1): _metadata(),
        }

        plan = plan_metadata_edit(raw, generated)

        self.assertFalse(plan.errors)
        result = yaml.safe_load(plan.output_bytes)
        self.assertNotIn("job_level", result)
        self.assertEqual(result["jobs"][0]["job_level"]["normalized"], "mid")
        self.assertEqual(result["jobs"][1]["job_level"]["normalized"], "senior")
        self.assertIn(("jobs", 0, "job_level"), plan.changed_field_paths)
        self.assertIn(("jobs", 1, "job_level"), plan.changed_field_paths)

    def test_missing_jobs_list_is_rejected(self):
        raw = b"company: Acme\nrole: Senior Engineer\n"

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata()})

        self.assertTrue(plan.errors)
        self.assertTrue(any("jobs list" in error for error in plan.errors))
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)

    def test_missing_exact_record_path_returns_error_without_output(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Backend Engineer\n"
            b"    jd_file: JD-backend.md\n"
        )

        plan = plan_metadata_edit(raw, {("jobs", 1): _metadata()})

        self.assertTrue(plan.errors)
        self.assertTrue(
            any("missing exact record path jobs[0]" in error for error in plan.errors)
        )
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)

    def test_null_placeholder_is_enriched_when_jd_has_salary(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Senior Engineer\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    status: drafted\n"
            b"    salary_range: null\n"
        )

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata(with_salary=True)})

        self.assertFalse(plan.errors)
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["jobs"][0]["salary_range"]["min"], 150000)
        self.assertIn(("jobs", 0, "salary_range"), plan.changed_field_paths)

    def test_null_fact_is_preserved_when_generated_fact_is_also_null(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Senior Engineer\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    status: drafted\n"
            b"    salary_range: null\n"
        )

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata(with_salary=False)})

        self.assertFalse(plan.errors)
        result = yaml.safe_load(plan.output_bytes)
        self.assertIsNone(result["jobs"][0]["salary_range"])
        self.assertNotIn(("jobs", 0, "salary_range"), plan.changed_field_paths)

    def test_populated_partial_field_requires_manual_migration(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Senior Engineer\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    required_yoe:\n"
            b"      min: 5\n"
        )

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata()})

        self.assertTrue(
            any(
                "required_yoe" in error and "manual migration" in error
                for error in plan.errors
            )
        )
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)

    def test_preexisting_notes_list_semantics_are_unchanged(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Senior Engineer\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    status: drafted\n"
            b"notes:\n"
            b"  - follow up with recruiter\n"
            b"  - owner: candidate\n"
            b"    tags: [urgent, remote]\n"
        )
        before_notes = yaml.safe_load(raw)["notes"]

        plan = plan_metadata_edit(raw, {("jobs", 0): _metadata()})

        self.assertFalse(plan.errors)
        self.assertEqual(yaml.safe_load(plan.output_bytes)["notes"], before_notes)

    def test_atomic_write_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "meta.yaml"
            path.write_bytes(b"company: Acme\n")

            with self.assertRaises(MetadataChecksumMismatchError):
                atomic_write_bytes(
                    path,
                    b"company: Changed\n",
                    expected_sha256="0" * 64,
                )

            self.assertEqual(path.read_bytes(), b"company: Acme\n")

    def test_atomic_write_accepts_matching_checksum(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "meta.yaml"
            original = b"company: Acme\n"
            replacement = b"company: Acme Corp\n"
            path.write_bytes(original)

            atomic_write_bytes(
                path,
                replacement,
                expected_sha256=hashlib.sha256(original).hexdigest(),
            )

            self.assertEqual(path.read_bytes(), replacement)

    def test_atomic_write_rechecks_checksum_before_replace(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "meta.yaml"
            original = b"company: Acme\n"
            concurrent = b"company: Concurrent Edit\n"
            path.write_bytes(original)
            real_fsync = os.fsync
            changed = False

            def fsync_then_edit(descriptor):
                nonlocal changed
                real_fsync(descriptor)
                if not changed:
                    changed = True
                    path.write_bytes(concurrent)

            with patch("metadata_editor.os.fsync", side_effect=fsync_then_edit):
                with self.assertRaises(MetadataChecksumMismatchError):
                    atomic_write_bytes(
                        path,
                        b"company: Planned Edit\n",
                        expected_sha256=hashlib.sha256(original).hexdigest(),
                    )

            self.assertEqual(path.read_bytes(), concurrent)

    def test_second_run_is_idempotent(self):
        raw = (
            b"company: Acme\n"
            b"jobs:\n"
            b"  - role: Senior Engineer\n"
            b"    jd_file: JD-senior-engineer.md\n"
            b"    status: drafted\n"
        )
        generated = {("jobs", 0): _metadata()}

        first = plan_metadata_edit(raw, generated)
        second = plan_metadata_edit(first.output_bytes, generated)

        self.assertFalse(first.errors)
        self.assertFalse(second.errors)
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(second.changed_field_paths, ())
        self.assertEqual(second.output_bytes, first.output_bytes)


def _valid_v4_meta_bytes() -> bytes:
    """A fully valid schema-v4 meta.yaml (single posting) for set-field tests."""
    return (
        b"job_metadata_schema_version: 4\n"
        b"company: Acme\n"
        b"jobs:\n"
        b"  - role: Senior Engineer  # exact title\n"
        b"    jd_file: JD-senior-engineer.md\n"
        b"    status: drafted  # created by handoff\n"
        b"    workplace: remote\n"
        b"    sponsorship: unknown\n"
        b"    job_level: {normalized: senior, min: 5.0, max: 5.8, confidence: low, source: title}\n"
        b"    required_yoe: {min: 5, max: null, confidence: high, source: job_description}\n"
        b"    salary_range: null\n"
    )


class FieldUpdateEditorTests(unittest.TestCase):
    def test_overwrite_existing_status_preserves_comment_and_format(self):
        raw = _valid_v4_meta_bytes()
        plan = plan_field_updates(
            raw, {("jobs", 0): {"status": "applied", "status_date": "2026-07-20"}})
        self.assertFalse(plan.errors)
        self.assertTrue(plan.changed)
        # The overwrite keeps the trailing inline comment byte-for-byte.
        self.assertIn(b"status: applied  # created by handoff", plan.output_bytes)
        # The absent status_date is inserted.
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["jobs"][0]["status"], "applied")
        self.assertEqual(result["jobs"][0]["status_date"], "2026-07-20")
        # Untouched fields keep their exact formatting (flow-style mappings, comment).
        self.assertIn(b"role: Senior Engineer  # exact title", plan.output_bytes)
        self.assertIn(b"required_yoe: {min: 5, max: null,", plan.output_bytes)
        self.assertIn(
            ("jobs", 0, "status"), plan.changed_field_paths)
        self.assertIn(
            ("jobs", 0, "status_date"), plan.changed_field_paths)

    def test_stage_only_edit_leaves_status_untouched(self):
        raw = _valid_v4_meta_bytes()
        plan = plan_field_updates(raw, {("jobs", 0): {"stage": "onsite"}})
        self.assertFalse(plan.errors)
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["jobs"][0]["stage"], "onsite")
        self.assertEqual(result["jobs"][0]["status"], "drafted")

    def test_unknown_record_path_fails_closed(self):
        raw = _valid_v4_meta_bytes()
        plan = plan_field_updates(raw, {("jobs", 3): {"status": "applied"}})
        self.assertTrue(plan.errors)
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)

    def test_invalid_status_value_is_rejected_by_the_gate(self):
        raw = _valid_v4_meta_bytes()
        plan = plan_field_updates(raw, {("jobs", 0): {"status": "offer"}})
        self.assertTrue(plan.errors)
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)

    def test_setting_status_to_current_value_is_a_no_op(self):
        raw = _valid_v4_meta_bytes()
        plan = plan_field_updates(raw, {("jobs", 0): {"status": "drafted"}})
        self.assertFalse(plan.errors)
        self.assertFalse(plan.changed)
        self.assertEqual(plan.output_bytes, raw)


if __name__ == "__main__":
    unittest.main()
