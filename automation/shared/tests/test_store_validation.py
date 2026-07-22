"""JSON Schema validator, zone-aware store validation, and the fixture-size check."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
REPO_ROOT = SHARED.parent.parent
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(REPO_ROOT / "automation" / "store"))

from store import blobs as _blobs  # noqa: E402
from store import serialization, validation  # noqa: E402
from store.blobs import BlobStore  # noqa: E402
from store.constants import FIXTURE_SIZE_OVERRIDE_FILENAME  # noqa: E402
from store.manifest import build_envelope, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402

FIXTURE = REPO_ROOT / "examples" / "data"


class MinimalValidatorTests(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["a", "b"],
        "properties": {
            "a": {"type": "integer", "minimum": 0},
            "b": {"type": "string", "enum": ["x", "y"]},
            "c": {"anyOf": [{"type": "null"}, {"type": "object",
                                               "required": ["k"]}]},
        },
        "additionalProperties": False,
    }

    def test_valid_instance(self):
        self.assertEqual(validation.validate({"a": 1, "b": "x"}, self.SCHEMA), [])

    def test_missing_required(self):
        errs = validation.validate({"a": 1}, self.SCHEMA)
        self.assertTrue(any("missing required property 'b'" in e for e in errs))

    def test_wrong_type(self):
        errs = validation.validate({"a": "nope", "b": "x"}, self.SCHEMA)
        self.assertTrue(any("expected type" in e for e in errs))

    def test_enum_and_additional(self):
        errs = validation.validate({"a": 1, "b": "z", "extra": 1}, self.SCHEMA)
        self.assertTrue(any("enum" in e for e in errs))
        self.assertTrue(any("additional property" in e for e in errs))

    def test_anyof_null_or_object(self):
        self.assertEqual(validation.validate({"a": 1, "b": "x", "c": None},
                                             self.SCHEMA), [])
        self.assertEqual(validation.validate({"a": 1, "b": "x", "c": {"k": 1}},
                                             self.SCHEMA), [])
        errs = validation.validate({"a": 1, "b": "x", "c": {"nope": 1}}, self.SCHEMA)
        self.assertTrue(any("anyOf" in e for e in errs))


class FixtureValidationTests(unittest.TestCase):
    def test_committed_fixture_is_valid(self):
        self.assertTrue(FIXTURE.is_dir(), "run generate_fixture_store.py first")
        report = validation.validate_store(FIXTURE)
        self.assertTrue(report.ok, report.errors)

    def test_fixture_reports_not_synced_here_as_info(self):
        report = validation.validate_store(FIXTURE)
        # The fixture deliberately includes one not-synced-here blob — informational.
        self.assertGreaterEqual(report.blob_states.get(_blobs.NOT_SYNCED_HERE, 0), 1)
        self.assertTrue(report.ok)  # not-synced-here never fails validation


class CorruptBlobFailsTests(unittest.TestCase):
    def test_corrupt_blob_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = domain_layout(root, "jobs")
            blobs = BlobStore(layout.blobs)
            dt = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)
            ref = blobs.write(b'{"real": 1}', "application/json")
            env = build_envelope(
                fetch_id="20260721T093000Z-000001-aaaaaa", source="greenhouse",
                operation="board", request={"url": "u"}, status=200,
                fetched_at=serialization.to_z(dt),
                payload=ref.as_payload("application/json"),
                context={"company": "examplecorp"})
            write_manifest(layout.manifest_path("greenhouse", dt, env["fetch_id"]),
                           env)
            # Corrupt the stored blob (valid zstd of different bytes).
            import zstandard
            blobs.path_for(ref.sha256, "json").write_bytes(
                zstandard.ZstdCompressor().compress(b'{"tampered": 1}'))

            report = validation.validate_store(root)
            self.assertFalse(report.ok)
            self.assertEqual(report.blob_states.get(_blobs.CORRUPT), 1)


class FixtureSizeTests(unittest.TestCase):
    def test_over_default_threshold_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "big.bin").write_bytes(b"x" * (
                validation.FIXTURE_SIZE_SOFT_LIMIT_BYTES + 5000))
            check = validation.check_fixture_size(root)
            self.assertTrue(check.over)

    def test_override_file_raises_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "big.bin").write_bytes(b"x" * (
                validation.FIXTURE_SIZE_SOFT_LIMIT_BYTES + 5000))
            (root / FIXTURE_SIZE_OVERRIDE_FILENAME).write_text("100000")  # 100 MB
            check = validation.check_fixture_size(root)
            self.assertFalse(check.over)
            self.assertIn("override", check.limit_source)

    def test_cli_warns_but_does_not_fail_when_over(self):
        import validate_store as cli  # automation/store/validate_store.py
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / FIXTURE_SIZE_OVERRIDE_FILENAME).write_text("0")  # force over
            (root / "note.txt").write_text("content")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main([str(root), "--check-fixture-size"])
            self.assertEqual(rc, 0)  # soft threshold: WARN, never fail
            self.assertIn("WARNING", err.getvalue())


if __name__ == "__main__":
    unittest.main()
