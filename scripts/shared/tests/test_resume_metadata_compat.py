from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CHECK_PATH = ROOT / ".agents/skills/resume-writer/scripts/check.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "resume_writer_check_under_test", CHECK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResumeMetadataValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.check = _load_check_module()

    def test_non_v4_metadata_fails_the_render_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary)
            (app_dir / "meta.yaml").write_text(
                'company: "Example Corp"\nrole: "Software Engineer"\n'
            )
            checker = self.check.Checker()
            self.check.check_application_metadata(checker, app_dir)

        self.assertTrue(any(
            "job_metadata_schema_version must be 4" in failure
            for failure in checker.failures))

    def test_legacy_v3_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary)
            (app_dir / "meta.yaml").write_text(
                "job_metadata_schema_version: 3\n"
                'company: "Example Corp"\n'
                "jobs:\n"
                '  - role: "Software Engineer"\n'
                "    jd_file: JD-software-engineer.md\n"
                "    status: drafted\n"
            )
            checker = self.check.Checker()
            self.check.check_application_metadata(checker, app_dir)

        self.assertTrue(any(
            "job_metadata_schema_version must be 4" in failure
            for failure in checker.failures))

    def test_v4_metadata_is_validated_strictly(self):
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary)
            (app_dir / "meta.yaml").write_text(
                "job_metadata_schema_version: 4\n"
                'company: "Example Corp"\n'
                "jobs:\n"
                '  - role: "Software Engineer"\n'
                "    jd_file: JD-software-engineer.md\n"
                "    status: drafted\n"
            )
            checker = self.check.Checker()
            self.check.check_application_metadata(checker, app_dir)

        self.assertTrue(checker.failures)
        self.assertTrue(any("job_level" in failure for failure in checker.failures))


if __name__ == "__main__":
    unittest.main()
