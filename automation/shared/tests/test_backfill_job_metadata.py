import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKER_SCRIPTS = (
    REPO_ROOT / "skills" / "application-tracker" / "scripts"
)
if str(TRACKER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(TRACKER_SCRIPTS))

import backfill_job_metadata  # noqa: E402


class BackfillJobMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = Path(self.temporary.name) / "acme-multi-20260719"
        (self.app / "source").mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_meta(self, data):
        path = self.app / "meta.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        return path

    @staticmethod
    def _job(role: str, jd_file: str | None) -> dict:
        job = {
            "role": role,
            "status": "drafted",
            "progress": {"phase": "application_prep", "state": "action_required"},
        }
        if jd_file:
            job["jd_file"] = jd_file
        return job

    def test_multi_role_uses_exact_jd_file_not_index_order(self):
        (self.app / "source" / "JD-alpha.md").write_text(
            "Requires at least 2 years of professional experience.")
        (self.app / "source" / "JD-zulu.md").write_text(
            "Requires at least 7 years of professional experience.")
        self._write_meta({
            "company": "Acme",
            "jobs": [
                self._job("Zulu", "JD-zulu.md"),
                self._job("Alpha", "JD-alpha.md"),
            ],
        })
        with patch.object(
            backfill_job_metadata.config,
            "company_levels_path",
            return_value=self.app / "missing-company-levels.yaml",
        ):
            _path, plan = backfill_job_metadata.plan_application(self.app)
        self.assertFalse(plan.errors)
        result = yaml.safe_load(plan.output_bytes)
        self.assertEqual(result["jobs"][0]["required_yoe"]["min"], 7)
        self.assertEqual(result["jobs"][1]["required_yoe"]["min"], 2)

    def test_multi_role_missing_jd_file_never_falls_back(self):
        (self.app / "source" / "JD-only.md").write_text(
            "Requires at least 9 years of professional experience.")
        meta_path = self._write_meta({
            "company": "Acme",
            "jobs": [self._job("No Association", None)],
        })
        before = meta_path.read_bytes()
        result = backfill_job_metadata.process_application(self.app, write=False)
        self.assertIn("no jd_file", result["error"])
        self.assertEqual(meta_path.read_bytes(), before)

    def test_dry_run_preserves_file_and_second_plan_is_idempotent(self):
        (self.app / "source" / "JD-engineer.md").write_text(
            "Requires at least 4 years of professional experience.")
        meta_path = self._write_meta({
            "company": "Acme",
            "jobs": [self._job("Software Engineer", "JD-engineer.md")],
        })
        before = meta_path.read_bytes()
        with patch.object(
            backfill_job_metadata.config,
            "company_levels_path",
            return_value=self.app / "missing-company-levels.yaml",
        ):
            first_path, first = backfill_job_metadata.plan_application(self.app)
            second = backfill_job_metadata.plan_metadata_edit(
                first.output_bytes,
                backfill_job_metadata.generated_metadata_by_path(
                    self.app, yaml.safe_load(first.output_bytes)),
            )
        self.assertEqual(first_path, meta_path)
        self.assertFalse(first.errors)
        self.assertTrue(first.changed)
        self.assertFalse(second.errors)
        self.assertFalse(second.changed)
        self.assertEqual(meta_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
