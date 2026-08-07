#!/usr/bin/env python3
"""Checksum-compare two trees, and copy files WITHOUT ever overwriting or deleting.

WHY THIS EXISTS
---------------
Cutting a working tree over to a merged layout leaves git-ignored files behind:
Git renamed every tracked path, and the ignored ones still sit at their old
address. Moving them by hand is where data dies — a ``cp -r`` silently
overwrites a destination that already holds different bytes, and an ``mv``
destroys the retired source before anyone has verified the new one.

So this tool has exactly two modes and one refusal:

  * ``--copy``   creates destinations that do not exist yet. A destination that
    already exists with the SAME bytes is a no-op; a destination that exists with
    DIFFERENT bytes is a REFUSAL — the whole run is rejected before a single byte
    is written, so a conflict never leaves a half-migrated tree. The creation
    itself uses ``O_CREAT|O_EXCL``, so "it did not exist a moment ago" cannot
    turn into an overwrite between the check and the write.
  * ``--verify`` re-hashes both ends of every recorded pair and exits nonzero on
    any mismatch or missing file.

The SOURCE is never removed, in either mode. Retiring the old copy is the
owner's call, not this tool's (AGENTS.md: agents never delete owner data).

Usage::

    # copy one file or a whole tree, create-only, recording what it created
    .venv/bin/python automation/cutover/verify_copy.py --copy \\
        --from <src> --to <dst> --manifest local/cutover/<run-id>/copied.txt

    # re-verify everything a previous --copy recorded
    .venv/bin/python automation/cutover/verify_copy.py --verify \\
        --manifest local/cutover/<run-id>/copied.txt

    # compare two trees directly, with no manifest
    .venv/bin/python automation/cutover/verify_copy.py --verify --from <src> --to <dst>

Exit codes::

    0  every pair matches / every planned destination was created
    1  a mismatch, a missing file, or a refusal (destination exists, other bytes)
    2  usage error (argparse)
    3  NOTHING WAS VERIFIED — no manifest, or a manifest with no rows

Exit 3 matters: a verification that had nothing to check must never be readable
as a green one. ``automation/cutover/validate_cutover.py`` turns that state into
an explicit SKIP row before the subprocess even starts.

Manifest format — one row per destination CREATED, LF-terminated::

    <sha256>  <source path>\t<destination path>

Both paths are absolute. A path containing a tab or a newline is refused rather
than written, because a manifest that cannot be parsed back is not a record.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

READ_CHUNK = 1024 * 1024
FIELD_SEPARATOR = "\t"
DIGEST_SEPARATOR = "  "

OK, CREATED, ALREADY, CONFLICT, MISSING, MISMATCH, UNSAFE = (
    "OK", "CREATED", "ALREADY", "CONFLICT", "MISSING", "MISMATCH", "UNSAFE")


class CopyRefused(RuntimeError):
    """A precondition that must stop the run before anything is written."""


@dataclass(frozen=True)
class Pair:
    """One source → destination mapping."""

    source: Path
    destination: Path


@dataclass(frozen=True)
class Row:
    """One manifest record."""

    digest: str
    source: Path
    destination: Path


# ── hashing ──────────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    """Streamed sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(READ_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ── manifest ─────────────────────────────────────────────────────────────────


def format_row(row: Row) -> str:
    for path in (row.source, row.destination):
        text = str(path)
        if FIELD_SEPARATOR in text or "\n" in text or "\r" in text:
            raise CopyRefused(
                f"path contains a tab or newline and cannot be recorded: {text!r}")
    return f"{row.digest}{DIGEST_SEPARATOR}{row.source}{FIELD_SEPARATOR}{row.destination}"


def parse_manifest(text: str) -> list[Row]:
    """Parse a manifest, refusing anything ambiguous rather than guessing."""
    rows: list[Row] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(FIELD_SEPARATOR)
        if len(parts) != 2:
            raise CopyRefused(
                f"manifest line {number}: expected exactly one tab separating "
                f"source from destination, got {len(parts) - 1}")
        head, destination = parts
        digest, separator, source = head.partition(DIGEST_SEPARATOR)
        if not separator or not source:
            raise CopyRefused(
                f"manifest line {number}: expected '<sha256>  <source>' before the tab")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CopyRefused(
                f"manifest line {number}: {digest!r} is not a lowercase sha256 digest")
        rows.append(Row(digest, Path(source), Path(destination)))
    return rows


def append_rows(manifest: Path, rows: Sequence[Row]) -> None:
    if not rows:
        return
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(format_row(row) + "\n")


# ── pair enumeration ─────────────────────────────────────────────────────────


def enumerate_pairs(source: Path, destination: Path) -> list[Pair]:
    """One pair for a file, one per contained file for a directory.

    Symlinks are refused rather than followed: a symlinked source could copy
    bytes from outside the tree the caller named, and a symlinked destination
    could write through to a file the caller never mentioned.
    """
    if source.is_symlink():
        raise CopyRefused(f"source is a symlink, which is never followed: {source}")
    if not source.exists():
        raise CopyRefused(f"source does not exist: {source}")
    if source.is_file():
        return [Pair(source, destination)]
    if not source.is_dir():
        raise CopyRefused(f"source is neither a file nor a directory: {source}")

    pairs: list[Pair] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise CopyRefused(
                f"source tree contains a symlink, which is never followed: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise CopyRefused(f"source tree contains a non-regular file: {path}")
        pairs.append(Pair(path, destination / path.relative_to(source)))
    return pairs


# ── copy ─────────────────────────────────────────────────────────────────────


def plan_copy(pairs: Sequence[Pair]) -> tuple[list[Pair], list[Pair], list[Pair]]:
    """Split pairs into (to create, already identical, conflicting)."""
    create: list[Pair] = []
    already: list[Pair] = []
    conflict: list[Pair] = []
    for pair in pairs:
        if pair.destination.is_symlink():
            conflict.append(pair)
            continue
        if not pair.destination.exists():
            create.append(pair)
            continue
        if pair.destination.is_dir():
            conflict.append(pair)
            continue
        if sha256_file(pair.destination) == sha256_file(pair.source):
            already.append(pair)
        else:
            conflict.append(pair)
    return create, already, conflict


def create_only(pair: Pair) -> str:
    """Write the destination, or fail. Never truncates an existing file.

    ``O_CREAT | O_EXCL`` is the whole point: ``plan_copy`` decided a moment ago
    that the destination was absent, and this makes that decision binding at the
    syscall rather than merely likely.
    """
    pair.destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(pair.destination, flags, 0o644)
    try:
        with os.fdopen(fd, "wb") as out, pair.source.open("rb") as src:
            while True:
                chunk = src.read(READ_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
    except BaseException:
        # The destination did not exist before this call, so removing the partial
        # file destroys nothing the owner had. This is the ONLY unlink in the
        # module and it only ever touches bytes this call just wrote.
        try:
            pair.destination.unlink()
        except OSError:
            pass
        raise
    return sha256_file(pair.destination)


def run_copy(source: Path, destination: Path, manifest: Path | None, out) -> int:
    pairs = enumerate_pairs(source, destination)
    create, already, conflict = plan_copy(pairs)

    if conflict:
        print(f"REFUSED: {len(conflict)} destination(s) already exist with different "
              f"bytes (or are not regular files). Nothing was copied.", file=out)
        for pair in conflict:
            print(f"  {CONFLICT}  {pair.source} -> {pair.destination}", file=out)
        print("This tool never overwrites. Resolve each destination by hand — the "
              "sources are all still in place.", file=out)
        return 1

    created: list[Row] = []
    for pair in create:
        digest = create_only(pair)
        created.append(Row(digest, pair.source, pair.destination))
        print(f"  {CREATED}  {pair.source} -> {pair.destination}", file=out)
    for pair in already:
        print(f"  {ALREADY}  {pair.destination} (identical bytes; no manifest row)",
              file=out)

    if manifest is not None:
        append_rows(manifest, created)

    # A source is never removed. Say so, because that is the property a reader
    # of this output most needs to be able to trust.
    print(f"copied {len(created)} file(s), {len(already)} already identical; "
          f"0 overwritten, 0 deleted; sources left in place at {source}", file=out)
    if manifest is not None:
        print(f"manifest: {manifest} (+{len(created)} row(s))", file=out)
    return 0


# ── verify ───────────────────────────────────────────────────────────────────


def verify_rows(rows: Iterable[Row], out) -> int:
    failures = 0
    checked = 0
    for row in rows:
        checked += 1
        problems: list[str] = []
        digests: dict[str, str] = {}
        for label, path in (("source", row.source), ("destination", row.destination)):
            if not path.is_file():
                problems.append(f"{MISSING} {label}: {path}")
                continue
            digests[label] = sha256_file(path)
        if not problems:
            if digests["source"] != row.digest:
                problems.append(
                    f"{MISMATCH} source: recorded {row.digest[:12]}, "
                    f"now {digests['source'][:12]}: {row.source}")
            if digests["destination"] != row.digest:
                problems.append(
                    f"{MISMATCH} destination: recorded {row.digest[:12]}, "
                    f"now {digests['destination'][:12]}: {row.destination}")
        if problems:
            failures += 1
            for problem in problems:
                print(f"  {problem}", file=out)
        else:
            print(f"  {OK}  {row.destination}", file=out)
    if failures:
        print(f"RED: {failures} of {checked} recorded pair(s) do not match.", file=out)
        return 1
    print(f"OK: {checked} recorded pair(s) match on both ends.", file=out)
    return 0


def run_verify_manifest(manifest: Path, out) -> int:
    if not manifest.is_file():
        print(f"NOTHING TO VERIFY: no manifest at {manifest}. This is not a pass — "
              f"no copy has been recorded for this run.", file=out)
        return 3
    rows = parse_manifest(manifest.read_text(encoding="utf-8"))
    if not rows:
        print(f"NOTHING TO VERIFY: {manifest} records no copied file. This is not a "
              f"pass.", file=out)
        return 3
    print(f"verifying {len(rows)} recorded pair(s) from {manifest}", file=out)
    return verify_rows(rows, out)


def run_verify_trees(source: Path, destination: Path, out) -> int:
    pairs = enumerate_pairs(source, destination)
    if not pairs:
        print(f"NOTHING TO VERIFY: {source} contains no files. This is not a pass.",
              file=out)
        return 3
    rows = [Row(sha256_file(pair.source), pair.source, pair.destination)
            for pair in pairs]
    print(f"verifying {len(rows)} file(s) under {source} against {destination}",
          file=out)
    return verify_rows(rows, out)


# ── cli ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_copy.py",
        description="Checksum-compare two trees, or copy files create-only. This "
                    "tool never overwrites and never deletes.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--copy", action="store_true",
                      help="create every destination that does not exist yet; refuse "
                           "the whole run if any exists with different bytes")
    mode.add_argument("--verify", action="store_true",
                      help="re-hash both ends of every recorded pair")
    parser.add_argument("--from", dest="source", metavar="PATH",
                        help="source file or directory")
    parser.add_argument("--to", dest="destination", metavar="PATH",
                        help="destination file or directory")
    parser.add_argument("--manifest", metavar="PATH",
                        help="record of what --copy created; the input for --verify")
    return parser


def main(argv: Sequence[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    source = Path(args.source).expanduser() if args.source else None
    destination = Path(args.destination).expanduser() if args.destination else None
    manifest = Path(args.manifest).expanduser() if args.manifest else None

    try:
        if args.copy:
            if source is None or destination is None:
                print("verify_copy: --copy requires --from and --to.", file=out)
                return 2
            return run_copy(source, destination, manifest, out)

        if manifest is not None:
            if source is not None or destination is not None:
                print("verify_copy: --verify takes EITHER --manifest OR --from/--to, "
                      "not both; two sources of truth cannot disagree safely.",
                      file=out)
                return 2
            return run_verify_manifest(manifest, out)
        if source is None or destination is None:
            print("verify_copy: --verify requires --manifest, or --from and --to.",
                  file=out)
            return 2
        return run_verify_trees(source, destination, out)
    except CopyRefused as error:
        print(f"REFUSED: {error}", file=out)
        return 1
    except OSError as error:
        print(f"REFUSED: {error}", file=out)
        return 1


if __name__ == "__main__":
    sys.exit(main())
