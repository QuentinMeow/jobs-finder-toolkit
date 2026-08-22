"""Real temporary Git repositories for the workspace suite — nothing is mocked.

Every fact this suite asserts is a fact about GIT, so a mocked ``git`` would only
prove that the mock agrees with the code that wrote it. The measured failures
this suite exists to prevent — ``git branch --merged`` missing squash-merges,
``git patch-id`` ignoring whitespace, a locked worktree whose directory is gone
never reporting ``prunable`` — are all behaviours no reasonable mock would have
reproduced, because nobody would have written the mock that way.

THE ENVIRONMENT IS PINNED, and that is not a nicety. Without
``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM``/``HOME`` the developer's own
``~/.gitconfig`` decides ``gc.pruneExpire``, ``core.hooksPath``, commit signing
and ``merge.conflictStyle`` inside these fixtures, so the suite passes on one
machine and fails on another for reasons no diff explains. ``status.py`` runs
git as a SUBPROCESS that inherits ``os.environ``, so the pinning has to happen
in the process environment, not only in the arguments this module passes.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

# The fixture's "now". Captured once so a run's ages are arithmetic rather than
# a race with the clock, and anchored to the REAL clock because a worktree's
# mtime is real: a hard-coded epoch would put every commit months behind files
# the fixture writes this second, and every age would be negative.
FIXED_EPOCH = int(time.time())
DAY = 86400


def backdate(path: Path, epoch: int) -> None:
    """Age a worktree's own files, so "nobody has touched this" is testable."""
    for candidate in (path, path / ".git"):
        try:
            os.utime(candidate, (epoch, epoch))
        except OSError:
            continue


def pinned_env(home: Path, epoch: int | None = None) -> dict[str, str]:
    """The environment every fixture command runs under."""
    moment = FIXED_EPOCH if epoch is None else epoch
    stamp = f"{moment} +0000"
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_AUTHOR_NAME": "Workspace Test",
        "GIT_AUTHOR_EMAIL": "workspace@example.invalid",
        "GIT_COMMITTER_NAME": "Workspace Test",
        "GIT_COMMITTER_EMAIL": "workspace@example.invalid",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "true",
        # A fixture must never reach the network, whatever a ref name looks like.
        "GIT_ALLOW_PROTOCOL": "file",
    }


class GitTestCase(unittest.TestCase):
    """Base case: a scratch directory, a pinned environment, and a git helper."""

    def setUp(self) -> None:  # noqa: D102
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        self.home = self.scratch / "home"
        self.home.mkdir()
        self.pin_environment()

    def pin_environment(self, epoch: int | None = None) -> None:
        """Overlay the pinned variables onto ``os.environ`` for this test."""
        previous = {key: os.environ.get(key) for key in pinned_env(self.home, epoch)}

        def restore() -> None:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        os.environ.update(pinned_env(self.home, epoch))

    def git(self, repo: Path, *args: str, epoch: int | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if epoch is not None:
            env.update({"GIT_AUTHOR_DATE": f"{epoch} +0000",
                        "GIT_COMMITTER_DATE": f"{epoch} +0000"})
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", check=False, env=env,
        )
        if check and result.returncode:
            raise AssertionError(
                f"git {' '.join(args)} failed ({result.returncode}):\n{result.stderr}")
        return result

    def out(self, repo: Path, *args: str, **kwargs) -> str:
        return self.git(repo, *args, **kwargs).stdout.strip()

    def commit(self, repo: Path, message: str, *, epoch: int | None = None) -> str:
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message, epoch=epoch)
        return self.out(repo, "rev-parse", "HEAD")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_binary(path: Path, marker: bytes) -> None:
    """A file git will auto-detect as BINARY — the NUL byte is the whole trick.

    Git looks for a NUL in the first 8000 bytes and, finding one, refuses to
    merge the file at all. The real repository has 22 tracked files of this
    shape (DOCX and PDF resumes, JPGs, ``.json.zst`` blobs) and the suite had
    none, which is how the keep-ours merge trap survived 114 passing tests.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89FIXTURE\x00\x01\x02" + marker + b"\x00\n")


def add_toolkit_markers(root: Path) -> None:
    """The four files ``status.validate_toolkit_root`` insists on."""
    write(root / "AGENTS.md", "fixture\n")
    write(root / "config.example.yaml", "fixture: true\n")
    write(root / "automation" / "shared" / "config.py", "# fixture\n")
    write(root / "skills" / "job-search" / "SKILL.md", "# fixture\n")


# ── the merge-shape matrix ───────────────────────────────────────────────────
#
# UNIQUE_WORK is the invariant. Every branch listed there holds content that
# exists nowhere else, so reporting any of them ``merged`` is a data-loss
# answer: the cleanup planner would propose deleting work that cannot be
# recovered from main. CONTAINED is the other half — every branch whose content
# main already has, including the two shapes that surprise people (a
# merged-then-reverted branch and an empty commit).
UNIQUE_WORK = (
    "open-work",            # ordinary unmerged branch
    "partially-merged",     # one of two commits cherry-picked
    "ws-variant",           # the whitespace trap: patch-id says merged, it is not
    "binary-conflict",      # the KEEP-OURS trap: merge-tree hands back the base tree
    "dirty-work",           # committed work plus uncommitted edits
    "locked-work",          # a live, locked worktree
)
CONTAINED = (
    "true-merge",           # git branch --merged finds this one
    "squash-merge",         # git branch --merged MISSES this one
    "rebase-copy",          # cherry-picked onto main under a new sha
    "merged-then-revert",   # content still reachable in main's history
    "empty-commit",         # no content at all
    "untracked-work",       # merged branch, untracked files in its worktree
)


_SHARED: dict = {}


def fixture_fingerprint(case: GitTestCase, root: Path) -> str:
    """Every ref, every worktree registration, every branch description."""
    return "\n".join((
        case.out(root, "for-each-ref", "--format=%(refname) %(objectname)"),
        case.out(root, "worktree", "list", "--porcelain"),
        case.out(root, "config", "-z", "--get-regexp",
                 r"^branch\..*\.description$", check=False),
    ))


def shared_shapes(case: GitTestCase) -> tuple[Path, dict]:
    """The merge-shape repository, built ONCE per process, for READ-ONLY tests."""
    if "root" not in _SHARED:
        holder = tempfile.TemporaryDirectory()
        atexit.register(holder.cleanup)
        root = Path(holder.name) / "toolkit"
        _SHARED.update(holder=holder, root=root,
                       facts=build_merge_shapes(case, root))
    return _SHARED["root"], _SHARED["facts"]


class SharedShapesTestCase(GitTestCase):
    """Read-only tests over one shared fixture.

    Building the matrix costs about a second of git subprocesses, and twenty-odd
    read-only tests rebuilding an identical repository is half a minute of CI
    spent proving nothing. The risk of sharing is a test that mutates and
    silently poisons its neighbours, so the fixture's fingerprint is compared
    after every test: a mutation fails loudly, here, instead of somewhere else.
    """

    def setUp(self) -> None:
        super().setUp()
        self.root, self.facts = shared_shapes(self)
        before = fixture_fingerprint(self, self.root)
        self.addCleanup(self._assert_shared_fixture_unchanged, before)

    def _assert_shared_fixture_unchanged(self, before: str) -> None:
        self.assertEqual(
            fixture_fingerprint(self, self.root), before,
            "this test mutated the SHARED fixture; give it its own repository "
            "by subclassing GitTestCase and calling build_merge_shapes()")


def add_origin(case: GitTestCase, root: Path) -> Path:
    """A local bare repository standing in for ``origin``.

    A real remote, not a stub: ``git fetch --prune origin`` has to actually run
    for the planner's one network-authorising flag to be tested at all, and
    "every commit exists on a remote" has to be answerable by
    ``git rev-list --not --remotes`` rather than by a fixture's promise. It is a
    directory on disk, so the suite still never touches the network.
    """
    origin = root.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                   check=True, env=dict(os.environ))
    case.git(root, "remote", "add", "origin", str(origin))
    case.git(root, "push", "-q", "-u", "origin", "main")
    case.git(root, "fetch", "-q", "origin")
    return origin


def build_merge_shapes(case: GitTestCase, root: Path) -> dict:
    """Create every merge shape and worktree shape in one repository.

    Returns the fixture's facts: branch tips, worktree paths, and the two
    classification sets above.
    """
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   env=dict(os.environ))
    add_toolkit_markers(root)
    write(root / "seed.txt", "seed\n")
    case.commit(root, "base commit", epoch=FIXED_EPOCH - 30 * DAY)
    base = case.out(root, "rev-parse", "HEAD")
    facts: dict = {"base": base, "worktrees": {}, "unique": list(UNIQUE_WORK),
                   "contained": list(CONTAINED)}

    def branch_from_main(name: str) -> None:
        case.git(root, "switch", "-q", "-c", name, "main")

    # 1. true merge — the only shape `git branch --merged` reports.
    branch_from_main("true-merge")
    write(root / "true.txt", "true merge\n")
    case.commit(root, "true-merge: add true.txt", epoch=FIXED_EPOCH - 20 * DAY)
    case.git(root, "switch", "-q", "main")
    case.git(root, "merge", "-q", "--no-ff", "true-merge", "-m", "Merge true-merge",
             epoch=FIXED_EPOCH - 20 * DAY)

    # 2. squash merge — the measured root cause of branch accumulation.
    branch_from_main("squash-merge")
    write(root / "squash.txt", "squash merge\n")
    case.commit(root, "squash-merge: add squash.txt", epoch=FIXED_EPOCH - 19 * DAY)
    case.git(root, "switch", "-q", "main")
    case.git(root, "merge", "-q", "--squash", "squash-merge")
    case.commit(root, "squash-merge landed as one commit", epoch=FIXED_EPOCH - 19 * DAY)

    # 3. rebase / cherry-pick — same content, different sha.
    branch_from_main("rebase-copy")
    write(root / "rebased.txt", "rebased\n")
    picked = case.commit(root, "rebase-copy: add rebased.txt",
                         epoch=FIXED_EPOCH - 18 * DAY)
    case.git(root, "switch", "-q", "main")
    case.git(root, "cherry-pick", picked, epoch=FIXED_EPOCH - 18 * DAY)

    # 4. open work — plainly unmerged.
    branch_from_main("open-work")
    write(root / "open.txt", "open work\n")
    case.commit(root, "open-work: start the feature", epoch=FIXED_EPOCH - 3 * DAY)
    write(root / "open2.txt", "more open work\n")
    case.commit(root, "open-work: keep going", epoch=FIXED_EPOCH - 3 * DAY)

    # 5. partially merged — main took the first commit, not the second.
    case.git(root, "switch", "-q", "main")
    branch_from_main("partially-merged")
    write(root / "part1.txt", "first half\n")
    first = case.commit(root, "partially-merged: first half",
                        epoch=FIXED_EPOCH - 10 * DAY)
    write(root / "part2.txt", "second half\n")
    case.commit(root, "partially-merged: second half", epoch=FIXED_EPOCH - 10 * DAY)
    case.git(root, "switch", "-q", "main")
    case.git(root, "cherry-pick", first, epoch=FIXED_EPOCH - 10 * DAY)

    # 6. the whitespace trap (V-B). main and the branch add the SAME path with
    #    the same code at different indentation. `git patch-id` ignores
    #    whitespace, so `git cherry` reports the branch as already upstream —
    #    a false MERGED on genuinely unique content.
    branch_from_main("ws-variant")
    write(root / "indent.py", "def f():\n        return 1\n")
    case.commit(root, "ws-variant: eight-space body", epoch=FIXED_EPOCH - 9 * DAY)
    case.git(root, "switch", "-q", "main")
    write(root / "indent.py", "def f():\n  return 1\n")
    case.commit(root, "main: two-space body", epoch=FIXED_EPOCH - 9 * DAY)

    # 7. merged then reverted — content is still reachable in main's history.
    branch_from_main("merged-then-revert")
    write(root / "reverted.txt", "later reverted\n")
    case.commit(root, "merged-then-revert: add reverted.txt",
                epoch=FIXED_EPOCH - 8 * DAY)
    case.git(root, "switch", "-q", "main")
    case.git(root, "merge", "-q", "--no-ff", "merged-then-revert",
             "-m", "Merge merged-then-revert", epoch=FIXED_EPOCH - 8 * DAY)
    merge_commit = case.out(root, "rev-parse", "HEAD")
    case.git(root, "revert", "--no-edit", "-m", "1", merge_commit,
             epoch=FIXED_EPOCH - 8 * DAY)

    # 8. an empty commit — a message and nothing else.
    branch_from_main("empty-commit")
    case.git(root, "commit", "-q", "--allow-empty", "-m", "empty-commit: nothing yet",
             epoch=FIXED_EPOCH - 7 * DAY)
    case.git(root, "switch", "-q", "main")

    # 9. the KEEP-OURS trap. Both sides edit a file git treats as BINARY. Git
    #    cannot merge it, so it resolves the conflict by keeping OURS — and the
    #    tree `merge-tree --write-tree` hands back is then BYTE-IDENTICAL to
    #    main's own tree, on exit 1. A probe that accepts exit 1 and compares
    #    trees therefore reports `merged` for a branch whose content exists
    #    nowhere in main: the one false-merged direction that loses work.
    write_binary(root / "asset.bin", b"main-baseline")
    case.commit(root, "main: track a binary asset", epoch=FIXED_EPOCH - 6 * DAY)
    branch_from_main("binary-conflict")
    write_binary(root / "asset.bin", b"branch-only-work")
    case.commit(root, "binary-conflict: the branch re-cuts the asset",
                epoch=FIXED_EPOCH - 6 * DAY)
    case.git(root, "switch", "-q", "main")
    write_binary(root / "asset.bin", b"main-went-elsewhere")
    case.commit(root, "main: the asset moved on too", epoch=FIXED_EPOCH - 6 * DAY)

    # ── worktree shapes ──────────────────────────────────────────────────────
    holder = root.parent / "worktrees"
    holder.mkdir(exist_ok=True)

    detached = holder / "detached"
    case.git(root, "worktree", "add", "-q", "--detach", str(detached), "main")
    facts["worktrees"]["detached"] = detached

    locked = holder / "locked-live"
    case.git(root, "worktree", "add", "-q", "-b", "locked-work", str(locked), "main")
    write(locked / "locked.txt", "work in a locked worktree\n")
    case.git(locked, "add", "-A")
    case.git(locked, "commit", "-q", "-m", "locked-work: unique work",
             epoch=FIXED_EPOCH - 40 * DAY)
    case.git(root, "worktree", "lock", "--reason", "agent session holds this",
             str(locked))
    # Old on every clock: an old tip AND old files. Only the lock can keep it
    # out of `stale`, which is exactly what the state rule promises.
    backdate(locked, FIXED_EPOCH - 40 * DAY)
    facts["worktrees"]["locked-live"] = locked

    dirty = holder / "dirty"
    case.git(root, "worktree", "add", "-q", "-b", "dirty-work", str(dirty), "main")
    write(dirty / "dirty.txt", "committed here\n")
    case.git(dirty, "add", "-A")
    case.git(dirty, "commit", "-q", "-m", "dirty-work: committed half",
             epoch=FIXED_EPOCH - 2 * DAY)
    write(dirty / "seed.txt", "edited but not committed\n")
    facts["worktrees"]["dirty"] = dirty

    untracked = holder / "untracked"
    case.git(root, "worktree", "add", "-q", "-b", "untracked-work", str(untracked),
             "main")
    write(untracked / "scratch.md", "untracked only — git can recover none of this\n")
    facts["worktrees"]["untracked"] = untracked

    prunable = holder / "prunable"
    case.git(root, "worktree", "add", "-q", "-b", "prunable-work", str(prunable),
             "main")
    shutil.rmtree(prunable)
    facts["worktrees"]["prunable"] = prunable

    locked_gone = holder / "locked-gone"
    case.git(root, "worktree", "add", "-q", "-b", "locked-gone-work",
             str(locked_gone), "main")
    case.git(root, "worktree", "lock", "--reason", "locked before the directory went",
             str(locked_gone))
    shutil.rmtree(locked_gone)
    facts["worktrees"]["locked-gone"] = locked_gone

    facts["origin"] = add_origin(case, root)
    facts["tips"] = {
        line.split(" ", 1)[1]: line.split(" ", 1)[0]
        for line in case.out(
            root, "for-each-ref", "--format=%(objectname) %(refname:short)",
            "refs/heads").splitlines()
        if line
    }
    return facts


# ── the private overlay ──────────────────────────────────────────────────────
#
# ONE FABRICATED TOKEN, EVERYWHERE THE REAL OVERLAY WOULD CARRY AN EMPLOYER
# NAME. The real overlay is a separate repository holding the owner's identity,
# so no test may read it; instead this builds a repository shaped exactly like
# it and stamps a nonsense word into every field the auditor caught leaking —
# branch name, commit subject, branch description, tracked path, changed path,
# worktree path and remote URL. A privacy test then asserts one thing: that
# word appears nowhere in any of the dashboard's outputs.
OVERLAY_SECRET = "zzyzxrobotics"


def build_private_overlay(case: GitTestCase, root: Path,
                          secret: str = OVERLAY_SECRET) -> dict:
    """A stand-in for ``private/``: same shapes, fabricated contents."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   env=dict(os.environ))
    stage = f"applications/2_interviewing/{secret}"
    write(root / stage / "meta.yaml", f"company: {secret}\nstatus: interviewing\n")
    case.commit(root, "seed the overlay", epoch=FIXED_EPOCH - 30 * DAY)
    # A remote-tracking ref without a remote to fetch from: the base ref has to
    # exist for `merged` to mean anything, and the suite never touches a network.
    case.git(root, "remote", "add", "origin",
             f"git@github.com:{secret}-team/overlay.git")
    case.git(root, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    case.git(root, "config", "branch.main.remote", "origin")
    case.git(root, "config", "branch.main.merge", "refs/heads/main")

    # A CONVENTIONAL prefix (`codex/`) with an employer name behind it, and a
    # branch with no conventional prefix at all — the two halves of the naming
    # rule the redaction has to get right.
    conventional = f"codex/{secret}-onsite-loop"
    case.git(root, "switch", "-q", "-c", conventional, "main")
    write(root / stage / "prep.md", f"loop plan for {secret}\n")
    case.commit(root, f"prep the {secret} onsite loop", epoch=FIXED_EPOCH - 3 * DAY)
    case.git(root, "config", f"branch.{conventional}.description",
             f"drive the {secret} loop to an offer\nnext: send the thank-you note")

    bare_named = f"{secret}-negotiation"
    case.git(root, "switch", "-q", "-c", bare_named, "main")
    write(root / stage / "offer.md", f"numbers from {secret}\n")
    case.commit(root, f"log the {secret} numbers", epoch=FIXED_EPOCH - 2 * DAY)
    case.git(root, "switch", "-q", "main")

    # A linked worktree whose PATH carries the name, and an uncommitted change
    # whose PATH carries it too — `-v` prints both for the public repo.
    linked = root.parent / f"{secret}-worktree"
    case.git(root, "worktree", "add", "-q", "--detach", str(linked), "main")
    write(root / stage / "notes.md", f"call notes for {secret}\n")

    # A LOCK REASON and a PRUNABLE reason: free-text git repeats back verbatim,
    # and `-v` prints both for the public repo.
    locked = root.parent / f"{secret}-locked"
    case.git(root, "worktree", "add", "-q", "--detach", str(locked), "main")
    case.git(root, "worktree", "lock", "--reason",
             f"holding the {secret} loop open", str(locked))
    gone = root.parent / f"{secret}-gone"
    case.git(root, "worktree", "add", "-q", "--detach", str(gone), "main")
    shutil.rmtree(gone)
    return {"secret": secret, "conventional": conventional,
            "bare_named": bare_named, "linked": linked, "locked": locked,
            "gone": gone, "stage": stage}
