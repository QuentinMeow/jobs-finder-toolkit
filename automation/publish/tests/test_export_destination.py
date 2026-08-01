"""Tests for WHERE the exporter is allowed to write, and what ``--force`` may delete.

The regression: the destination guard refused only the repo root and its
ancestors, so ``export_public.py --dest private --force`` fell through to
``shutil.rmtree()`` on the mounted private overlay — a separate git repository
holding the owner's applications, interviews, dossiers and profile, which
AGENTS.md says an agent must never delete "under any condition".

Two rules are pinned here, and the destructive path is never executed:

  * ``forbidden_destination`` — the BLOCKLIST of paths that are never a
    legitimate target (the checkout, anything inside it, the private overlay and
    any configured owner-data root, ``$HOME``, another git checkout). It runs
    before every other gate in ``export()``, so a bad ``--dest`` is refused even
    in a checkout that would fail the arming gate.
  * ``overwrite_refusal`` — the ALLOWLIST of what ``--force`` may DELETE: an
    empty directory, or one carrying this exporter's own marker file. Every
    other existing directory belongs to the user.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402
import export_public  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT
EXPORTER = REPO_ROOT / "automation/publish/export_public.py"
MARKER = export_public.EXPORT_MARKER_NAME

# The exporter's own arming refusal (test_export_arming.py owns it). Named here
# only to prove the destination check runs FIRST: a forbidden --dest must be
# refused by the destination rule, not by the arming gate.
ARMING_NEEDLE = "the leak guard is UNARMED in this checkout"
# A token that arms the guard without naming anybody.
PROBE_TOKEN = "zz-export-destination-probe-token"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


class ForbiddenDestinationTests(unittest.TestCase):
    """The blocklist: destinations that are never legitimate, with a reason."""

    def _patch_root(self, root: Path) -> None:
        original = export_public.REPO_ROOT
        export_public.REPO_ROOT = root
        self.addCleanup(lambda: setattr(export_public, "REPO_ROOT", original))

    def test_the_private_overlay_is_refused(self):
        """The reported defect: --dest private --force would rmtree the overlay."""
        for rel in ("private", "private/applications/6_drafted", "private/.git"):
            dest = (REPO_ROOT / rel).resolve()
            reason = export_public.forbidden_destination(dest)
            self.assertIsNotNone(reason, rel)
            self.assertIn("private overlay", reason)
            self.assertIn("owner data", reason)

    def test_an_overlay_mounted_outside_the_checkout_is_refused(self):
        """``private/`` is checked by its REAL path, so a symlinked mount counts."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            root.mkdir()
            overlay = Path(td) / "elsewhere-overlay"
            overlay.mkdir()
            os.symlink(overlay, root / "private")
            self._patch_root(root)

            reason = export_public.forbidden_destination(overlay.resolve())
            self.assertIsNotNone(reason)
            self.assertIn("private overlay", reason)

    def test_anything_inside_the_source_checkout_is_refused(self):
        for rel in ("local/export", "examples", "skills", ".git", "docs/handbook"):
            dest = (REPO_ROOT / rel).resolve()
            reason = export_public.forbidden_destination(dest)
            self.assertIsNotNone(reason, rel)
            self.assertIn(str(REPO_ROOT), reason, rel)

    def test_the_checkout_and_its_ancestors_are_refused(self):
        self.assertEqual(export_public.forbidden_destination(REPO_ROOT),
                         "it is the source checkout itself")
        for parent in list(REPO_ROOT.parents)[:3]:
            reason = export_public.forbidden_destination(parent)
            self.assertIsNotNone(reason, parent)
            self.assertIn("contains the source checkout", reason)

    def test_the_real_home_directory_is_refused(self):
        self.assertIsNotNone(export_public.forbidden_destination(Path.home().resolve()))

    def test_the_home_directory_and_its_parents_are_refused(self):
        """A checkout OUTSIDE $HOME, so the home rule is the one that fires.

        In this repo's normal layout the checkout lives under the home directory,
        so ``$HOME`` is caught one rule earlier ("it contains the source
        checkout"). Both fixtures are synthetic here — a fake ``$HOME`` and a
        fake checkout beside it — so the home rule is exercised on its own.
        """
        with tempfile.TemporaryDirectory() as td:
            fake_home = Path(td) / "home/someone"
            fake_home.mkdir(parents=True)
            root = Path(td) / "src"
            root.mkdir()
            self._patch_root(root.resolve())
            previous = os.environ.get("HOME")
            os.environ["HOME"] = str(fake_home)
            self.addCleanup(lambda: os.environ.__setitem__("HOME", previous)
                            if previous is not None else os.environ.pop("HOME", None))

            self.assertEqual(export_public.forbidden_destination(fake_home.resolve()),
                             "it is your home directory")
            reason = export_public.forbidden_destination((Path(td) / "home").resolve())
            self.assertIsNotNone(reason)
            self.assertIn("contains your home directory", reason)

    def test_a_destination_inside_another_git_checkout_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            other = Path(td) / "someones-project"
            (other / "sub").mkdir(parents=True)
            _git(other, "init")

            reason = export_public.forbidden_destination((other / "sub/export").resolve())
            self.assertIsNotNone(reason)
            self.assertIn("inside another git checkout", reason)
            self.assertIn(str(other.resolve()), reason)

    def test_an_existing_non_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "notes.txt"
            target.write_text("not a directory\n", encoding="utf-8")
            self.assertEqual(export_public.forbidden_destination(target.resolve()),
                             "it exists and is not a directory")

    def test_a_legitimate_destination_is_permitted(self):
        with tempfile.TemporaryDirectory() as td:
            absent = (Path(td) / "public-export").resolve()
            self.assertIsNone(export_public.forbidden_destination(absent))
            empty = Path(td) / "empty"
            empty.mkdir()
            self.assertIsNone(export_public.forbidden_destination(empty.resolve()))


class OverwriteAllowlistTests(unittest.TestCase):
    """What ``--force`` may delete: empty, or a tree this exporter wrote."""

    def test_an_empty_directory_may_be_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(export_public.overwrite_refusal(Path(td)))

    def test_a_marked_directory_may_be_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            (dest / MARKER).write_text(export_public.EXPORT_MARKER_TEXT, encoding="utf-8")
            (dest / "AGENTS.md").write_text("a previous export\n", encoding="utf-8")
            self.assertIsNone(export_public.overwrite_refusal(dest))

    def test_an_unmarked_non_empty_directory_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            (dest / "tax-returns.pdf").write_text("mine\n", encoding="utf-8")
            reason = export_public.overwrite_refusal(dest)
            self.assertIsNotNone(reason)
            self.assertIn("tax-returns.pdf", reason)
            self.assertIn(MARKER, reason)

    def test_a_foreign_git_checkout_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "someones-project"
            dest.mkdir()
            _git(dest, "init")
            reason = export_public.overwrite_refusal(dest)
            self.assertIsNotNone(reason)
            self.assertIn(".git", reason)


class DestinationRefusalOrderingTests(unittest.TestCase):
    """A refusal must land BEFORE any filesystem mutation, and before arming."""

    def test_a_fake_overlay_survives_dest_private_force(self):
        """The defect, reproduced against a THROWAWAY tree: nothing is deleted.

        The real overlay is never used as a fixture — the point of the fix is
        that this path must not run. A fake checkout with a fake ``private/``
        exercises the identical code with the identical argument.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            (root / "private/applications/6_drafted/acme-20260101").mkdir(parents=True)
            sentinel = root / "private/applications/6_drafted/acme-20260101/meta.yaml"
            sentinel.write_text("company: Acme\n", encoding="utf-8")
            original = export_public.REPO_ROOT
            export_public.REPO_ROOT = root
            self.addCleanup(lambda: setattr(export_public, "REPO_ROOT", original))

            rc = export_public.export(root / "private", git_init=False, force=True)

            self.assertEqual(rc, 2)
            self.assertTrue(sentinel.is_file(), "the overlay must survive --force")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "company: Acme\n")
            self.assertEqual(sorted(p.name for p in (root / "private").iterdir()),
                             ["applications"])

    def test_the_cli_refuses_dest_private_before_the_arming_gate(self):
        """Unarmed + forbidden --dest: the DESTINATION rule is what fires."""
        env = dict(os.environ)
        env.pop(check_public.TOKENS_ENV_VAR, None)
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        overlay = REPO_ROOT / "private"
        # The overlay is the owner's data: this test reads its top-level shape and
        # asserts the run left it untouched. It never writes there.
        before = sorted(p.name for p in overlay.iterdir()) if overlay.is_dir() else None

        proc = subprocess.run(
            [sys.executable, str(EXPORTER), "--dest", "private", "--force"],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )

        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn(f"refusing to export into {overlay}", proc.stderr)
        self.assertIn("private overlay", proc.stderr)
        self.assertNotIn(ARMING_NEEDLE, proc.stderr)
        after = sorted(p.name for p in overlay.iterdir()) if overlay.is_dir() else None
        self.assertEqual(before, after, "the overlay must be untouched")

    def test_an_unmarked_destination_survives_force(self):
        env = dict(os.environ)
        env[check_public.TOKENS_ENV_VAR] = PROBE_TOKEN
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "not-an-export"
            dest.mkdir()
            sentinel = dest / "sentinel.txt"
            sentinel.write_text("do not delete me\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(EXPORTER), "--dest", str(dest), "--force"],
                cwd=REPO_ROOT, capture_output=True, text=True, env=env,
            )

            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn(f"refusing to delete {dest.resolve()}", proc.stderr)
            self.assertIn("sentinel.txt", proc.stderr)
            self.assertTrue(sentinel.is_file(),
                            "refusal must happen BEFORE shutil.rmtree(dest)")


class MarkedDestinationTests(unittest.TestCase):
    """A real export marks its destination, and may then be re-run over it."""

    def setUp(self):
        os.environ[check_public.TOKENS_ENV_VAR] = PROBE_TOKEN
        self.addCleanup(lambda: os.environ.pop(check_public.TOKENS_ENV_VAR, None))

    def test_a_fresh_export_is_marked_and_re_exportable_but_never_published(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "public-export"

            rc = export_public.export(dest, git_init=False, force=False)
            self.assertEqual(rc, 0, "a legitimate destination must still export")

            marker = dest / MARKER
            self.assertTrue(marker.is_file(), "the export must mark its destination")
            self.assertIn("export target", marker.read_text(encoding="utf-8"))

            # The marker is local to this directory: it is excluded from the
            # export's own git history, so it can never reach a published tree.
            tracked = subprocess.run(["git", "ls-files"], cwd=dest,
                                     capture_output=True, text=True, check=True).stdout
            self.assertNotIn(MARKER, tracked)
            self.assertGreater(len(tracked.splitlines()), 100, "export staged nothing?")

            # And the marker is what makes the repeat run safe.
            self.assertIsNone(export_public.overwrite_refusal(dest))
            rc = export_public.export(dest, git_init=False, force=True)
            self.assertEqual(rc, 0, "a marked destination must be re-exportable")
            self.assertTrue((dest / MARKER).is_file())
            self.assertTrue((dest / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
