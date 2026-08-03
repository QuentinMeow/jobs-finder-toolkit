"""The vendor gate must fail on a ``_vendor/`` file nobody declared.

``sync_vendored.check()`` used to walk the manifest in one direction only: for
each declared target, does the copy still match its source? A module copied into
``skills/<skill>/scripts/_vendor/`` whose ``TARGETS`` entry was forgotten was
therefore compared against nothing — the pre-commit vendor gate stayed green
forever while that copy drifted away from ``automation/shared/``. A gate that
fails open.

``undeclared_vendored_files()`` is the reverse audit that closes it. These tests
pin three things a future edit could quietly undo: the audit's verdicts on a
synthetic tree, the narrowness of the exemption list, and — the one that matters
most — that ``check()`` still returns non-zero when the audit reports something.
An audit nothing consults is the same fail-open bug wearing a function name.

This suite lives beside the other vendoring-manifest tests in
``automation/shared/tests`` because that is the only directory ``run_gates.py``
and ``ci.yml`` discover for them; ``automation/vendoring/`` has no test dir.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules  # noqa: E402

pin_shared_modules()

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]
SYNC_VENDORED = REPO_ROOT / "automation" / "vendoring" / "sync_vendored.py"


def _load_manifest():
    """Load ``sync_vendored.py`` BY PATH, under a private alias.

    Same trick as ``test_canonical_module_resolution``: the file is a script in
    ``automation/vendoring/``, not an importable package, and loading it by path
    keeps it out of ``sys.modules`` under a name another test could collide with.
    """
    spec = importlib.util.spec_from_file_location("_probe_reverse_audit_sv",
                                                  SYNC_VENDORED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class RealTreeTests(unittest.TestCase):
    """The audit's verdict on the repository as it actually stands."""

    def test_no_undeclared_file_under_any_vendor_root(self):
        undeclared = _load_manifest().undeclared_vendored_files()
        self.assertEqual(
            undeclared, [],
            "these files sit under a skills/*/scripts/_vendor/ root but no "
            "TARGETS or DIR_TARGETS entry names them, so nothing compares them "
            "to a canonical source: " + ", ".join(undeclared))

    def test_the_exemption_list_stays_narrow(self):
        """Widening it must be a deliberate, reviewable edit — not a drive-by.

        Every name here is structure rather than vendored code: a README is the
        "generated, do not edit" notice, an ``__init__.py`` is a package marker.
        Anything else appearing in this set means real code stopped being
        checked.
        """
        self.assertEqual(_load_manifest()._VENDOR_ROOT_EXEMPT,
                         frozenset({"README.md", "__init__.py"}))


class SyntheticTreeTests(unittest.TestCase):
    """Verdict-by-verdict, over a tree and a manifest built for the test."""

    def setUp(self):
        import tempfile  # noqa: PLC0415

        self.manifest = _load_manifest()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vendor = self.root / "skills" / "demo" / "scripts" / "_vendor"
        self.vendor.mkdir(parents=True)
        self.targets = {"automation/shared/thing.py":
                        ["skills/demo/scripts/_vendor/thing.py"]}
        self.dir_targets = {"automation/shared/pkg":
                            ["skills/demo/scripts/_vendor/pkg"]}

    def _audit(self) -> list[str]:
        return self.manifest.undeclared_vendored_files(
            self.root, self.targets, self.dir_targets)

    def test_a_declared_target_and_a_declared_tree_are_accounted_for(self):
        _write(self.vendor / "thing.py")
        _write(self.vendor / "pkg" / "__init__.py")
        _write(self.vendor / "pkg" / "deep" / "helper.py")
        self.assertEqual(self._audit(), [])

    def test_an_undeclared_module_is_reported(self):
        _write(self.vendor / "thing.py")
        _write(self.vendor / "sneaked_in.py")
        self.assertEqual(self._audit(),
                         ["skills/demo/scripts/_vendor/sneaked_in.py"])

    def test_an_undeclared_file_of_any_type_is_reported(self):
        """Not just ``*.py`` — a data file drifts from its source just as well."""
        _write(self.vendor / "table.json", "{}\n")
        self.assertEqual(self._audit(),
                         ["skills/demo/scripts/_vendor/table.json"])

    def test_readme_and_init_are_exempt_at_the_vendor_root(self):
        _write(self.vendor / "README.md", "# generated\n")
        _write(self.vendor / "__init__.py", "")
        self.assertEqual(self._audit(), [])

    def test_the_same_names_are_not_exempt_below_the_root(self):
        """The exemption is by name AND position, deliberately.

        A ``README.md`` inside an undeclared subdirectory is not the vendoring
        notice — it is an unmirrored tree, exactly what this audit is for.
        """
        _write(self.vendor / "extra" / "README.md", "# not the notice\n")
        _write(self.vendor / "extra" / "__init__.py", "")
        self.assertEqual(self._audit(), [
            "skills/demo/scripts/_vendor/extra/README.md",
            "skills/demo/scripts/_vendor/extra/__init__.py",
        ])

    def test_build_artifacts_are_not_reported(self):
        _write(self.vendor / "__pycache__" / "thing.cpython-311.pyc", "")
        _write(self.vendor / "stale.pyc", "")
        self.assertEqual(self._audit(), [])

    def test_vendor_dirs_outside_the_skills_tree_are_not_swept_in(self):
        """Scoping matters: third-party ``_vendor/`` trees are not ours.

        A bare ``rglob('_vendor')`` would report every file in, say,
        ``.venv/**/site-packages/pip/_vendor`` and make the gate unusable.
        """
        _write(self.root / ".venv" / "lib" / "pip" / "_vendor" / "urllib3.py")
        _write(self.root / "automation" / "shared" / "_vendor" / "nope.py")
        self.assertEqual(self._audit(), [])


class GateWiringTests(unittest.TestCase):
    """``check()`` must actually consult the audit and go red on a finding."""

    def test_check_returns_one_when_the_audit_reports_a_file(self):
        manifest = _load_manifest()
        manifest.undeclared_vendored_files = lambda *a, **k: [
            "skills/demo/scripts/_vendor/sneaked_in.py"]
        self.assertEqual(manifest.check(), 1)

    def test_check_returns_zero_when_the_audit_is_empty(self):
        """Guards the other direction: the pin above must not pass vacuously."""
        manifest = _load_manifest()
        manifest.undeclared_vendored_files = lambda *a, **k: []
        self.assertEqual(manifest.check(), 0)

    def test_the_failure_message_names_the_file_and_the_two_remedies(self):
        """An agent reading the gate output must not have to open the script."""
        import io  # noqa: PLC0415
        from contextlib import redirect_stderr  # noqa: PLC0415

        manifest = _load_manifest()
        offender = "skills/demo/scripts/_vendor/sneaked_in.py"
        manifest.undeclared_vendored_files = lambda *a, **k: [offender]
        err = io.StringIO()
        with redirect_stderr(err):
            manifest.check()
        message = err.getvalue()
        self.assertIn(offender, message)
        self.assertIn("TARGETS", message)
        self.assertIn("DIR_TARGETS", message)
        self.assertIn("delete the file", message)


if __name__ == "__main__":
    unittest.main()
