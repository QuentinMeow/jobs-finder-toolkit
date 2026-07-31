"""Regression guard: this suite must test ``automation/shared/``, not a copy.

Every module in this directory is imported into ONE process by ``unittest``
discovery before anything runs, and several of them put a skill's ``scripts/``
directory on ``sys.path`` to reach that skill's entry-point script — which in
turn puts its sibling ``_vendor/`` directory there. Before ``_canonical_imports``
existed, that made a bare ``import job_metadata`` resolve to
``skills/application-tracker/scripts/_vendor/job_metadata.py``: the suite passed
on a COPY, and the copy matched the original only because a different gate
(``sync_vendored.py --check``) enforced it.

These tests assert the resolution itself, so the next ``sys.path`` insertion
cannot re-break it invisibly. They are deliberately written against **process
state** — what ``sys.modules`` and ``sys.meta_path`` actually hold after a full
discovery pass — and derive the expected module set straight from the vendoring
manifest rather than from the guard, so the two disagreeing is a failure here.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
import unittest
from contextlib import contextmanager
from importlib.machinery import PathFinder
from pathlib import Path

from _canonical_imports import installed_finder, pin_shared_modules  # noqa: E402

pin_shared_modules()

TESTS_DIR = Path(__file__).resolve().parent
SHARED_DIR = TESTS_DIR.parent
REPO_ROOT = SHARED_DIR.parents[1]
SYNC_VENDORED = REPO_ROOT / "automation" / "vendoring" / "sync_vendored.py"

# The call every test module in this directory must make before importing a
# shared module by name.
_PIN_CALL = re.compile(r"^pin_shared_modules\(\)[ \t]*(#.*)?$", re.MULTILINE)


def _expected_names_to_vendor_dirs() -> dict[str, list[Path]]:
    """``{top-level module name: [directories holding a vendored copy]}``.

    Read from ``sync_vendored.py`` BY PATH, independently of the guard. Covers
    both file targets (``TARGETS``) and package targets (``DIR_TARGETS``); for a
    package the "directory holding the copy" is the copy's PARENT, since that is
    what a ``sys.path`` entry would point at.
    """
    spec = importlib.util.spec_from_file_location("_probe_sync_vendored",
                                                  SYNC_VENDORED)
    manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest)

    out: dict[str, list[Path]] = {}
    for source, targets in {**manifest.TARGETS, **manifest.DIR_TARGETS}.items():
        source_path = Path(source)
        if source_path.parent.as_posix() != "automation/shared":
            continue
        out[source_path.stem] = [(REPO_ROOT / t).parent for t in targets]
    return out


@contextmanager
def _evicted(name: str):
    """Drop ``name`` and its submodules from ``sys.modules``, then put them back.

    Restoring the ORIGINAL module objects matters: other test modules in this
    process hold references to them, and a half-replaced package would leak
    across tests.
    """
    prefix = name + "."
    saved = {key: module for key, module in sys.modules.items()
             if key == name or key.startswith(prefix)}
    for key in saved:
        del sys.modules[key]
    try:
        yield
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(prefix)]:
            del sys.modules[key]
        sys.modules.update(saved)


@contextmanager
def _sys_path_front(directory: Path):
    """Force ``directory`` to the very front of ``sys.path`` for the block."""
    sys.path.insert(0, str(directory))
    try:
        yield
    finally:
        sys.path.remove(str(directory))


class CanonicalModuleResolutionTests(unittest.TestCase):
    def _assert_canonical(self, module, name: str) -> None:
        origin = Path(getattr(module, "__file__", "") or "").resolve()
        self.assertTrue(
            origin.is_relative_to(SHARED_DIR),
            f"import {name} resolved to {origin}, which is not under "
            f"automation/shared/ — a vendored copy is shadowing the module "
            f"this suite claims to test",
        )

    def test_every_vendored_name_resolves_under_automation_shared(self):
        """The headline guarantee, measured after a full discovery pass.

        Names already imported by an earlier test module are checked as they sit
        in ``sys.modules`` — the state the rest of the suite actually ran
        against — so this fails if any of them picked up a ``_vendor/`` copy.
        """
        for name in sorted(_expected_names_to_vendor_dirs()):
            with self.subTest(module=name):
                module = sys.modules.get(name) or importlib.import_module(name)
                self._assert_canonical(module, name)

    def test_submodules_of_vendored_packages_are_canonical_too(self):
        """A package pin has to carry its subtree, not just its ``__init__``."""
        for dotted in ("mail.contract.transport", "mail.check_mail_safety",
                       "store.blobs", "store.serialization"):
            with self.subTest(module=dotted):
                self._assert_canonical(importlib.import_module(dotted), dotted)

    def test_resolution_survives_sys_modules_eviction(self):
        """Re-importing from scratch must not fall back to ``sys.path`` order.

        This is what separates a real fix from "the canonical copy happened to
        be imported first": a test that clears ``sys.modules`` and re-imports
        gets the canonical module again.
        """
        for name in sorted(_expected_names_to_vendor_dirs()):
            with self.subTest(module=name), _evicted(name):
                self._assert_canonical(importlib.import_module(name), name)

    def test_guard_beats_a_vendor_directory_at_the_front_of_sys_path(self):
        """Proves the guard is not vacuous, independent of discovery order.

        Each vendored directory is pushed to ``sys.path[0]`` — the exact hazard
        a skill script creates — and the import is checked twice: that the
        directory really would shadow the name, and that it does not.
        """
        for name, vendor_dirs in sorted(_expected_names_to_vendor_dirs().items()):
            for vendor_dir in vendor_dirs:
                with self.subTest(module=name, shadow=vendor_dir.name):
                    self.assertIsNotNone(
                        PathFinder.find_spec(name, [str(vendor_dir)]),
                        f"{vendor_dir} no longer holds a copy of {name}; this "
                        f"test's shadow is stale",
                    )
                    with _sys_path_front(vendor_dir), _evicted(name):
                        self._assert_canonical(importlib.import_module(name),
                                               name)


class GuardWiringTests(unittest.TestCase):
    def test_the_finder_is_installed_ahead_of_the_path_finder(self):
        finder = installed_finder()
        self.assertIsNotNone(finder, "no CanonicalSharedFinder on sys.meta_path")
        self.assertIs(sys.meta_path[0], finder,
                      "the finder must be first, ahead of the path finder")

    def test_the_pinned_set_matches_the_vendoring_manifest(self):
        """A newly vendored shared module is pinned the day it is added."""
        self.assertEqual(set(installed_finder().names),
                         set(_expected_names_to_vendor_dirs()))

    def test_every_test_module_installs_the_guard(self):
        """No file's position in the alphabet may be load-bearing.

        Discovery imports these modules in name order; whichever one runs first
        has to install the finder before it imports a shared module. Requiring
        the call in ALL of them is what makes the order irrelevant.
        """
        missing = [path.name for path in sorted(TESTS_DIR.glob("test_*.py"))
                   if not _PIN_CALL.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(
            missing, [],
            "these test modules never call pin_shared_modules(), so a bare "
            "import in them can resolve to a skills/*/scripts/_vendor/ copy: "
            f"{missing}",
        )

    def test_explicit_path_loads_are_left_alone(self):
        """Tests that deliberately load ONE named copy must keep working.

        ``spec_from_file_location`` does not consult ``sys.meta_path``, so the
        per-copy probes elsewhere in this suite still read the file they name.
        """
        copy = (REPO_ROOT / "skills" / "application-tracker" / "scripts"
                / "_vendor" / "job_metadata.py")
        spec = importlib.util.spec_from_file_location("_probe_vendored_jm", copy)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_probe_vendored_jm"] = module
        self.addCleanup(sys.modules.pop, "_probe_vendored_jm", None)
        spec.loader.exec_module(module)
        self.assertEqual(Path(module.__file__).resolve(), copy.resolve())


if __name__ == "__main__":
    unittest.main()
