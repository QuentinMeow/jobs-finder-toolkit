#!/usr/bin/env python3
"""Classify every dirty working-tree path against a merged layout change.

NOT ``automation/reconcile/reconcile.py``: that is the process-layer schema gate
wired into pre-commit and CI.  This module reads Git object state and nothing
else — it never writes the index, the worktree, or a ref.

The question it answers, once per dirty path: *did the branch that just merged
move this file, and if so did it also change what is inside it?*  The evidence is
``git diff -M100%`` — an exact-blob rename, which is a proof rather than a score
— plus a residual check that mechanises "the upstream delta was path-only".

Verdicts (first match wins, see ``classify_entries``):

``unsafe``                    a name, gitlink, or symlink the planner must refuse.
``ignored``                   git-ignored; it never replays, it is copied or left.
``unchanged``                 the worktree blob equals the fork-point blob.
``renamed-by-merged-layout``  moved upstream, contents untouched — replays by
                              relocation alone.
``content-divergent``         moved upstream AND the contents differ.  The
                              link-rebase residual says whether the upstream delta
                              was provably path-only; the verdict does NOT change
                              either way, because a proof is an input to the
                              agent's judgement, never a substitute for it.
``unknown``                   no rename evidence and no other explanation.  This
                              is a REFUSAL upstream, not a warning: an
                              unrecognised file in a tree about to be rebased is
                              exactly the shape of "an ignored source someone
                              assumes is disposable".

The NUL-field walker for ``git diff --name-status`` is IMPORTED from
``automation/ci/classify_changes.py`` rather than re-implemented, so a malformed
Git response raises ``ClassificationError`` and becomes a refusal instead of a
silent misparse.

Tests: ``.venv/bin/python -m unittest discover automation/cutover/tests``
"""
from __future__ import annotations

import difflib
import hashlib
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


def _find_repo_root(start: Path) -> Path:
    """The project root ``start`` belongs to, found by walking UP.

    A fixed ``parents[N]`` encodes this file's depth and breaks the moment the
    folder moves.  ``.git`` is tested with ``exists()`` because a git WORKTREE's
    ``.git`` is a FILE; ``config.example.yaml`` is the fallback marker for a
    ``.git``-less export.  Local twin of ``automation/shared/config.py``'s walk.
    """
    for marker in (".git", "config.example.yaml"):
        for parent in (start, *start.parents):
            if (parent / marker).exists():
                return parent
    return start


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)

_CI_DIR = REPO_ROOT / "automation" / "ci"
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))
import classify_changes  # noqa: E402  (import after sys.path bootstrap, by design)

ClassificationError = classify_changes.ClassificationError
parse_name_status = classify_changes.parse_name_status


# ── verdict / action / residual domains ──────────────────────────────────────
VERDICT_UNSAFE = "unsafe"
VERDICT_IGNORED = "ignored"
VERDICT_UNCHANGED = "unchanged"
VERDICT_RENAMED = "renamed-by-merged-layout"
VERDICT_CONTENT_DIVERGENT = "content-divergent"
VERDICT_UNKNOWN = "unknown"
VERDICTS = (
    VERDICT_UNSAFE,
    VERDICT_IGNORED,
    VERDICT_UNCHANGED,
    VERDICT_RENAMED,
    VERDICT_CONTENT_DIVERGENT,
    VERDICT_UNKNOWN,
)

ACTION_NONE = "none"
ACTION_REPLAY = "replay"
ACTION_AGENT_RESOLVE = "agent-resolve"
ACTION_COPY = "copy"
ACTION_OWNER = "owner"
ACTIONS = (ACTION_NONE, ACTION_REPLAY, ACTION_AGENT_RESOLVE, ACTION_COPY, ACTION_OWNER)

RESIDUAL_EMPTY = "empty"
RESIDUAL_NON_EMPTY = "non-empty"
RESIDUAL_BINARY = "not-attempted:binary"
RESIDUAL_NA = "not-applicable"
RESIDUALS = (RESIDUAL_EMPTY, RESIDUAL_NON_EMPTY, RESIDUAL_BINARY, RESIDUAL_NA)

# Refusal codes this module can attach to a path.  The planner turns each into a
# ``blocking[]`` entry and exits 3; the path still appears in the inventory, so a
# refused plan is still a complete description of the state.
CODE_UNSAFE_PATH_NAME = "unsafe-path-name"
CODE_SUBMODULE_DIRTY = "submodule-dirty"
CODE_SYMLINK_ESCAPES = "symlink-escapes-repo"
CODE_IGNORED_CONFLICT = "ignored-destination-conflict"
CODE_UNKNOWN_DIRTY = "unknown-dirty-path"


# ── read-only Git plumbing ───────────────────────────────────────────────────
# Every invocation is an argv LIST through subprocess.run: no shell, no pipe, and
# the real returncode is read from CompletedProcess rather than from any shell
# variable.  The allowlist below is the structural half of the read-only promise:
# a future edit cannot reach a mutating subcommand without changing this set.
READ_ONLY_SUBCOMMANDS = frozenset({
    "cat-file",
    "check-ignore",
    "diff",
    "for-each-ref",
    "hash-object",
    "log",
    "ls-files",
    "merge-base",
    "remote",
    "rev-list",
    "rev-parse",
    "show-ref",
    "status",
    "worktree",
})
# Authorised separately by ``allow_fetch``: a fetch writes remote-tracking refs
# and nothing else, and only when the caller passed --fetch.
NETWORK_SUBCOMMANDS = frozenset({"fetch"})


class GitError(RuntimeError):
    """A Git invocation failed in a way the caller must not paper over."""


class ReadOnlyGit:
    """Read-only Git access to one repository root.

    ``hash-object`` is called WITHOUT ``-w``, so it computes an object id without
    writing to the object store.  ``--no-optional-locks`` keeps ``git status``
    from refreshing (and therefore rewriting) the index as a side effect.
    """

    def __init__(self, root: Path, *, allow_fetch: bool = False) -> None:
        self.root = Path(root)
        self.allow_fetch = allow_fetch

    # -- invocation ---------------------------------------------------------
    def _check_argv(self, args: Sequence[str]) -> None:
        if not args:
            raise GitError("empty git invocation")
        head = args[0]
        if head == "--version":
            return
        if head in NETWORK_SUBCOMMANDS:
            if not self.allow_fetch:
                raise GitError(f"git {head} requires --fetch authorisation")
            return
        if head not in READ_ONLY_SUBCOMMANDS:
            raise GitError(f"git {head} is not a read-only subcommand")
        if head == "hash-object" and "-w" in args:
            raise GitError("git hash-object -w would write to the object store")
        if head == "worktree" and (len(args) < 2 or args[1] != "list"):
            raise GitError("only `git worktree list` is read-only")
        if head == "remote" and len(args) > 1 and args[1] != "get-url":
            raise GitError("only `git remote` and `git remote get-url` are read-only")

    def run(self, *args: str, check: bool = True,
            stdin: bytes | None = None) -> subprocess.CompletedProcess:
        self._check_argv(args)
        try:
            completed = subprocess.run(
                ["git", "--no-optional-locks", *args],
                cwd=str(self.root),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:  # pragma: no cover - git missing is environmental
            raise GitError(f"could not execute git: {error}") from error
        if check and completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise GitError(
                f"git {' '.join(args)} exited {completed.returncode}"
                + (f": {detail}" if detail else "")
            )
        return completed

    # -- queries ------------------------------------------------------------
    def version(self) -> str:
        out = self.run("--version").stdout.decode("utf-8", "replace").strip()
        return out.split()[-1] if out else "unknown"

    def blob_oid(self, rev: str, path: str) -> str | None:
        """Object id of ``rev:path``, or None when it does not exist there."""
        completed = self.run("rev-parse", "--verify", "--quiet", f"{rev}:{path}",
                             check=False)
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("ascii", "replace").strip() or None

    def cat_blob(self, rev: str, path: str) -> bytes | None:
        completed = self.run("cat-file", "blob", f"{rev}:{path}", check=False)
        if completed.returncode != 0:
            return None
        return completed.stdout

    def hash_object(self, path: str) -> str | None:
        """Blob id of the WORKTREE file, computed without writing it (no ``-w``).

        Returns None for a symlink or a directory: ``hash-object`` would follow
        the link and hash the target's contents, which is not what Git stores, so
        the honest answer is "cannot compare" and the caller stays conservative.
        """
        absolute = self.root / path
        if absolute.is_symlink() or absolute.is_dir() or not absolute.exists():
            return None
        completed = self.run("hash-object", "--", path, check=False)
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("ascii", "replace").strip() or None

    def ignored(self, paths: Sequence[str]) -> set[str]:
        """The subset of ``paths`` git-ignores, in ONE batched read-only call.

        ``git check-ignore`` consults the index by default, so a TRACKED path is
        never reported as ignored — which is exactly the semantics the classifier
        needs.  Exit 0 means at least one path matched, 1 means none did; any
        other code is a real error and is raised rather than read as "none".
        """
        if not paths:
            return set()
        payload = b"".join(p.encode("utf-8") + b"\0" for p in paths)
        completed = self.run("check-ignore", "-z", "--stdin", check=False,
                             stdin=payload)
        if completed.returncode == 1:
            return set()
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise GitError(f"git check-ignore exited {completed.returncode}: {detail}")
        fields = [f for f in completed.stdout.split(b"\0") if f]
        return {f.decode("utf-8", "replace") for f in fields}


# ── git status --porcelain=v2 parsing ────────────────────────────────────────
@dataclass(frozen=True)
class BranchInfo:
    oid: str | None = None
    head: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None

    @property
    def detached(self) -> bool:
        return self.head == "(detached)"


@dataclass(frozen=True)
class StatusEntry:
    kind: str          # "1" | "2" | "u" | "?" | "!"
    xy: str            # two-char status field; "" for untracked/ignored records
    sub: str           # 4-char submodule field; "" for untracked/ignored records
    path: str
    orig_path: str | None = None

    @property
    def tracked(self) -> bool:
        return self.kind in {"1", "2", "u"}

    @property
    def is_gitlink(self) -> bool:
        return self.sub.startswith("S")

    @property
    def record(self) -> str:
        return f"{self.kind} {self.xy}".strip()


def _decode_path(raw: bytes) -> str:
    """Decode one Git path field, refusing every name unsafe to project."""
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ClassificationError("dirty path is not valid UTF-8") from error
    if "\n" in name or "\r" in name:
        raise ClassificationError("dirty path contained a line break")
    if not name:
        raise ClassificationError("dirty path was empty")
    return name


def parse_status_v2(output: bytes) -> tuple[BranchInfo, tuple[StatusEntry, ...]]:
    """Parse ``git status --porcelain=v2 --branch -z`` without line splitting.

    NUL is the record separator, and the rename record ``2`` carries its original
    path as the NEXT field — the one shape a line-oriented parser silently gets
    wrong when a path contains a space.
    """
    if not isinstance(output, bytes):
        raise ClassificationError("git status output was not bytes")
    fields = output.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()

    branch: dict[str, object] = {}
    entries: list[StatusEntry] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if record.startswith(b"# "):
            text = record[2:].decode("utf-8", "replace")
            key, _, value = text.partition(" ")
            if key == "branch.oid":
                branch["oid"] = value.strip()
            elif key == "branch.head":
                branch["head"] = value.strip()
            elif key == "branch.upstream":
                branch["upstream"] = value.strip()
            elif key == "branch.ab":
                parts = value.split()
                if len(parts) == 2:
                    try:
                        branch["ahead"] = int(parts[0])
                        branch["behind"] = -int(parts[1])
                    except ValueError as error:
                        raise ClassificationError(
                            f"git status branch.ab was not numeric: {value!r}"
                        ) from error
            continue

        kind = record[:1].decode("ascii", "replace")
        if kind in {"?", "!"}:
            parts = record.split(b" ", 1)
            if len(parts) != 2:
                raise ClassificationError(f"git status record {kind!r} had no path")
            entries.append(StatusEntry(kind, "", "", _decode_path(parts[1])))
            continue
        if kind in {"1", "2", "u"}:
            leading = {"1": 8, "2": 9, "u": 10}[kind]
            parts = record.split(b" ", leading)
            if len(parts) != leading + 1:
                raise ClassificationError(
                    f"git status record {kind!r} had {len(parts)} fields, "
                    f"expected {leading + 1}"
                )
            xy = parts[1].decode("ascii", "replace")
            sub = parts[2].decode("ascii", "replace")
            path = _decode_path(parts[leading])
            orig: str | None = None
            if kind == "2":
                if index >= len(fields):
                    raise ClassificationError("rename record was missing its origin path")
                orig = _decode_path(fields[index])
                index += 1
            entries.append(StatusEntry(kind, xy, sub, path, orig))
            continue
        raise ClassificationError(f"unsupported git status record {kind!r}")

    return BranchInfo(**branch), tuple(entries)  # type: ignore[arg-type]


# ── rename evidence ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Rename:
    old: str
    new: str
    score: int

    @property
    def exact(self) -> bool:
        return self.score == 100


def renames_from_diff(output: bytes) -> tuple[Rename, ...]:
    """Every rename row in ``git diff --name-status -z -M --diff-filter=R``."""
    found: list[Rename] = []
    for change in parse_name_status(output):
        if not change.status.startswith("R") or len(change.paths) != 2:
            continue
        old = _decode_path(change.paths[0])
        new = _decode_path(change.paths[1])
        found.append(Rename(old, new, int(change.status[1:])))
    return tuple(sorted(found, key=lambda r: (r.old, r.new)))


def exact_rename_map(renames: Iterable[Rename]) -> dict[str, str]:
    """``{old: new}`` for R100 rows only — exact blob matches, never a score.

    A path Git can only match at 87% similarity is by construction a file whose
    CONTENT also changed; that is the content-divergent case and it is agent work
    regardless, so a looser threshold buys nothing and can silently relocate a
    local edit into the wrong file.
    """
    return {r.old: r.new for r in renames if r.exact}


def derive_prefix_pairs(renames: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Directory prefix pairs implied by an exact-rename map.

    For each ``(old, new)`` take the longest common component SUFFIX — capped so
    at least one component of prefix remains on each side — and record the
    differing prefixes.  A pair survives only when EVERY renamed path under
    ``old_dir`` lands under ``new_dir``, so a partially-moved directory yields no
    pair at all (``applications/`` -> ``me/applications/`` is kept; a directory
    whose files scattered to two destinations is not).
    """
    candidates: set[tuple[str, str]] = set()
    for old, new in renames.items():
        old_parts = old.split("/")
        new_parts = new.split("/")
        limit = min(len(old_parts) - 1, len(new_parts) - 1)
        shared = 0
        while shared < limit and old_parts[-1 - shared] == new_parts[-1 - shared]:
            shared += 1
        if shared == 0:
            continue
        old_dir = "/".join(old_parts[:len(old_parts) - shared])
        new_dir = "/".join(new_parts[:len(new_parts) - shared])
        if old_dir and new_dir and old_dir != new_dir:
            candidates.add((old_dir, new_dir))

    consistent = [
        (old_dir, new_dir)
        for old_dir, new_dir in sorted(candidates)
        if all(
            new.startswith(new_dir + "/")
            for old, new in renames.items()
            if old.startswith(old_dir + "/")
        )
    ]
    # One old_dir mapping to two different new_dirs is ambiguous; drop both
    # rather than pick one.
    counts: dict[str, int] = {}
    for old_dir, _ in consistent:
        counts[old_dir] = counts.get(old_dir, 0) + 1
    return tuple(pair for pair in consistent if counts[pair[0]] == 1)


def apply_prefix_pairs(path: str,
                       prefix_pairs: Sequence[tuple[str, str]]) -> str | None:
    """Relocate ``path`` under the longest matching prefix pair, or None."""
    best: tuple[str, str] | None = None
    for old_dir, new_dir in prefix_pairs:
        if path.startswith(old_dir + "/") and (best is None or len(old_dir) > len(best[0])):
            best = (old_dir, new_dir)
    if best is None:
        return None
    return best[1] + path[len(best[0]):]


# ── link-rebase residual normalizer ──────────────────────────────────────────
_LINK_FORMS = (
    re.compile(r"\]\(\s*(?P<t>[^)\s]+)"),          # markdown ](target)
    re.compile(r"`(?P<t>[^`\r\n]+)`"),             # inline `target`
    re.compile(r'href="(?P<t>[^"\r\n]+)"'),
    re.compile(r'src="(?P<t>[^"\r\n]+)"'),
)


def _is_relative_target(target: str) -> bool:
    if not target or target.startswith(("/", "#", "<", "mailto:")):
        return False
    if "://" in target:
        return False
    return True


def _prefix_pattern(old_dir: str) -> re.Pattern[str]:
    # A path-component boundary on the left (so ``applications`` never matches
    # inside ``me/applications`` or ``xapplications``) and a ``/`` on the right
    # (so it only ever rewrites a DIRECTORY prefix).
    return re.compile(r"(?<![0-9A-Za-z._/-])(" + re.escape(old_dir) + r")(?=/)")


def link_rebase(text: str, *, path: str, merged_path: str,
                renames: Mapping[str, str],
                prefix_pairs: Sequence[tuple[str, str]]) -> str:
    """Apply ONLY the substitutions the exact-rename map itself licenses.

    Two families, computed over the ORIGINAL text and applied in a single
    non-overlapping pass:

    1. every relative link target that RESOLVES to a renamed path is re-pointed
       at that path's new home, expressed relative to the file's new directory;
    2. every remaining literal directory prefix named by a surviving prefix pair.

    Applying the two families sequentially would be wrong: family 2 would rewrite
    the output of family 1 a second time (``companies/x`` freshly produced by a
    link rewrite would be re-prefixed by the ``companies/`` pair).  So link spans
    are computed first and any prefix span overlapping one is dropped.

    A target that does not resolve into the rename map is left exactly as it is —
    the normalizer never guesses.
    """
    old_dir = posixpath.dirname(path)
    new_dir = posixpath.dirname(merged_path) or "."

    link_spans: list[tuple[int, int, str]] = []
    for pattern in _LINK_FORMS:
        for match in pattern.finditer(text):
            target = match.group("t")
            if not _is_relative_target(target):
                continue
            resolved = posixpath.normpath(posixpath.join(old_dir, target))
            if resolved not in renames:
                continue
            replacement = posixpath.relpath(renames[resolved], new_dir)
            link_spans.append((match.start("t"), match.end("t"), replacement))

    spans = list(link_spans)
    for pair in sorted(prefix_pairs, key=lambda p: -len(p[0])):
        for match in _prefix_pattern(pair[0]).finditer(text):
            start, end = match.start(1), match.end(1)
            if any(start < ls[1] and ls[0] < end for ls in link_spans):
                continue
            spans.append((start, end, pair[1]))

    spans.sort(key=lambda span: span[0])
    out: list[str] = []
    cursor = 0
    for start, end, replacement in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def residual_line_count(normalized: str, merged: str) -> int:
    """Changed lines between the normalized base text and the merged text."""
    diff = difflib.unified_diff(
        normalized.splitlines(), merged.splitlines(), lineterm="", n=0
    )
    return sum(
        1
        for line in diff
        if line[:1] in {"+", "-"} and not line.startswith(("---", "+++"))
    )


def _looks_binary(blob: bytes | None) -> bool:
    """Git's own heuristic: a NUL byte in the first 8000 bytes.

    Applied directly to the blob rather than through ``git diff --numstat``: it
    is the same test, it costs no extra subprocess, and it also covers the case
    the normalizer actually cares about (text it cannot decode).
    """
    if blob is None:
        return True
    return b"\0" in blob[:8000]


def _decode_text(blob: bytes) -> str | None:
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ── the classified path ──────────────────────────────────────────────────────
@dataclass
class DirtyPath:
    path: str
    worktree_status: str
    tracked: bool
    ignored: bool
    verdict: str
    verdict_reason: str
    merged_path: str | None = None
    rename: dict | None = None
    blobs: dict = field(default_factory=dict)
    residual_after_link_rebase: str = RESIDUAL_NA
    residual_lines: int = 0
    destination_exists: bool = False
    destination_bytes_equal: bool | None = None
    action: str = ACTION_OWNER
    blocking: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> dict:
        return {
            "action": self.action,
            "blobs": dict(self.blobs),
            "destination_bytes_equal": self.destination_bytes_equal,
            "destination_exists": self.destination_exists,
            "ignored": self.ignored,
            "merged_path": self.merged_path,
            "path": self.path,
            "rename": self.rename,
            "residual_after_link_rebase": self.residual_after_link_rebase,
            "residual_lines": self.residual_lines,
            "tracked": self.tracked,
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "worktree_status": self.worktree_status,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _escapes_repo(root: Path, relative: str) -> bool:
    absolute = root / relative
    if not absolute.is_symlink():
        return False
    try:
        resolved = absolute.resolve()
    except OSError:
        return True
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return True
    return False


def classify_entry(entry: StatusEntry, *, git: ReadOnlyGit, base: str,
                   merge_base: str, renames: Mapping[str, str],
                   prefix_pairs: Sequence[tuple[str, str]],
                   ignored_paths: Iterable[str],
                   similarity: Mapping[str, Rename] = MappingProxyType({})) -> DirtyPath:
    """Classify ONE dirty path.  Cases are evaluated in order; first match wins."""
    path = entry.path
    ignored = entry.kind == "!" or path in set(ignored_paths)
    common = {
        "path": path,
        "worktree_status": entry.record,
        "tracked": entry.tracked,
        "ignored": ignored,
    }

    # 1. unsafe -------------------------------------------------------------
    if entry.is_gitlink:
        return DirtyPath(
            **common,
            verdict=VERDICT_UNSAFE,
            verdict_reason="the dirty entry is a gitlink (submodule)",
            action=ACTION_OWNER,
            blocking=((CODE_SUBMODULE_DIRTY,
                       "a dirty gitlink means two repositories claim one tree"),),
        )
    if _escapes_repo(git.root, path):
        return DirtyPath(
            **common,
            verdict=VERDICT_UNSAFE,
            verdict_reason="symlink resolves outside the repository root",
            action=ACTION_OWNER,
            blocking=((CODE_SYMLINK_ESCAPES,
                       "a symlink pointing outside the repository cannot be replayed"),),
        )

    # 2. ignored ------------------------------------------------------------
    if ignored:
        destination = renames.get(path) or apply_prefix_pairs(path, prefix_pairs)
        if destination is None:
            return DirtyPath(
                **common,
                verdict=VERDICT_IGNORED,
                verdict_reason="git-ignored with no layout counterpart",
                action=ACTION_OWNER,
                destination_exists=False,
            )
        source_abs = git.root / path
        dest_abs = git.root / destination
        if dest_abs.exists():
            equal = (
                dest_abs.is_file()
                and source_abs.is_file()
                and _sha256_file(source_abs) == _sha256_file(dest_abs)
            )
            if equal:
                return DirtyPath(
                    **common,
                    verdict=VERDICT_IGNORED,
                    verdict_reason="git-ignored; destination already holds identical bytes",
                    merged_path=destination,
                    action=ACTION_NONE,
                    destination_exists=True,
                    destination_bytes_equal=True,
                )
            return DirtyPath(
                **common,
                verdict=VERDICT_IGNORED,
                verdict_reason="git-ignored; destination exists with DIFFERENT bytes",
                merged_path=destination,
                action=ACTION_OWNER,
                destination_exists=True,
                destination_bytes_equal=False,
                blocking=((CODE_IGNORED_CONFLICT,
                           f"{destination} already exists with different bytes; a "
                           f"non-overwriting copy cannot proceed and only the owner "
                           f"may resolve it"),),
            )
        return DirtyPath(
            **common,
            verdict=VERDICT_IGNORED,
            verdict_reason="git-ignored; merged destination is absent",
            merged_path=destination,
            action=ACTION_COPY,
            destination_exists=False,
        )

    worktree_oid = git.hash_object(path)
    fork_oid = git.blob_oid(merge_base, path)

    # Where did the merged branch put this file?  THREE evidence grades, tried in
    # descending order of strength.  Only the first is a proof, and only the first
    # can ever yield ``renamed-by-merged-layout``.
    #
    # A note on why the second grade has to exist at all.  ``-M100%`` matches
    # IDENTICAL blobs, so an R100 pair proves the contents did not change — which
    # means a path found in the R100 map can never be content-divergent.  A file
    # the merged branch moved AND edited is, by construction, absent from that map
    # and would otherwise fall through to ``unknown``.  That is the calendar case,
    # the one this tool was written for.  Its destination therefore comes from the
    # prefix pairs, which are themselves derived only from R100 renames and kept
    # only when every renamed path under the directory agrees — so the destination
    # is still evidence, not a guess, and the residual check still has to PROVE
    # the delta was path-only.
    evidence: str | None = None
    score: int | None = None
    merged_path = renames.get(path)
    if merged_path is not None:
        evidence, score = "R100", 100
    else:
        derived = apply_prefix_pairs(path, prefix_pairs)
        if derived is not None and git.blob_oid(base, derived) is not None:
            merged_path, evidence = derived, "prefix-pair"
        else:
            similar = similarity.get(path)
            if similar is not None and git.blob_oid(base, similar.new) is not None:
                merged_path, evidence, score = similar.new, "similarity", similar.score

    merged_oid = git.blob_oid(base, merged_path) if merged_path else None
    blobs = {"fork": fork_oid, "merged": merged_oid, "worktree": worktree_oid}
    rename_record = (
        None if evidence is None
        else {"evidence": evidence, "exact": evidence == "R100", "score": score}
    )

    # 3. unchanged ----------------------------------------------------------
    if entry.tracked and worktree_oid is not None and worktree_oid == fork_oid:
        return DirtyPath(
            **common,
            verdict=VERDICT_UNCHANGED,
            verdict_reason="worktree blob equals the fork-point blob",
            merged_path=merged_path,
            rename=rename_record,
            blobs=blobs,
            action=ACTION_NONE,
        )

    # 4. renamed-by-merged-layout -------------------------------------------
    if evidence == "R100" and merged_oid is not None and merged_oid == fork_oid:
        return DirtyPath(
            **common,
            verdict=VERDICT_RENAMED,
            verdict_reason="R100 rename; merged blob equals the fork-point blob",
            merged_path=merged_path,
            rename=rename_record,
            blobs=blobs,
            action=ACTION_REPLAY,
        )

    # 5. content-divergent + link-rebase residual ---------------------------
    if merged_path is not None:
        fork_blob = git.cat_blob(merge_base, path)
        merged_blob = git.cat_blob(base, merged_path)
        fork_text = None if _looks_binary(fork_blob) else _decode_text(fork_blob or b"")
        merged_text = None if _looks_binary(merged_blob) else _decode_text(merged_blob or b"")
        found_by = f"moved upstream ({evidence}); contents differ"
        if fork_text is None or merged_text is None:
            residual, lines = RESIDUAL_BINARY, 0
            reason = f"{found_by}; residual not attempted (binary)"
        else:
            normalized = link_rebase(
                fork_text, path=path, merged_path=merged_path,
                renames=renames, prefix_pairs=prefix_pairs,
            )
            if normalized == merged_text:
                residual, lines = RESIDUAL_EMPTY, 0
                reason = (f"{found_by}; residual after link-rebase is EMPTY "
                          f"(upstream delta proven path-only)")
            else:
                residual = RESIDUAL_NON_EMPTY
                lines = residual_line_count(normalized, merged_text)
                reason = (f"{found_by}; residual after link-rebase is "
                          f"{lines} line(s)")
        return DirtyPath(
            **common,
            verdict=VERDICT_CONTENT_DIVERGENT,
            verdict_reason=reason,
            merged_path=merged_path,
            rename=rename_record,
            blobs=blobs,
            residual_after_link_rebase=residual,
            residual_lines=lines,
            action=ACTION_AGENT_RESOLVE,
        )

    # 6. unknown ------------------------------------------------------------
    return DirtyPath(
        **common,
        verdict=VERDICT_UNKNOWN,
        verdict_reason="no exact-rename evidence in base..merged and no other explanation",
        blobs=blobs,
        action=ACTION_OWNER,
        blocking=((CODE_UNKNOWN_DIRTY,
                   "no rename evidence and no other explanation; the planner will "
                   "not guess whether the file is disposable"),),
    )


def classify_entries(entries: Sequence[StatusEntry], *, git: ReadOnlyGit,
                     base: str, merge_base: str,
                     renames: Mapping[str, str],
                     prefix_pairs: Sequence[tuple[str, str]],
                     similarity: Mapping[str, Rename] = MappingProxyType({}),
                     ) -> list[DirtyPath]:
    """Classify every dirty entry, sorted by path (the plan's canonical order)."""
    candidates = [e.path for e in entries if e.kind != "!"]
    ignored_paths = git.ignored(candidates) | {e.path for e in entries if e.kind == "!"}
    classified = [
        classify_entry(entry, git=git, base=base, merge_base=merge_base,
                       renames=renames, prefix_pairs=prefix_pairs,
                       ignored_paths=ignored_paths, similarity=similarity)
        for entry in entries
    ]
    classified.sort(key=lambda d: d.path)
    return classified


__all__ = [
    "ACTIONS",
    "BranchInfo",
    "ClassificationError",
    "DirtyPath",
    "GitError",
    "READ_ONLY_SUBCOMMANDS",
    "RESIDUALS",
    "ReadOnlyGit",
    "Rename",
    "StatusEntry",
    "VERDICTS",
    "apply_prefix_pairs",
    "classify_entries",
    "classify_entry",
    "derive_prefix_pairs",
    "exact_rename_map",
    "link_rebase",
    "parse_name_status",
    "parse_status_v2",
    "renames_from_diff",
    "residual_line_count",
]
