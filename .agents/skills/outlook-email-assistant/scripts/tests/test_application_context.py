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
                f"""job_metadata_schema_version: 3
company: Example Corp
recruiter_email: {recruiter}
jobs:
  - role: Platform Engineer
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

    def test_generic_role_words_do_not_create_false_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            recruiter = "recruiter" + chr(64) + "example.invalid"
            root = Path(tmp)
            app = root / "5_applied" / "unrelated-senior-engineer"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                "company: Unrelated Inc\njobs:\n  - role: Senior Software Engineer\n",
                encoding="utf-8",
            )
            matches = find_application_matches(
                root,
                query="Example Corp senior software engineer",
                sender=recruiter,
            )
            self.assertEqual(matches, [])
