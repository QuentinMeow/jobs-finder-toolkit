#!/usr/bin/env python3
"""Deterministic two-repository fixture for the reconciliation stage benchmarks.

The reconciliation leg (`evals/protocols/reconciliation-stages.md`) measures the
"the prerequisite PRs merged; reconcile preserved local work and publish the
remainder" workflow. Measuring it needs an entry state that is the SAME every
time, on every machine — otherwise a stage row is comparing two different
problems. This module generates that state.

## Why a generator and not committed repositories

Two git repositories checked into a third git repository are hostile to
``git ls-files``, to the leak guard's binary/path denylists, and to review. A
generator that reproduces **byte-identical commit object SHAs** on any machine
buys the same pinning guarantee from tracked, reviewable Python. The pins live
in :data:`PINNED_SHAS` and are asserted by
``automation/evals/tests/test_reconciliation_fixture.py`` — so editing the recipe
without bumping :data:`FIXTURE_VERSION` turns the ``tests-evals`` gate red, which
is the only form of "a fixture edit invalidates every row that used it" that
actually holds.

## What it builds

Everything the task's "Benchmark scenario" section names, and nothing else::

    <out>/
      fixture.json               # version, variant, repo paths, commit SHAs
      remotes/public.git/        # bare; the public repo's origin
      remotes/overlay.git/       # bare; the overlay's origin
      public/                    # public toolkit repo — layout refactor MERGED
        .gitignore               #   carries private/ (the overlay is ignored)
        person/**                #   post-refactor candidate content
        docs/roadmap/, tasks/, memory/, message-queue/, history/
        private/                 # nested overlay repo (its own .git)
          person/**              #   post-refactor content on origin/main
          me/**                  #   pre-refactor content in the WORKING TREE
          me/local-cache/…       #   git-ignored file, retained at the source

  * **public**: ``main`` == ``origin/main`` == the layout-refactor commit, clean
    working tree. The rename ``me/`` → ``person/`` is in its history at 100%
    similarity for every file whose content carries no path.
  * **overlay**: ``origin/main`` is the layout-refactor commit; local ``main`` is
    one commit BEHIND it; the checked-out branch ``codex/dirty`` sits on the
    pre-refactor commit with a **small uncommitted patch authored against the old
    paths** — exactly the state a post-merge reconciliation has to replay.
  * **one generated-file path-only conflict**: ``generated/calendar.md`` is
    rewritten by the refactor commit, and the dirty patch edits it too. The
    refactor's delta on that file is ``me/`` → ``person/`` **and nothing else**,
    which is what makes the conflict mechanically resolvable — and what a stage
    row is allowed to assume only because a test proves it.
  * **one ignored file** at ``me/local-cache/scratch.txt``: it must be copied to
    the new path WITHOUT overwriting anything and WITHOUT being removed from the
    source. Variant ``destination-exists`` pre-places a DIFFERENT file at the
    destination so the non-overwriting path has something to refuse.
  * **closeout records requiring normal gates**: the public tree's process
    folders are real, and ``automation/reconcile/reconcile.py --root <public>
    --check`` is RED on a fresh fixture (no handover, no ``memory/index.md``) and
    goes GREEN once the closeout records exist. The reconciler is the real one,
    not a simulation.

## Identity

Every byte is synthetic. The persona is the repository's fictional example
candidate, "Jordan Rivers" (``config.example.yaml``); no real name, employer,
posting or dated personal record appears here or in anything this builds.

## Determinism

Commit SHAs are pinned, so the recipe controls every input to the object hash:

  * a MINIMAL environment — the operator's ``~/.gitconfig``, ``GIT_CONFIG_*``,
    ``GIT_DIR``, locale and timezone are not inherited, they are replaced;
  * ``HOME``/``XDG_CONFIG_HOME`` point at a throwaway directory, which is what
    neutralises a global config on git < 2.32 (where ``GIT_CONFIG_GLOBAL`` does
    not exist);
  * ``git symbolic-ref HEAD refs/heads/main`` instead of ``--initial-branch``
    (added in git 2.28; this repo's macOS toolchain ships 2.23);
  * pinned ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` name, email AND date;
  * ``core.autocrlf=false``, ``commit.gpgsign=false``, an empty init template.

**Packfile bytes are NOT pinned** — they differ between git versions. Only
commit object SHAs are, and those are what identify the state under test.

## Usage

    .venv/bin/python automation/evals/reconciliation_fixture.py list-variants
    .venv/bin/python automation/evals/reconciliation_fixture.py build \\
        --out local/reconciliation-bench/fixture-1
    .venv/bin/python automation/evals/reconciliation_fixture.py verify \\
        --out local/reconciliation-bench/fixture-1

``build`` prints the manifest (``--json`` for the machine-readable form). ``verify``
rebuilds nothing when given ``--out`` — it re-reads the tree and compares it to
:data:`PINNED_SHAS` plus the structural invariants; without ``--out`` it builds a
throwaway tree first. Exit 0 clean, 1 on a mismatch, 2 on a usage/IO failure.

**The destination is guarded.** ``build`` refuses any path inside this checkout
that git does not ignore, so a mistyped ``--out`` can never write into the tracked
tree (or into the real ``private/`` overlay).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Bump on ANY change to the recipe below (content, order, dates, refs). The pinned
# SHAs move with it, and a row recorded against an older version is not comparable.
FIXTURE_VERSION = "recon-v1"

# The fictional example candidate this repo already ships. Never a real person.
FIXTURE_ACTOR_NAME = "Jordan Rivers"
FIXTURE_ACTOR_EMAIL = "jordan.rivers@example.com"

# Fixed commit timestamps. Synthetic and in the past — ``check_roadmap_dated``
# rejects a FUTURE Last-updated date, so a fixture dated forward would rot into a
# red gate on its own.
_SEED_DATE = "2026-01-05T09:00:00+00:00"
_REFACTOR_DATE = "2026-01-05T11:30:00+00:00"

# The roadmap date the fixture's public tree carries. Same reasoning as above.
_ROADMAP_DATE = "2026-01-05"

# The task/conversation id the closeout records hang off.
FIXTURE_TASK_ID = "2026-01-05-fixture-reconciliation"

VARIANTS: dict[str, str] = {
    "base": (
        "The scenario as written: overlay dirty patch at the old paths, a "
        "path-only generated-file conflict, and an ignored file whose "
        "destination is FREE."
    ),
    "destination-exists": (
        "base, plus a DIFFERENT ignored file already sitting at the copy "
        "destination — so a non-overwriting copy has something to refuse."
    ),
    "closeout-done": (
        "base, plus the closeout records already written — the control arm for "
        "the closeout stage, on which the reconciler is green from the start."
    ),
}

DEFAULT_VARIANT = "base"

# Commit object SHAs, per repository, in build order. Asserted by the test suite;
# a recipe edit that does not bump FIXTURE_VERSION turns ``tests-evals`` red.
#
# The three variants differ ONLY in untracked/ignored working-tree files and (for
# closeout-done) in files written after the last commit, so every variant shares
# these commits. That is deliberate: a variant must not silently change the
# history a stage row was measured against.
PINNED_SHAS: dict[str, dict[str, str]] = {
    "public": {
        "seed": "49590fcd9e48601c6326d3a2617be3a3e0a380c0",
        "layout-refactor": "3ea4a2a7acc2109fa87b3841d0c6eb7afc3c2ba0",
    },
    "overlay": {
        "seed": "9722a50523a437c77ad0d0df57e39a3e0a83d753",
        "layout-refactor": "3d5dd531c052509cf613d3c4895829e4eec195db",
    },
}

# Destination roots inside this checkout that a fixture may be built into. Both are
# git-ignored scratch; every other path inside the checkout is refused outright.
_ALLOWED_DEST_ROOTS = ("local", "logs")

# The one path inside a built fixture whose parent is neither repo.
MANIFEST_NAME = "fixture.json"


class FixtureError(RuntimeError):
    """Any refusal or failure this module raises deliberately."""


# ── file bodies ──────────────────────────────────────────────────────────────
#
# Kept as module constants rather than generated strings so a reviewer can read
# the fixture without running it, and so a content edit is a visible diff.

_PUBLIC_GITIGNORE = """\
# Private overlay: a separate git repository mounts here. Never committed.
private/
# Scratch
local/
/logs/
# Machine-local cache the toolkit regenerates; never committed.
local-cache/
"""

_OVERLAY_GITIGNORE = """\
# Machine-local cache the toolkit regenerates; never committed.
local-cache/
"""

_PUBLIC_README = f"""\
# Synthetic reconciliation fixture — public repository

Generated by `automation/evals/reconciliation_fixture.py`
(FIXTURE_VERSION `{FIXTURE_VERSION}`). Every byte is synthetic: the persona is the
toolkit's fictional example candidate. Nothing here describes a real person,
employer or posting.

The private overlay is a separate git repository mounted at `private/`.
"""

_OVERLAY_README = f"""\
# Synthetic reconciliation fixture — private overlay

Generated by `automation/evals/reconciliation_fixture.py`
(FIXTURE_VERSION `{FIXTURE_VERSION}`). Synthetic throughout. This tree stands in
for the overlay repository that mounts at the public repository's `private/`
path.
"""

_ROADMAP_CURRENT = f"""\
# Current state (synthetic fixture)

- **Last-updated**: {_ROADMAP_DATE}

Candidate content lives under `me/`. The person-first layout refactor moves it to
`person/` in the next commit.
"""

_ROADMAP_CURRENT_AFTER = f"""\
# Current state (synthetic fixture)

- **Last-updated**: {_ROADMAP_DATE}

Candidate content lives under `person/`. The person-first layout refactor is
merged.
"""

_ROADMAP_DESIRED = """\
# Desired state (synthetic fixture)

One fail-closed path from two-repository inventory through closeout, instead of
reconstructing the same procedure every session.
"""

_TASK_MD = """\
# Reconcile preserved local work after the layout refactor

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: synthetic benchmark fixture (`automation/evals/reconciliation_fixture.py`)
- **Claimed-by**: benchmark subject agent

## Goal

Replay the overlay's dirty patch across the merged layout refactor, copy the
git-ignored cache file without overwriting the destination or removing the
source, and write the closeout records.
"""

_MEMORY_DECISION = """\
# Move candidate content from me/ to person/

- **Status**: decided
- **Date**: 2026-01-05

## Decision

Person-first folders. For generated files the rename is path-only, so a replay
across it is mechanical.
"""

_SESSION_NOTES = """\
# Session notes (synthetic)

The functional reconciliation is finished. The handover has not been written yet
— that absence is this fixture's closeout entry condition, and the reconciler
reports it.
"""

_HANDOVER = """\
# Handover — synthetic fixture closeout

- **Date**: 2026-01-05
- **Session**: benchmark subject agent

## What happened

The overlay's dirty patch was replayed across the merged layout refactor and the
git-ignored cache file was handled without overwriting or deleting anything.

## What is left

Nothing. This handover is the closeout record the reconciler requires.
"""

_PROFILE_MD = """\
# Jordan Rivers — synthetic profile

The toolkit's fictional example candidate. This file exists so the fixture has
candidate-shaped content to rename; it describes nobody.
"""

# Path-free on purpose: this is the file whose rename must be detected at 100%
# similarity, and any path string inside it would make the refactor commit rewrite
# it, which would drop the similarity below 100%.
_JOURNAL_MD = """\
# Journal (synthetic)

- day 1 — drafted the reconciliation notes.
- day 2 — checkpointed before the layout refactor landed.
"""

_JOURNAL_DIRTY_LINE = "- day 6 — local work in progress, not yet committed.\n"

_META_YAML = """\
# Synthetic application metadata (fixture only).
company: Example Labs
company_slug: example-labs
jobs:
  - title: Example Role
    status: drafted
    location: Remote (US)
"""

_CALENDAR_MD = """\
<!-- GENERATED by the fixture calendar builder; do not hand-edit. -->
# Interview calendar (synthetic)

| when | what | source |
|------|------|--------|
| day 3 09:00 | screen | me/applications/6_drafted/example-role/meta.yaml |
| day 5 14:00 | onsite | me/applications/6_drafted/example-role/meta.yaml |
"""

_CALENDAR_DIRTY_ROW = (
    "| day 8 11:00 | debrief | me/applications/6_drafted/example-role/meta.yaml |\n"
)

_IGNORED_SOURCE = """\
synthetic machine-local cache
regenerated by the toolkit; retained at the source on every reconciliation
"""

_IGNORED_DESTINATION_OCCUPANT = """\
synthetic machine-local cache written by an EARLIER run
different bytes on purpose: a non-overwriting copy must refuse this destination
"""

# The candidate content, relative to the layout root (``me/`` before the refactor,
# ``person/`` after it). One entry per file; the calendar is last because it is the
# only one whose bytes the refactor rewrites.
_LAYOUT_FILES: tuple[tuple[str, str], ...] = (
    ("profile.md", _PROFILE_MD),
    ("notes/journal.md", _JOURNAL_MD),
    ("applications/6_drafted/example-role/meta.yaml", _META_YAML),
    ("generated/calendar.md", _CALENDAR_MD),
)

# Files whose bytes carry the layout root and are therefore rewritten, not merely
# moved, by the refactor commit. Everything else must rename at 100% similarity.
_PATH_CARRYING_FILES = ("generated/calendar.md",)

OLD_ROOT = "me"
NEW_ROOT = "person"

IGNORED_REL = "local-cache/scratch.txt"
GENERATED_REL = "generated/calendar.md"


def rewrite_layout_paths(text: str) -> str:
    """The refactor commit's ONLY content transformation: ``me/`` → ``person/``.

    Exported because the path-only claim is a property two readers must agree on:
    the generator that creates the delta, and the test that proves it is nothing
    more than this.
    """
    return text.replace(f"{OLD_ROOT}/", f"{NEW_ROOT}/")


# ── git plumbing ─────────────────────────────────────────────────────────────

_GIT_CONFIG_FLAGS: tuple[str, ...] = (
    "-c", "core.autocrlf=false",
    "-c", "core.safecrlf=false",
    "-c", "commit.gpgsign=false",
    "-c", "tag.gpgsign=false",
    "-c", "gc.auto=0",
    "-c", "core.fsmonitor=false",
    "-c", "advice.detachedHead=false",
    # Honoured by git >= 2.29 and silently ignored by older git, which is exactly
    # what is wanted: the flag form --object-format does not exist before 2.29.
    "-c", "init.defaultObjectFormat=sha1",
    "-c", "init.defaultBranch=main",
)


@dataclass
class _Git:
    """A git runner with a MINIMAL, fully-specified environment.

    The environment is built, not inherited. That is the whole determinism story:
    an operator's ``~/.gitconfig``, ``GIT_CONFIG_GLOBAL``, ``GIT_DIR``,
    ``GIT_AUTHOR_DATE``, locale or timezone cannot reach the fixture, and the
    isolation works identically on git 2.23 (no ``GIT_CONFIG_GLOBAL`` support) and
    on git 2.4x.
    """

    home: Path
    template: Path
    env: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "xdg"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,   # git >= 2.32
            "GIT_CONFIG_SYSTEM": os.devnull,   # git >= 2.32
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": FIXTURE_ACTOR_NAME,
            "GIT_AUTHOR_EMAIL": FIXTURE_ACTOR_EMAIL,
            "GIT_COMMITTER_NAME": FIXTURE_ACTOR_NAME,
            "GIT_COMMITTER_EMAIL": FIXTURE_ACTOR_EMAIL,
            "TZ": "UTC",
            "LC_ALL": "C",
            "LANG": "C",
        }
        # Windows' git needs SYSTEMROOT to resolve DLLs; harmless elsewhere.
        for passthrough in ("SYSTEMROOT", "SystemRoot", "COMSPEC"):
            if passthrough in os.environ:
                self.env[passthrough] = os.environ[passthrough]

    def run(self, cwd: Path, *args: str, date: str | None = None) -> str:
        env = dict(self.env)
        if date is not None:
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        proc = subprocess.run(
            ("git", *_GIT_CONFIG_FLAGS, *args),
            cwd=str(cwd), env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise FixtureError(
                f"git {' '.join(args)} failed in {cwd} "
                f"(exit {proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout

    def init(self, path: Path, *, bare: bool = False) -> None:
        path.mkdir(parents=True, exist_ok=True)
        args = ["init", "--quiet", f"--template={self.template}"]
        if bare:
            args.append("--bare")
        args.append(".")
        self.run(path, *args)
        # --initial-branch landed in git 2.28; this works on every version.
        self.run(path, "symbolic-ref", "HEAD", "refs/heads/main")

    def commit(self, repo: Path, message: str, date: str) -> str:
        self.run(repo, "add", "-A", ".")
        self.run(repo, "commit", "--quiet", "-m", message, date=date)
        return self.run(repo, "rev-parse", "HEAD").strip()


# ── destination guard ────────────────────────────────────────────────────────

def _git_ignores(path: Path) -> bool:
    """True when THIS checkout's git ignores ``path``.

    Fail-closed: any git failure reads as "not ignored", so a destination is
    refused rather than written to on an unexpected error.
    """
    proc = subprocess.run(
        ("git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--", str(path)),
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def resolve_destination(out: str | Path, *, repo_root: Path | None = None) -> Path:
    """The absolute build destination, or raise :class:`FixtureError`.

    A fixture is two git repositories with a dirty working tree. Building one into
    the tracked tree would be unreviewable at best and, with a mistyped path,
    could land inside the real ``private/`` overlay — which agents may never write
    to and never delete from. So: anywhere OUTSIDE this checkout is fine, and
    inside it only the git-ignored scratch roots are, confirmed twice (an explicit
    allowlist AND ``git check-ignore``).
    """
    root = (repo_root or REPO_ROOT).resolve()
    dest = Path(out).expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    dest = Path(os.path.abspath(dest))

    try:
        rel = dest.relative_to(root)
    except ValueError:
        return dest                      # outside the checkout entirely

    if rel == Path("."):
        raise FixtureError(
            f"refusing to build into the repository root itself ({dest})")
    if rel.parts[0] not in _ALLOWED_DEST_ROOTS:
        allowed = "/, ".join(_ALLOWED_DEST_ROOTS)
        raise FixtureError(
            f"refusing to build into the tracked tree: {rel.as_posix()} is inside "
            f"this checkout but not under {allowed}/ — build outside the repo, or "
            f"under one of those git-ignored scratch roots")
    if not _git_ignores(dest):
        raise FixtureError(
            f"refusing to build into {rel.as_posix()}: git does not ignore it, so "
            f"the fixture would show up as untracked content in this checkout")
    return dest


def _prepare_destination(dest: Path, *, force: bool) -> None:
    if not dest.exists():
        dest.mkdir(parents=True)
        return
    if not dest.is_dir():
        raise FixtureError(f"destination exists and is not a directory: {dest}")
    entries = [p for p in dest.iterdir() if p.name != ".DS_Store"]
    if not entries:
        return
    if not force:
        raise FixtureError(
            f"destination is not empty: {dest} — pass --force to replace a "
            f"previously generated fixture")
    manifest = dest / MANIFEST_NAME
    # --force is not "delete whatever is there". It replaces a tree this module
    # generated, identified by its own manifest, and refuses anything else.
    if not manifest.is_file():
        raise FixtureError(
            f"--force refuses {dest}: it is not empty and carries no "
            f"{MANIFEST_NAME}, so it was not generated by this module")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FixtureError(f"--force refuses {dest}: unreadable {MANIFEST_NAME} ({exc})")
    if data.get("generator") != Path(__file__).name:
        raise FixtureError(
            f"--force refuses {dest}: {MANIFEST_NAME} was not written by "
            f"{Path(__file__).name}")
    shutil.rmtree(dest)
    dest.mkdir(parents=True)


def _write_file(root: Path, rel: str, text: str) -> Path:
    """Write ``text`` at ``root/rel``, refusing anything that escapes ``root``.

    Every byte the generator writes goes through here. A ``..`` in a recipe path —
    or a caller-supplied one — is a refusal, not a write outside the fixture.
    """
    base = Path(os.path.abspath(root))
    path = Path(os.path.abspath(base / rel))
    if path != base and base not in path.parents:
        raise FixtureError(f"refusing to write outside the fixture: {rel!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── the recipe ───────────────────────────────────────────────────────────────

def _seed_layout(repo: Path, root: str) -> None:
    for rel, body in _LAYOUT_FILES:
        _write_file(repo, f"{root}/{rel}", body)


def _apply_layout_refactor(git: _Git, repo: Path) -> None:
    """``me/`` → ``person/``: a directory rename plus the path-only rewrites."""
    git.run(repo, "mv", OLD_ROOT, NEW_ROOT)
    for rel in _PATH_CARRYING_FILES:
        target = repo / NEW_ROOT / rel
        target.write_text(rewrite_layout_paths(target.read_text(encoding="utf-8")),
                          encoding="utf-8")


def _build_public(git: _Git, dest: Path) -> tuple[Path, dict[str, str]]:
    repo = dest / "public"
    remote = dest / "remotes" / "public.git"
    git.init(remote, bare=True)
    git.init(repo)

    _write_file(repo, ".gitignore", _PUBLIC_GITIGNORE)
    _write_file(repo, "README.md", _PUBLIC_README)
    _write_file(repo, "docs/roadmap/current-state.md", _ROADMAP_CURRENT)
    _write_file(repo, "docs/roadmap/desired-state.md", _ROADMAP_DESIRED)
    _write_file(repo, f"tasks/1_in-progress/{FIXTURE_TASK_ID}/task.md", _TASK_MD)
    _write_file(repo, "memory/decisions/fixture-layout-refactor.md", _MEMORY_DECISION)
    _write_file(repo, "message-queue/needs-agent/requests/.gitkeep", "")
    _write_file(repo, "message-queue/needs-human/decisions/.gitkeep", "")
    _write_file(repo, f"history/conversations/{FIXTURE_TASK_ID}/session-notes.md",
                _SESSION_NOTES)
    _seed_layout(repo, OLD_ROOT)
    seed = git.commit(repo, "Seed the synthetic public tree", _SEED_DATE)

    _apply_layout_refactor(git, repo)
    _write_file(repo, "docs/roadmap/current-state.md", _ROADMAP_CURRENT_AFTER)
    refactor = git.commit(repo, "Move candidate content from me/ to person/",
                          _REFACTOR_DATE)

    git.run(repo, "remote", "add", "origin", str(remote))
    git.run(repo, "push", "--quiet", "origin", "main")
    git.run(repo, "branch", "--set-upstream-to=origin/main", "main")
    return repo, {"seed": seed, "layout-refactor": refactor}


def _build_overlay(git: _Git, dest: Path, public: Path) -> tuple[Path, dict[str, str]]:
    repo = public / "private"
    remote = dest / "remotes" / "overlay.git"
    git.init(remote, bare=True)
    git.init(repo)

    _write_file(repo, ".gitignore", _OVERLAY_GITIGNORE)
    _write_file(repo, "README.md", _OVERLAY_README)
    _seed_layout(repo, OLD_ROOT)
    seed = git.commit(repo, "Seed the synthetic overlay tree", _SEED_DATE)

    _apply_layout_refactor(git, repo)
    refactor = git.commit(repo, "Move candidate content from me/ to person/",
                          _REFACTOR_DATE)

    git.run(repo, "remote", "add", "origin", str(remote))
    git.run(repo, "push", "--quiet", "origin", "main")
    git.run(repo, "branch", "--set-upstream-to=origin/main", "main")

    # origin/main stays at the refactor commit; the local branches go BACK to the
    # pre-refactor commit. That is the state a post-merge reconciliation finds:
    # the prerequisite is merged remotely, the local work predates it.
    git.run(repo, "reset", "--hard", "--quiet", seed)
    git.run(repo, "checkout", "--quiet", "-b", "codex/dirty")
    return repo, {"seed": seed, "layout-refactor": refactor}


def _apply_dirty_patch(overlay: Path, variant: str) -> None:
    """The small uncommitted patch, authored against the OLD paths."""
    journal = overlay / OLD_ROOT / "notes/journal.md"
    journal.write_text(journal.read_text(encoding="utf-8") + _JOURNAL_DIRTY_LINE,
                       encoding="utf-8")
    calendar = overlay / OLD_ROOT / GENERATED_REL
    calendar.write_text(calendar.read_text(encoding="utf-8") + _CALENDAR_DIRTY_ROW,
                        encoding="utf-8")
    _write_file(overlay, f"{OLD_ROOT}/{IGNORED_REL}", _IGNORED_SOURCE)
    if variant == "destination-exists":
        _write_file(overlay, f"{NEW_ROOT}/{IGNORED_REL}",
                    _IGNORED_DESTINATION_OCCUPANT)


def write_closeout_records(public: Path) -> list[str]:
    """Write the records the reconciler requires; return the relative paths.

    Shared with ``reconciliation_bench.py``'s closeout stage and with the test that
    proves the reconciler flips red → green, so the two can never disagree about
    what "the closeout records" are. ``memory/index.md`` is deliberately NOT written
    here: it is generated by ``reconcile.py --fix-index``, and hand-writing it would
    be the fixture asserting the reconciler's own output.
    """
    written = [f"history/conversations/{FIXTURE_TASK_ID}/handover.md"]
    _write_file(public, written[0], _HANDOVER)
    return written


@dataclass(frozen=True)
class FixtureManifest:
    fixture_version: str
    variant: str
    root: Path
    public: Path
    overlay: Path
    commits: dict[str, dict[str, str]]

    def as_dict(self) -> dict:
        return {
            "generator": Path(__file__).name,
            "fixture_version": self.fixture_version,
            "variant": self.variant,
            "root": str(self.root),
            "public": str(self.public),
            "overlay": str(self.overlay),
            "commits": self.commits,
        }


def build(out: str | Path, *, variant: str = DEFAULT_VARIANT,
          force: bool = False) -> FixtureManifest:
    """Generate the fixture at ``out`` and return its manifest."""
    if variant not in VARIANTS:
        raise FixtureError(
            f"unknown variant {variant!r} — known: {', '.join(sorted(VARIANTS))}")
    dest = resolve_destination(out)
    _prepare_destination(dest, force=force)

    with tempfile.TemporaryDirectory(prefix="recon-fixture-git-") as scratch:
        home = Path(scratch) / "home"
        template = Path(scratch) / "template"
        home.mkdir()
        template.mkdir()
        git = _Git(home=home, template=template)

        public, public_commits = _build_public(git, dest)
        overlay, overlay_commits = _build_overlay(git, dest, public)
        _apply_dirty_patch(overlay, variant)
        if variant == "closeout-done":
            write_closeout_records(public)

    manifest = FixtureManifest(
        fixture_version=FIXTURE_VERSION,
        variant=variant,
        root=dest,
        public=public,
        overlay=overlay,
        commits={"public": public_commits, "overlay": overlay_commits},
    )
    (dest / MANIFEST_NAME).write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


# ── verification ─────────────────────────────────────────────────────────────

def read_manifest(root: Path) -> FixtureManifest:
    data = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    return FixtureManifest(
        fixture_version=data["fixture_version"],
        variant=data["variant"],
        root=Path(data["root"]),
        public=Path(data["public"]),
        overlay=Path(data["overlay"]),
        commits=data["commits"],
    )


def _rev(repo: Path, ref: str) -> str:
    proc = subprocess.run(("git", "-C", str(repo), "rev-parse", ref),
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def verify(root: Path) -> list[str]:
    """Structural + pinned-SHA findings for a built fixture. Empty list ⇒ clean."""
    findings: list[str] = []
    root = Path(root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_NAME} missing — {root} is not a generated fixture"]
    try:
        manifest = read_manifest(root)
    except (OSError, ValueError, KeyError) as exc:
        return [f"{MANIFEST_NAME} unreadable: {exc}"]

    if manifest.fixture_version != FIXTURE_VERSION:
        findings.append(
            f"fixture_version {manifest.fixture_version!r} != {FIXTURE_VERSION!r} "
            f"— rebuild, and treat rows recorded against the old version as "
            f"incomparable")

    public, overlay = root / "public", root / "public" / "private"
    # Which ref carries which commit is itself part of the fixture's contract: the
    # public repo is AT the refactor (its parent is the seed), the overlay's local
    # branch is still ON the seed while its origin/main carries the refactor.
    refs = {
        "public": {"seed": "main~1", "layout-refactor": "main"},
        "overlay": {"seed": "codex/dirty", "layout-refactor": "origin/main"},
    }
    for label, repo in (("public", public), ("overlay", overlay)):
        if not (repo / ".git").exists():
            findings.append(f"{label}: no git repository at {repo}")
            continue
        head_of = {name: _rev(repo, ref) for name, ref in refs[label].items()}
        for name, pinned in PINNED_SHAS[label].items():
            actual = head_of.get(name, "")
            if pinned == "PENDING":
                findings.append(
                    f"{label}/{name}: PINNED_SHAS is unfilled — record {actual}")
            elif actual != pinned:
                findings.append(
                    f"{label}/{name}: {actual or '<missing>'} != pinned {pinned}")

    findings.extend(_structural_findings(public, overlay, manifest.variant))
    return findings


def _structural_findings(public: Path, overlay: Path, variant: str) -> list[str]:
    findings: list[str] = []
    if not (public / NEW_ROOT / "profile.md").is_file():
        findings.append("public: person/profile.md missing — refactor not applied")
    if (public / OLD_ROOT).exists():
        findings.append("public: me/ still present — refactor not applied")
    if "private/" not in (public / ".gitignore").read_text(encoding="utf-8"):
        findings.append("public: .gitignore does not ignore private/")
    if not (overlay / OLD_ROOT / "notes/journal.md").is_file():
        findings.append("overlay: working tree is not at the pre-refactor layout")
    if not (overlay / OLD_ROOT / IGNORED_REL).is_file():
        findings.append(f"overlay: ignored source {OLD_ROOT}/{IGNORED_REL} missing")
    destination = overlay / NEW_ROOT / IGNORED_REL
    if variant == "destination-exists" and not destination.is_file():
        findings.append(
            f"overlay: variant destination-exists but {NEW_ROOT}/{IGNORED_REL} "
            f"is absent")
    if variant != "destination-exists" and destination.exists():
        findings.append(
            f"overlay: {NEW_ROOT}/{IGNORED_REL} exists in variant {variant}")
    return findings


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_manifest(manifest: FixtureManifest, as_json: bool) -> None:
    if as_json:
        print(json.dumps(manifest.as_dict(), indent=2, sort_keys=True))
        return
    print(f"fixture {manifest.fixture_version} variant {manifest.variant}")
    print(f"  root     {manifest.root}")
    print(f"  public   {manifest.public}")
    print(f"  overlay  {manifest.overlay}")
    for repo in sorted(manifest.commits):
        for name in sorted(manifest.commits[repo]):
            print(f"  {repo}/{name:<16} {manifest.commits[repo][name]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="generate the fixture")
    p_build.add_argument("--out", required=True,
                         help="destination directory (outside this checkout, or "
                              "under local/ or logs/)")
    p_build.add_argument("--variant", default=DEFAULT_VARIANT, choices=sorted(VARIANTS))
    p_build.add_argument("--force", action="store_true",
                         help="replace a previously generated fixture at --out")
    p_build.add_argument("--json", action="store_true", help="machine-readable manifest")

    p_verify = sub.add_parser("verify", help="check a built fixture against the pins")
    p_verify.add_argument("--out", default=None,
                          help="fixture root to check; omitted ⇒ build a throwaway "
                               "one first")
    p_verify.add_argument("--variant", default=DEFAULT_VARIANT, choices=sorted(VARIANTS))

    p_list = sub.add_parser("list-variants", help="name every variant")
    p_list.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "list-variants":
        if args.json:
            print(json.dumps({"fixture_version": FIXTURE_VERSION,
                              "default": DEFAULT_VARIANT,
                              "variants": VARIANTS}, indent=2, sort_keys=True))
        else:
            print(f"fixture {FIXTURE_VERSION} (default variant: {DEFAULT_VARIANT})")
            for name in sorted(VARIANTS):
                print(f"  {name}\n      {VARIANTS[name]}")
        return 0

    try:
        if args.command == "build":
            manifest = build(args.out, variant=args.variant, force=args.force)
            _print_manifest(manifest, args.json)
            return 0

        if args.out is not None:
            findings = verify(Path(args.out).expanduser().resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="recon-fixture-verify-") as tmp:
                build(Path(tmp) / "fixture", variant=args.variant)
                findings = verify(Path(tmp) / "fixture")
    except FixtureError as exc:
        print(f"reconciliation_fixture: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"reconciliation_fixture: {exc}", file=sys.stderr)
        return 2

    if findings:
        print(f"reconciliation_fixture: {len(findings)} finding(s)")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"reconciliation_fixture: OK (fixture {FIXTURE_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
