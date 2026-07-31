"""`status.py --company-keys`: coverage is reported, correctness is enforced.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests

status.py reads its applications root from config at import time, so each case
runs it as a subprocess with JOBHUNT_CONFIG pointed at a throwaway config +
applications tree. JOBHUNT_COMPANY_INDEX points at a throwaway index (or at a
path that does not exist, for the no-overlay case) so no test depends on whether
a private overlay happens to be mounted on the machine running it.

Every company name here is invented.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / "status.py"

INDEX = textwrap.dedent("""\
    acme-labs:
      display: Acme Labs
      kind: employer
    beacon-works:
      display: Beacon Works
      kind: employer
    """)


class CompanyKeysReportTests(unittest.TestCase):
    def _run(self, apps: dict[str, str | None], *, index: str | None = INDEX,
             strict: bool = False):
        """Run --company-keys over a temp tree; return (rc, parsed_json)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafted = root / "apps" / "6_drafted"
            for slug, key in apps.items():
                app = drafted / slug
                app.mkdir(parents=True)
                body = "company: Acme Labs\n"
                if key is not None:
                    body += f"company_key: {key}\n"
                (app / "meta.yaml").write_text(body, encoding="utf-8")
            (root / "config.yaml").write_text(textwrap.dedent(f"""\
                paths:
                  applications_root: "{(root / 'apps').as_posix()}"
                """), encoding="utf-8")
            index_path = root / "_index.yaml"
            if index is not None:
                index_path.write_text(index, encoding="utf-8")
            env = dict(os.environ,
                       JOBHUNT_CONFIG=str(root / "config.yaml"),
                       JOBHUNT_COMPANY_INDEX=str(index_path))
            argv = [sys.executable, str(STATUS), "--company-keys", "--json"]
            if strict:
                argv.append("--strict")
            proc = subprocess.run(argv, capture_output=True, text=True, env=env)
            return proc.returncode, json.loads(proc.stdout)

    def test_counts_keyed_unkeyed_and_unresolved(self):
        rc, data = self._run({
            "acme-labs-swe-20260730": "acme-labs",
            "beacon-works-mle-20260730": "beacon-works",
            "unkeyed-swe-20260730": None,
            "unknown-key-swe-20260730": "not-in-the-index",
        })
        self.assertEqual(rc, 0, "coverage alone never fails without --strict")
        self.assertEqual(data["applications"], 4)
        self.assertEqual(data["keyed"], 3)
        self.assertEqual(data["distinct_keys"], 3)
        self.assertEqual(data["unkeyed"], ["unkeyed-swe-20260730"])
        self.assertEqual([r["company_key"] for r in data["unresolved"]],
                         ["not-in-the-index"])

    def test_an_unkeyed_application_never_fails_even_under_strict(self):
        """Coverage is fail-open BUT LOUD: a number, never a gate.

        An application is scaffolded unkeyed and keyed later; gating this would
        block unrelated work in the window between the two.
        """
        rc, data = self._run({"unkeyed-swe-20260730": None}, strict=True)
        self.assertEqual(rc, 0)
        self.assertEqual(data["unkeyed"], ["unkeyed-swe-20260730"])
        self.assertEqual(data["unresolved"], [])

    def test_an_unresolvable_key_fails_under_strict(self):
        rc, data = self._run({"ghost-swe-20260730": "not-in-the-index"},
                             strict=True)
        self.assertEqual(rc, 1)
        self.assertFalse(data["ok"])

    def test_an_unresolvable_key_does_not_fail_without_strict(self):
        rc, _ = self._run({"ghost-swe-20260730": "not-in-the-index"})
        self.assertEqual(rc, 0)

    def test_a_missing_index_is_reported_rather_than_crashing(self):
        """No overlay is the normal case in any checkout without one."""
        rc, data = self._run({"unkeyed-swe-20260730": None}, index=None)
        self.assertEqual(rc, 0)
        self.assertFalse(data["index_present"])
        self.assertEqual(data["index_keys"], 0)

    def test_a_missing_index_still_fails_strict_when_keys_exist(self):
        """"Cannot check" is not "checked and clean"."""
        rc, data = self._run({"acme-labs-swe-20260730": "acme-labs"},
                             index=None, strict=True)
        self.assertEqual(rc, 1)
        self.assertFalse(data["index_present"])
        self.assertEqual(len(data["unresolved"]), 1)

    def test_a_malformed_index_is_reported_rather_than_crashing(self):
        rc, data = self._run({"acme-labs-swe-20260730": "acme-labs"},
                             index="acme-labs: [unclosed\n")
        self.assertEqual(rc, 0)
        self.assertTrue(data["index_present"])
        self.assertTrue(data["index_error"])

    # ── unkeyed is not malformed ─────────────────────────────────────────────

    def test_a_malformed_company_key_is_not_counted_as_unkeyed(self):
        """The defect this class of test exists for.

        ``load_application`` copies a field only ``if meta_data.get(key)``, so
        ``""``, ``false`` and ``0`` were dropped on the way in and reported as
        UNKEYED — the same number as an application that simply has not been keyed
        yet — while ``validate_meta`` called each an ERROR and the reconciler called
        each a FINDING. ``"acme-labs\\n"`` was worse: ``.strip()`` made it look like
        a real key and it was counted keyed AND resolved.
        """
        for name, literal in (("trailing-newline", '"acme-labs\\n"'),
                              ("empty-string", '""'),
                              ("false", "false"),
                              ("zero", "0")):
            with self.subTest(shape=name):
                slug = f"broken-{name}-20260730"
                rc, data = self._run({slug: literal})
                self.assertEqual(data["unkeyed"], [],
                                 "a present-but-broken key is not an absent one")
                self.assertEqual([r["slug"] for r in data["malformed"]], [slug])
                self.assertEqual(data["keyed"], 0)
                self.assertEqual(rc, 0, "coverage alone never fails without --strict")

    def test_a_malformed_company_key_fails_under_strict(self):
        for name, literal in (("trailing-newline", '"acme-labs\\n"'),
                              ("empty-string", '""'),
                              ("false", "false"),
                              ("zero", "0")):
            with self.subTest(shape=name):
                rc, data = self._run({f"broken-{name}-20260730": literal},
                                     strict=True)
                self.assertEqual(rc, 1, data)
                self.assertFalse(data["ok"])

    def test_absent_is_the_one_class_that_stays_clean_everywhere(self):
        """The fifth row of the agreement table, and the only permissive one."""
        # Two shapes of absent: no `company_key:` line at all, and one with
        # nothing after the colon (which YAML parses as null).
        no_field, null_field = "unkeyed-swe-20260730", "explicit-null-swe-20260730"
        rc, data = self._run({no_field: None, null_field: ""}, strict=True)
        self.assertEqual(rc, 0)
        self.assertEqual(data["malformed"], [])
        self.assertEqual(sorted(data["unkeyed"]), sorted([no_field, null_field]))

    # ── the index itself ─────────────────────────────────────────────────────

    def test_an_empty_index_file_is_named_rather_than_counted_as_zero_keys(self):
        """0 keys is what a truncated file reports too."""
        rc, data = self._run({"acme-labs-swe-20260730": "acme-labs"}, index="")
        self.assertTrue(data["index_present"])
        self.assertTrue(data["index_empty"])
        self.assertEqual(data["index_keys"], 0)
        self.assertEqual(rc, 0)

    def test_a_directory_at_the_index_path_is_reported_not_treated_as_absent(self):
        """``is_file()`` is False for a directory, so this read as "no overlay"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "apps" / "6_drafted" / "acme-labs-swe-20260730"
            app.mkdir(parents=True)
            (app / "meta.yaml").write_text(
                "company: Acme Labs\ncompany_key: acme-labs\n", encoding="utf-8")
            (root / "config.yaml").write_text(textwrap.dedent(f"""\
                paths:
                  applications_root: "{(root / 'apps').as_posix()}"
                """), encoding="utf-8")
            index_path = root / "_index.yaml"
            index_path.mkdir()
            env = dict(os.environ,
                       JOBHUNT_CONFIG=str(root / "config.yaml"),
                       JOBHUNT_COMPANY_INDEX=str(index_path))
            proc = subprocess.run(
                [sys.executable, str(STATUS), "--company-keys", "--json"],
                capture_output=True, text=True, env=env)
            data = json.loads(proc.stdout)
            self.assertTrue(data["index_present"],
                            "a directory here is a broken overlay, not a missing one")
            self.assertIn("not a regular file", data["index_error"])


if __name__ == "__main__":
    unittest.main()
