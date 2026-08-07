"""Tests for the create-only copier and checksum verifier.

The load-bearing ones are the refusals: ``--copy`` must never overwrite a
destination that already holds different bytes, neither mode may ever remove a
source, and a ``--verify`` with nothing to verify must not exit 0. Everything
else in a cutover is recoverable from Git; these three are not.

Every case runs against a throwaway tree — never the real repository and never
the private overlay.

Run with:
    .venv/bin/python -m unittest discover automation/cutover/tests
"""
from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling module importable (automation/cutover/).
_CUTOVER_DIR = Path(__file__).resolve().parents[1]
if str(_CUTOVER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUTOVER_DIR))

import verify_copy  # noqa: E402

SCRIPT = _CUTOVER_DIR / "verify_copy.py"


def tree_digest(root: Path) -> str:
    """A digest over every file's relative path AND bytes under ``root``."""
    accumulator = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        accumulator.update(str(path.relative_to(root)).encode())
        accumulator.update(b"\0")
        accumulator.update(path.read_bytes())
        accumulator.update(b"\0")
    return accumulator.hexdigest()


class CopyToolTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "src"
        self.destination = self.root / "dst"
        self.manifest = self.root / "copied.txt"
        self.source.mkdir()

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        """A real subprocess with an argv LIST — no shell, no pipeline."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)

    def run_inprocess(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        code = verify_copy.main(list(args), out)
        return code, out.getvalue()


class CopyTests(CopyToolTestCase):
    def test_copy_creates_absent_destinations_and_records_one_row_each(self):
        self.write(self.source / "a.md", "alpha")
        self.write(self.source / "nested/b.yaml", "beta")

        result = self.run_cli("--copy", "--from", str(self.source),
                              "--to", str(self.destination),
                              "--manifest", str(self.manifest))

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.destination / "a.md").read_text(), "alpha")
        self.assertEqual((self.destination / "nested/b.yaml").read_text(), "beta")
        rows = verify_copy.parse_manifest(self.manifest.read_text())
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row.destination.name for row in rows), ["a.md", "b.yaml"])

    def test_copy_leaves_the_retired_source_in_place(self):
        """The 2026-08-07 precedent: a cutover copies forward, it never moves."""
        self.write(self.source / "a.md", "alpha")
        self.write(self.source / "nested/b.yaml", "beta")
        before = tree_digest(self.source)

        result = self.run_cli("--copy", "--from", str(self.source),
                              "--to", str(self.destination),
                              "--manifest", str(self.manifest))

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((self.source / "a.md").is_file())
        self.assertTrue((self.source / "nested/b.yaml").is_file())
        self.assertEqual(tree_digest(self.source), before)

    def test_copy_refuses_an_existing_destination_with_different_bytes(self):
        self.write(self.source / "a.md", "alpha")
        occupied = self.write(self.destination / "a.md", "SOMEONE ELSE'S BYTES")
        before = occupied.read_bytes()

        result = self.run_cli("--copy", "--from", str(self.source),
                              "--to", str(self.destination),
                              "--manifest", str(self.manifest))

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("a.md", result.stdout)
        self.assertEqual(occupied.read_bytes(), before)
        self.assertFalse(self.manifest.exists())

    def test_one_conflict_stops_the_whole_tree_before_anything_is_written(self):
        self.write(self.source / "a.md", "alpha")
        self.write(self.source / "b.md", "beta")
        self.write(self.destination / "b.md", "DIFFERENT")

        code, text = self.run_inprocess(
            "--copy", "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest))

        self.assertEqual(code, 1, text)
        # a.md had no conflict of its own; an all-or-nothing refusal is what
        # stops a half-migrated tree that nobody can tell apart from a whole one.
        self.assertFalse((self.destination / "a.md").exists(), text)
        self.assertEqual((self.destination / "b.md").read_text(), "DIFFERENT")

    def test_an_identical_destination_is_a_noop_with_no_manifest_row(self):
        self.write(self.source / "a.md", "alpha")
        self.write(self.destination / "a.md", "alpha")
        self.write(self.source / "b.md", "beta")

        code, text = self.run_inprocess(
            "--copy", "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest))

        self.assertEqual(code, 0, text)
        rows = verify_copy.parse_manifest(self.manifest.read_text())
        self.assertEqual([row.destination.name for row in rows], ["b.md"])
        self.assertIn("ALREADY", text)

    def test_copy_never_follows_a_symlink(self):
        outside = self.write(self.root / "outside.txt", "not yours")
        link = self.source / "link.txt"
        link.symlink_to(outside)

        code, text = self.run_inprocess(
            "--copy", "--from", str(self.source), "--to", str(self.destination))

        self.assertEqual(code, 1, text)
        self.assertIn("symlink", text)
        self.assertFalse(self.destination.exists())

    def test_a_missing_source_is_a_refusal_not_an_empty_success(self):
        code, text = self.run_inprocess(
            "--copy", "--from", str(self.root / "nope"), "--to", str(self.destination))
        self.assertEqual(code, 1, text)
        self.assertIn("does not exist", text)

    def test_copy_refuses_a_symlinked_DESTINATION(self):
        """A symlink at the destination must never be followed onto owner data.

        ``test_copy_never_follows_a_symlink`` covers a symlink inside the
        SOURCE tree. This is the other direction, and it is the dangerous one:
        the destination link points at a file outside the copy entirely, so
        following it overwrites something the copy was never asked to touch.
        The guard is ``plan_copy``'s ``is_symlink()`` branch, which was correct
        but unverified — mutating it to treat the link as creatable passed the
        whole suite.
        """
        outside = self.write(self.root / "owner-data.txt", "OWNER DATA")
        self.write(self.source / "a.md", "NEW BYTES")
        self.destination.mkdir(parents=True, exist_ok=True)
        (self.destination / "a.md").symlink_to(outside)

        code, text = self.run_inprocess(
            "--copy", "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest))

        self.assertEqual(code, 1, text)
        self.assertIn("REFUSED", text)
        self.assertEqual(outside.read_text(), "OWNER DATA",
                         "the file behind the destination symlink was overwritten")
        self.assertFalse(self.manifest.exists(),
                         "a refused run must not record a manifest row")

    def test_create_only_will_not_truncate_a_file_that_appears_after_planning(self):
        """The TOCTOU case ``O_CREAT|O_EXCL`` exists for.

        ``plan_copy`` decided the destination was absent; by the time
        ``create_only`` runs it is not. The syscall must refuse rather than
        truncate — mutating ``O_EXCL`` to ``O_TRUNC`` passed the whole suite.
        """
        source = self.write(self.source / "a.md", "NEW BYTES")
        self.destination.mkdir(parents=True, exist_ok=True)
        occupied = self.write(self.destination / "a.md", "OWNER DATA")
        pair = verify_copy.Pair(source=source, destination=occupied)

        with self.assertRaises(FileExistsError):
            verify_copy.create_only(pair)
        self.assertEqual(occupied.read_text(), "OWNER DATA")


class VerifyTests(CopyToolTestCase):
    def _copy_two_files(self) -> None:
        self.write(self.source / "a.md", "alpha")
        self.write(self.source / "nested/b.yaml", "beta")
        code, text = self.run_inprocess(
            "--copy", "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest))
        self.assertEqual(code, 0, text)

    def test_verify_of_a_matching_manifest_exits_zero(self):
        self._copy_two_files()
        result = self.run_cli("--verify", "--manifest", str(self.manifest))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("2 recorded pair(s) match", result.stdout)

    def test_one_differing_byte_exits_one_and_names_the_path(self):
        self._copy_two_files()
        (self.destination / "a.md").write_text("alphb", encoding="utf-8")

        result = self.run_cli("--verify", "--manifest", str(self.manifest))

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("MISMATCH", result.stdout)
        self.assertIn("a.md", result.stdout)

    def test_a_removed_destination_exits_one(self):
        self._copy_two_files()
        (self.destination / "a.md").unlink()
        result = self.run_cli("--verify", "--manifest", str(self.manifest))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("MISSING", result.stdout)

    def test_a_missing_manifest_is_never_a_pass(self):
        result = self.run_cli("--verify", "--manifest", str(self.manifest))
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("NOTHING TO VERIFY", result.stdout)
        self.assertNotIn("OK:", result.stdout)

    def test_an_empty_manifest_is_never_a_pass(self):
        self.manifest.write_text("", encoding="utf-8")
        code, text = self.run_inprocess("--verify", "--manifest", str(self.manifest))
        self.assertEqual(code, 3, text)
        self.assertIn("NOTHING TO VERIFY", text)

    def test_verify_leaves_both_trees_byte_identical(self):
        self._copy_two_files()
        before_source = tree_digest(self.source)
        before_destination = tree_digest(self.destination)

        result = self.run_cli("--verify", "--manifest", str(self.manifest))

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(tree_digest(self.source), before_source)
        self.assertEqual(tree_digest(self.destination), before_destination)

    def test_tree_verify_without_a_manifest_compares_both_ends(self):
        self.write(self.source / "a.md", "alpha")
        self.write(self.destination / "a.md", "alpha")
        ok = self.run_cli("--verify", "--from", str(self.source),
                          "--to", str(self.destination))
        self.assertEqual(ok.returncode, 0, ok.stdout)

        (self.destination / "a.md").write_text("drifted", encoding="utf-8")
        red = self.run_cli("--verify", "--from", str(self.source),
                           "--to", str(self.destination))
        self.assertEqual(red.returncode, 1, red.stdout)

    def test_a_malformed_manifest_is_refused_rather_than_guessed(self):
        self.manifest.write_text("not-a-digest  /a\t/b\n", encoding="utf-8")
        code, text = self.run_inprocess("--verify", "--manifest", str(self.manifest))
        self.assertEqual(code, 1, text)
        self.assertIn("sha256", text)


class ManifestFormatTests(unittest.TestCase):
    def test_rows_round_trip(self):
        row = verify_copy.Row("0" * 64, Path("/tmp/src/a.md"), Path("/tmp/dst/a.md"))
        parsed = verify_copy.parse_manifest(verify_copy.format_row(row) + "\n")
        self.assertEqual(parsed, [row])

    def test_a_path_with_a_tab_is_refused_rather_than_recorded(self):
        row = verify_copy.Row("0" * 64, Path("/tmp/we\tird"), Path("/tmp/dst"))
        with self.assertRaises(verify_copy.CopyRefused):
            verify_copy.format_row(row)


if __name__ == "__main__":
    unittest.main()
