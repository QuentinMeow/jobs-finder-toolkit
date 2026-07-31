"""Pin every vendored module name to its canonical ``automation/shared/`` file.

WHY THIS EXISTS
---------------
``unittest`` discovery imports every module in this directory into ONE process
before it runs anything, and several of those modules legitimately put a skill's
``scripts/`` directory on ``sys.path`` so they can import that skill's own
entry-point script. Those skill scripts then insert their sibling ``_vendor/``
directory on ``sys.path`` too. From that moment a bare ``import job_metadata``
anywhere in the run resolves to
``skills/application-tracker/scripts/_vendor/job_metadata.py`` — a COPY —
instead of ``automation/shared/job_metadata.py``, the file this suite exists to
test.

That made the suite's guarantee wrong as stated: it reported on a copy, and the
copy was equal to the canonical file only because a *different* gate
(``automation/vendoring/sync_vendored.py --check``) said so. A canonical-only
change was untested until it had been vendored — the opposite of the intended
order.

THE MECHANISM
-------------
A ``sys.meta_path`` finder. ``sys.meta_path`` is consulted BEFORE ``sys.path``,
so the finder wins over any path insertion regardless of when that insertion
happened or which module made it — the resolution stops depending on import
order, rather than depending on a *different* order. For each pinned top-level
name it delegates to ``PathFinder.find_spec(name, path=[automation/shared])``:
the ordinary import machinery, aimed at exactly one directory.

Installed by ``pin_shared_modules()``, which every ``test_*.py`` in this
directory calls before its first repo-local import. It is called from EVERY test
module on purpose, so no single file's position in the alphabet is load-bearing;
the first module discovery happens to import installs the finder and the rest are
no-ops. ``test_canonical_module_resolution.py`` asserts both that the call is
present in every test module and that the resolution actually holds.

(A package ``__init__.py`` would be the tidier hook, but ``unittest discover
automation/shared/tests`` — the form CI and the pre-commit gate run — sets
``top_level_dir`` equal to the start directory, imports each test module as a
TOP-LEVEL module, and never imports ``__init__.py`` at all.)

The pinned set is DERIVED from ``TARGETS``/``DIR_TARGETS`` in
``automation/vendoring/sync_vendored.py``, not restated here, so a module that
becomes vendored later is covered the day it is added.

WHAT THIS GUARANTEES
--------------------
* In a discovery run over this directory, every top-level
  ``import <vendored-name>`` resolves under ``automation/shared/`` — whatever
  else is on ``sys.path``, and whatever order it got there.
* It survives ``sys.modules`` eviction and reload: the finder runs on every
  import, not once at startup.
* Submodules follow their parent (``mail.contract.transport``, ``store.blobs``),
  because the parent package's ``__path__`` is canonical.

WHAT THIS DOES **NOT** GUARANTEE
--------------------------------
* **It is not a drift check.** It never compares the canonical file with its
  vendored copies; ``sync_vendored.py --check`` remains the only gate that fails
  on divergence. This finder makes THIS suite's claim honest — that it tested the
  canonical module — and nothing more.
* **It does not cover the vendored copies.** With the finder installed, a skill
  script imported by a test here (for example ``backfill_job_metadata``) gets the
  canonical module rather than its own ``_vendor/`` copy. The copies are
  exercised by the per-skill suites under ``skills/*/scripts/tests``, which run
  in separate processes and never call this.
* **It does not cover a test module that never calls it.** A new ``test_*.py``
  added without the call is caught by ``test_canonical_module_resolution.py``,
  not by anything at import time.
* **It does not cover other suites.** Only this directory calls it.
* **It does not intercept explicit-path loads.**
  ``importlib.util.spec_from_file_location`` bypasses ``sys.meta_path``
  entirely, so tests that deliberately load one named copy (the per-copy
  ``config.py`` probes in ``test_config_accessors.py``, the by-path loads in
  ``test_company_key_additive.py``) keep working unchanged. That is intended:
  those tests are ABOUT a specific copy.
* **It pins names, not behaviour.** If a canonical module is deleted or renamed
  the finder simply stops matching and normal ``sys.path`` resolution resumes —
  which is why the regression test asserts the resolution instead of trusting
  the install.
"""
from __future__ import annotations

import importlib.util
import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec, PathFinder
from pathlib import Path
from typing import Sequence

# automation/shared/tests/_canonical_imports.py -> automation/shared
SHARED_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SHARED_DIR.parents[1]
SYNC_VENDORED = REPO_ROOT / "automation" / "vendoring" / "sync_vendored.py"


def vendoring_manifest():
    """Load ``sync_vendored.py`` BY PATH, under a private alias.

    By path because ``automation/vendoring`` is not on ``sys.path`` here, and
    under a private alias because the manifest is a script, not a library — no
    caller should end up sharing this module object by name.
    """
    spec = importlib.util.spec_from_file_location(
        "_canonical_imports_sync_vendored", SYNC_VENDORED)
    if spec is None or spec.loader is None:      # a moved manifest must be loud
        raise RuntimeError(f"cannot load the vendoring manifest: {SYNC_VENDORED}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned_names() -> frozenset[str]:
    """Top-level module names that must resolve under ``automation/shared/``.

    Derived from the vendoring manifest rather than restated, so the pin set and
    the vendoring set cannot drift apart. Only sources that actually live in
    ``automation/shared/`` are pinned — a future target rooted elsewhere is
    skipped rather than mis-aimed at this directory.
    """
    manifest = vendoring_manifest()
    names: set[str] = set()
    for source in list(manifest.TARGETS) + list(manifest.DIR_TARGETS):
        path = Path(source)
        if path.parent.as_posix() != "automation/shared":
            continue
        names.add(path.stem)                     # "automation/shared/mail" -> "mail"
    return frozenset(names)


class CanonicalSharedFinder(MetaPathFinder):
    """Resolve a fixed set of top-level names out of ``automation/shared/``."""

    def __init__(self, names: frozenset[str], root: Path) -> None:
        self.names = names
        self.root = root

    def find_spec(self, fullname: str, path: Sequence[str] | None = None,
                  target: object = None) -> ModuleSpec | None:
        # ``path is not None`` means "resolving a SUBmodule of an already
        # imported package". That parent's ``__path__`` is canonical already, so
        # stepping in would only risk re-rooting a same-named submodule.
        if path is not None or fullname not in self.names:
            return None
        return PathFinder.find_spec(fullname, [str(self.root)])


def pin_shared_modules() -> CanonicalSharedFinder:
    """Put the finder first on ``sys.meta_path`` (idempotent); return it.

    Every ``test_*.py`` in this directory calls this before its first repo-local
    import. Calling it twice is free.
    """
    existing = installed_finder()
    if existing is not None:
        return existing
    finder = CanonicalSharedFinder(pinned_names(), SHARED_DIR)
    sys.meta_path.insert(0, finder)
    return finder


def installed_finder() -> CanonicalSharedFinder | None:
    """The live finder, or ``None`` — how a test inspects process state."""
    for entry in sys.meta_path:
        if isinstance(entry, CanonicalSharedFinder):
            return entry
    return None
