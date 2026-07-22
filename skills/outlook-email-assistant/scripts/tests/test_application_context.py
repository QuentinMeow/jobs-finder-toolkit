from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from application_context import find_application_matches


class ApplicationContextTests(unittest.TestCase):
    def test_company_and_recruiter_match_rank_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "5_applied" / "example-corp-platform-engineer-20260720"
            (app / "source").mkdir(parents=True)
            (app / "meta.yaml").write_text(
                f"""job_metadata_schema_version: 4
company: Example Corp
recruiter_email: {recruiter}
jobs:
  - role: Platform Engineer
    status: applied
    status_date: "2026-07-18"
    stage: ""
""",
                encoding="utf-8",
            )
            (app / "source/JD-platform-engineer.md").write_text("Example JD", encoding="utf-8")
            matches = find_application_matches(
                root,
                query="Example Corp platform interview",
                sender=recruiter,
            )
            self.assertEqual(matches[0].company, "Example Corp")
            self.assertGreaterEqual(matches[0].score, 100)
            self.assertIn(app.resolve() / "meta.yaml", matches[0].context_files)
            # The clean status label ("applied"), not the raw numbered folder name.
            self.assertEqual(matches[0].status, "applied")
            self.assertEqual(
                matches[0].jobs,
                ({"role": "Platform Engineer", "status": "applied", "stage": None},),
            )

    def test_generic_role_words_do_not_create_false_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "5_applied" / "unrelated-senior-engineer"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                "job_metadata_schema_version: 4\n"
                "company: Unrelated Inc\n"
                "jobs:\n"
                "  - role: Senior Software Engineer\n"
                "    status: applied\n",
                encoding="utf-8",
            )
            matches = find_application_matches(
                root,
                query="Example Corp senior software engineer",
                sender=recruiter,
            )
            self.assertEqual(matches, [])

    def test_mixed_status_jobs_report_per_job_status_and_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "4_in_progress" / "north-star-labs-multi-role-20260710"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                f"""job_metadata_schema_version: 4
company: North Star Labs
recruiter_email: {recruiter}
jobs:
  - role: Backend Engineer
    status: rejected
    status_date: "2026-07-12"
  - role: Platform Engineer
    status: in_progress
    status_date: "2026-07-15"
    stage: "onsite"
""",
                encoding="utf-8",
            )
            matches = find_application_matches(
                root,
                query="North Star Labs onsite interview",
                sender=recruiter,
            )
            self.assertEqual(len(matches), 1)
            # Overall folder status is the rollup label, independent of per-job status.
            self.assertEqual(matches[0].status, "in_progress")
            self.assertEqual(
                matches[0].jobs,
                (
                    {"role": "Backend Engineer", "status": "rejected", "stage": None},
                    {"role": "Platform Engineer", "status": "in_progress", "stage": "onsite"},
                ),
            )

    def test_legacy_meta_without_per_job_status_degrades_gracefully(self):
        # v2/v3 files predate per-job status/stage; matching must not crash and
        # should report null status/stage rather than fabricating a value, while
        # still falling back to the raw folder name for status when unmapped.
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "5_applied" / "legacy-corp-platform-engineer"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                f"""job_metadata_schema_version: 3
company: Legacy Corp
recruiter_email: {recruiter}
jobs:
  - role: Platform Engineer
""",
                encoding="utf-8",
            )
            matches = find_application_matches(
                root,
                query="Legacy Corp platform engineer",
                sender=recruiter,
            )
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].status, "applied")
            self.assertEqual(
                matches[0].jobs,
                ({"role": "Platform Engineer", "status": None, "stage": None},),
            )

    def test_unmapped_folder_name_falls_back_to_raw_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "not_a_status_folder" / "quirky-labs-role"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                f"""job_metadata_schema_version: 4
company: Quirky Labs
recruiter_email: {recruiter}
jobs:
  - role: Data Engineer
    status: drafted
""",
                encoding="utf-8",
            )
            matches = find_application_matches(
                root,
                query="Quirky Labs data engineer",
                sender=recruiter,
            )
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].status, "not_a_status_folder")
