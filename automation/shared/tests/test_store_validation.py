"""JSON Schema validator, zone-aware store validation, and the fixture-size check."""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

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


class FixtureFreshnessTests(unittest.TestCase):
    """The tracked example store must equal what the documented generator writes.

    ``generate_fixture_store.py``'s stated contract is that ``derived/`` and
    ``index/`` "are produced by RUNNING THE REAL BUILDER … so the fixture can never
    drift from builder output". Nothing enforced it: the fixture stamps the content
    hash of every builder module plus ``NORMALIZER_VERSION``, so ANY edit to the
    build path silently invalidates it, and ``validate_store.py`` still exits 0
    because the stale files are internally consistent. The tracked fixture has now
    drifted twice — once on ``main`` (normalizer 1 against code at 2) and once
    inside a single stack, where one PR regenerated it and three later ones
    re-broke it.

    A defect that recurs is a missing gate, so this is the gate: regenerate into a
    tmpdir and compare. One generator run costs about a second.

    Blob BYTES are deliberately exempt. They are zstd-compressed, so their bytes
    depend on the installed zstandard build, while their NAMES are the sha256 of
    the uncompressed payload and are portable — the path-set assertion below is
    what carries that meaning. Everything else — manifests, ``derived/``,
    ``index/``, ``state/``, raw payload text — is byte-compared.
    """

    IGNORED = {".DS_Store"}

    def _tree(self, root: Path) -> dict[str, Path]:
        return {p.relative_to(root).as_posix(): p
                for p in sorted(root.rglob("*"))
                if p.is_file() and p.name not in self.IGNORED
                and "__pycache__" not in p.parts}

    def test_tracked_fixture_matches_a_fresh_generator_run(self):
        gen = REPO_ROOT / "automation" / "store" / "generate_fixture_store.py"
        self.assertTrue(gen.is_file(), gen)
        with tempfile.TemporaryDirectory() as td:
            fresh_root = Path(td) / "data"
            proc = subprocess.run(
                [sys.executable, str(gen), "--root", str(fresh_root)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             f"generator failed:\n{proc.stdout}\n{proc.stderr}")
            tracked, fresh = self._tree(FIXTURE), self._tree(fresh_root)

            howto = ("re-run  .venv/bin/python "
                     "automation/store/generate_fixture_store.py  and commit the "
                     "result (the tracked fixture is generator output, not "
                     "hand-maintained)")
            self.assertEqual(sorted(fresh), sorted(tracked),
                             f"example-store file set differs from a fresh "
                             f"generator run — {howto}")

            drifted = [rel for rel in sorted(tracked)
                       if "_blobs/" not in rel
                       and tracked[rel].read_bytes() != fresh[rel].read_bytes()]
            self.assertEqual(drifted, [],
                             f"tracked example-store files are stale against the "
                             f"builder that writes them — {howto}")


if __name__ == "__main__":
    unittest.main()
