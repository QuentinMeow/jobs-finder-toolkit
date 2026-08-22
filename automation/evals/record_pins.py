#!/usr/bin/env python3
"""Content pins for eval records — what bytes were actually under test.

An eval record's provenance used to be one free-form prose cell::

    | Git SHA | `389dfee` + uncommitted working tree (the v4 change under review) |

Nothing can check that. Across the records in ``evals/results/`` the field holds
clean SHAs, branch names, two SHAs, "PR #52 head", and sixteen variants of
"plus the uncommitted working tree" — the last being the interesting failure,
because the tested bytes were then in no commit at all, so an ancestry check on
the named SHA passes while proving nothing about what ran.

This module replaces the guess with a measurement. It records, per instruction
file under test, the sha256 of the exact bytes and their length, so a later
reader can ask a question with a real answer: *are these still the bytes at
HEAD?*

**New records only.** Nothing here backfills, refreshes or rewrites a historical
record — those are evidence, and a pin invented after the fact would be a
fabrication wearing a checksum. There is deliberately no ``--backfill``.

## The pin block

A fenced block, in the record, next to the metadata table::

    ```eval-pin v1
    skill job-search
    pin sha256=1b9f0c2d4e6a8b70 bytes=24680 path=skills/job-search/SKILL.md
    pin sha256=0a1c2e4f6b8d0011 bytes=5120 path=skills/job-search/LESSONS.md
    pin sha256=90ab12cd34ef5678 bytes=8192 path=evals/canaries/job-search.yaml
    ```

Plain keyword-led lines, **not YAML**: ``automation/reconcile/reconcile.py`` is
contractually stdlib-only on a bare clone, so anything that may one day need to
read this must be parseable without PyYAML. ``path=`` is last on the line so the
rest of the line is the path, whatever it contains.

The digest is the first 16 hex characters of the sha256 of the file's raw bytes
— 64 bits, the same truncation ``automation/publish/review_ledger.yaml`` uses,
and far past what an accident reaches. ``bytes=`` is carried alongside because a
length mismatch localises a drift instantly without a second read.

## Usage

    # print a block for a skill, computed from the working tree
    .venv/bin/python automation/evals/record_pins.py --emit --skill job-search

    # insert (or refresh) that block inside a record, leaving the rest untouched
    .venv/bin/python automation/evals/record_pins.py --write evals/results/<record>.md

    # report each pinned file against a revision (default HEAD)
    .venv/bin/python automation/evals/record_pins.py --report evals/results/<record>.md
    .venv/bin/python automation/evals/record_pins.py --report <record>.md --rev main

``--report`` classifies every pinned file:

    current   the path exists at <rev> and its bytes hash to the pinned digest
    drifted   the path exists at <rev> and its bytes are different
    moved     the path is gone at <rev>, but another instruction file there
              carries exactly the pinned bytes (a rename)
    gone      the path is gone at <rev> and those bytes are nowhere in it

``--report`` is a REPORT: it exits 0 whenever it could read the record, drift
included. It is deliberately not wired into ``reconcile.py``'s ``CHECKS`` and is
run by a human or an agent that wants the answer. The open owner decision
``message-queue/needs-human/decisions/process-weight-what-to-cut.md`` carries a
default path of "no new gate is added while this is open", and a gate over the
one record that has a block would be noise anyway. Exit 2 is reserved for a
usage or I/O failure — a missing record, an unparseable block, a bad revision.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

BLOCK_VERSION = "v1"
FENCE_INFO = f"eval-pin {BLOCK_VERSION}"
DIGEST_HEX = 16          # first 64 bits of the sha256; see module docstring

# The core instruction files a canary run is a test OF, in the order they are
# pinned. Additional top-level Markdown guides are appended deterministically;
# progressive disclosure may move behavior into files such as dossier-guide.md,
# and omitting those bytes would make a retiered skill's eval provenance false.
SKILL_FILES = ("SKILL.md", "LESSONS.md", "reference.md")

# Every path that could legitimately hold a pinned file's bytes under a different
# name. Bounds the rename search in --report to ~30 blobs instead of the whole
# tree: a "moved" verdict only makes sense for another instruction file, and
# hashing every blob at a revision to answer it would be a different tool.
CANDIDATE_RE = re.compile(
    r"^(?:skills/[^/]+/[^/]+\.md"
    r"|evals/canaries/[^/]+\.yaml)$"
)

_FENCE_OPEN_RE = re.compile(r"^\s*```+\s*eval-pin\s+(?P<version>\S+)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```+\s*$")
# ``| Skill | `job-search` |`` in a record's metadata table.
_SKILL_ROW_RE = re.compile(r"^\|\s*Skill\s*\|\s*`?([A-Za-z0-9._-]+)`?\s*\|", re.M)

EXIT_OK = 0
EXIT_ERROR = 2


class PinError(Exception):
    """A usage or I/O failure: a missing record, a bad block, a bad revision."""


@dataclass(frozen=True)
class Pin:
    """One pinned file: its repo-relative path and the bytes it held."""

    path: str
    sha256: str
    size: int

    def line(self) -> str:
        return f"pin sha256={self.sha256} bytes={self.size} path={self.path}"


@dataclass(frozen=True)
class PinBlock:
    """A parsed ``eval-pin`` block: the skill it covers and its pins."""

    skill: str
    pins: tuple[Pin, ...]

    def render(self) -> str:
        lines = [f"```{FENCE_INFO}", f"skill {self.skill}"]
        lines += [pin.line() for pin in self.pins]
        lines.append("```")
        return "\n".join(lines)


# ── digests ──────────────────────────────────────────────────────────────────

def digest_bytes(data: bytes) -> str:
    """The pinned digest of a byte string: sha256, truncated to 64 bits."""
    return hashlib.sha256(data).hexdigest()[:DIGEST_HEX]


def pin_for(root: Path, rel: str) -> Pin:
    """Pin the working-tree file at ``rel`` (repo-relative)."""
    data = (root / rel).read_bytes()
    return Pin(path=rel, sha256=digest_bytes(data), size=len(data))


# ── emit ─────────────────────────────────────────────────────────────────────

def expected_paths(root: Path, skill: str) -> list[str]:
    """The files a run of ``skill``'s canaries is a test of, in pin order.

    The canary set is in here on purpose. A record that pins the instructions but
    not the prompts they were judged against pins half the experiment: editing a
    canary changes the verdict just as surely as editing the SKILL.md does.
    """
    skill_dir = root / "skills" / skill
    paths = [f"skills/{skill}/{name}" for name in SKILL_FILES]
    core_names = set(SKILL_FILES)
    if skill_dir.is_dir():
        paths.extend(
            f"skills/{skill}/{path.name}"
            for path in sorted(skill_dir.glob("*.md"), key=lambda item: item.name)
            if path.name not in core_names
        )
    paths.append(f"evals/canaries/{skill}.yaml")
    return paths


def build_block(root: Path, skill: str) -> tuple[PinBlock, list[str]]:
    """Return the block for ``skill`` plus the expected paths that do not exist.

    A skill legitimately ships without a ``LESSONS.md`` or a ``reference.md``, so
    an absent file is skipped rather than fatal — but it is RETURNED, not
    swallowed, because "3 pins" and "3 of 4 files pinned" are different facts and
    the caller is the one that can say so.
    """
    pins, missing = [], []
    expected = expected_paths(root, skill)
    for rel in expected:
        if (root / rel).is_file():
            pins.append(pin_for(root, rel))
        else:
            missing.append(rel)
    if not pins:
        raise PinError(
            f"no instruction files found for skill {skill!r} under {root} "
            f"(looked for: {', '.join(expected)})"
        )
    return PinBlock(skill=skill, pins=tuple(pins)), missing


# ── parse ────────────────────────────────────────────────────────────────────

def find_block(text: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` line span of the block, fences included."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _FENCE_OPEN_RE.match(line)
        if not m:
            continue
        if m.group("version") != BLOCK_VERSION:
            raise PinError(
                f"line {i + 1}: eval-pin block version {m.group('version')!r} is "
                f"not supported (this tool writes and reads {BLOCK_VERSION})"
            )
        for j in range(i + 1, len(lines)):
            if _FENCE_CLOSE_RE.match(lines[j]):
                return i, j + 1
        raise PinError(f"line {i + 1}: eval-pin block is never closed")
    return None


def parse_block(text: str) -> PinBlock | None:
    """Parse the record's ``eval-pin`` block, or None when it has none."""
    span = find_block(text)
    if span is None:
        return None
    start, end = span
    body = text.splitlines()[start + 1:end - 1]

    skill, pins = None, []
    for offset, raw in enumerate(body):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lineno = start + 2 + offset
        keyword, _, rest = line.partition(" ")
        if keyword == "skill":
            skill = rest.strip()
        elif keyword == "pin":
            pins.append(_parse_pin(rest, lineno))
        else:
            raise PinError(f"line {lineno}: unknown eval-pin keyword {keyword!r}")

    if not skill:
        raise PinError("eval-pin block has no `skill` line")
    if not pins:
        raise PinError("eval-pin block has no `pin` lines")
    return PinBlock(skill=skill, pins=tuple(pins))


def _parse_pin(rest: str, lineno: int) -> Pin:
    """Parse ``sha256=<hex> bytes=<n> path=<rel>`` — path last, so it may be anything."""
    m = re.match(
        r"^sha256=(?P<sha>[0-9a-f]+)\s+bytes=(?P<size>\d+)\s+path=(?P<path>.+)$",
        rest.strip(),
    )
    if not m:
        raise PinError(
            f"line {lineno}: expected `pin sha256=<hex> bytes=<n> path=<path>`, "
            f"got `pin {rest.strip()}`"
        )
    return Pin(
        path=m.group("path").strip(),
        sha256=m.group("sha"),
        size=int(m.group("size")),
    )


# ── write ────────────────────────────────────────────────────────────────────

def insert_index(lines: list[str]) -> int:
    """Where a block goes in a record that has none: after the metadata table.

    The pin block is provenance, so it belongs beside the other provenance rather
    than at the bottom under the verdict. Falls back to just after the title, then
    to the end of the file — a record this tool cannot recognise still gets its
    block, at a predictable place, without any of its text being rearranged.
    """
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        j = i
        while j < len(lines) and lines[j].startswith("|"):
            j += 1
        return j
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return i + 1
    return len(lines)


def upsert_block(text: str, block: PinBlock) -> str:
    """Insert or replace the block, leaving every other byte of ``text`` alone."""
    lines = text.splitlines()
    span = find_block(text)
    rendered = block.render().splitlines()

    if span is not None:
        start, end = span
        new_lines = lines[:start] + rendered + lines[end:]
    else:
        at = insert_index(lines)
        chunk = rendered
        # One blank line either side, and never two: a record is read by humans.
        if at > 0 and lines[at - 1].strip():
            chunk = [""] + chunk
        if at < len(lines) and lines[at].strip():
            chunk = chunk + [""]
        new_lines = lines[:at] + chunk + lines[at:]

    out = "\n".join(new_lines)
    # splitlines() drops the trailing newline; markdown files here all end with one.
    return out + "\n" if text.endswith("\n") or not text else out


def skill_from_record(text: str) -> str | None:
    """The skill a record is about, from its existing block or its `Skill` row.

    An UNPARSEABLE block is not an error here, and that is the main path rather
    than an edge case: a record is made by copying ``evals/results/TEMPLATE.md``,
    whose block is all ``<16 hex>`` placeholders, and the very next thing anyone
    does is run ``--write`` to fill it. Refusing to read a placeholder would break
    exactly the workflow this exists for. A block whose *version* is unsupported
    still fails, one call later, in ``upsert_block``.
    """
    try:
        block = parse_block(text)
    except PinError:
        block = None
    if block is not None:
        return block.skill
    # The template ships this row as ``| Skill | `<skill>` |``; the character class
    # does not match ``<skill>``, so an unfilled template is correctly "unknown"
    # rather than a skill literally named "<skill>".
    m = _SKILL_ROW_RE.search(text)
    return m.group(1) if m else None


# ── report ───────────────────────────────────────────────────────────────────

def _git(args: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True)


def read_at_rev(repo: Path, rev: str, rel: str) -> bytes | None:
    """The bytes of ``rel`` at ``rev``, or None when the path is not there."""
    proc = _git(["cat-file", "blob", f"{rev}:{rel}"], repo)
    return proc.stdout if proc.returncode == 0 else None


def _resolve_rev(repo: Path, rev: str) -> str:
    proc = _git(["rev-parse", "--verify", f"{rev}^{{commit}}"], repo)
    if proc.returncode != 0:
        raise PinError(
            f"cannot resolve revision {rev!r} in {repo}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout.decode().strip()


def candidate_paths(repo: Path, rev: str) -> list[str]:
    """Instruction files present at ``rev`` — the search space for a rename."""
    proc = _git(["ls-tree", "-r", "--name-only", rev], repo)
    if proc.returncode != 0:
        raise PinError(
            f"cannot list the tree at {rev!r}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    names = proc.stdout.decode("utf-8", "replace").splitlines()
    return [n for n in names if CANDIDATE_RE.match(n)]


def report(repo: Path, block: PinBlock, resolved: str) -> list[dict]:
    """Classify each pin against the RESOLVED commit ``resolved``.

    Takes a resolved sha rather than a symbolic name so a long run cannot compare
    its first pin against one commit and its last against another. See the module
    docstring for the four verdicts.
    """
    rows: list[dict] = []
    # Built once, and only if something is actually missing at its pinned path —
    # the common case is "everything is current" and costs one read per pin.
    index: dict[str, str] | None = None

    for pin in block.pins:
        data = read_at_rev(repo, resolved, pin.path)
        if data is not None:
            found = digest_bytes(data)
            status = "current" if found == pin.sha256 else "drifted"
            rows.append({
                "pin": pin, "status": status,
                "found_sha256": found, "found_size": len(data), "note": "",
            })
            continue

        if index is None:
            index = {}
            for name in candidate_paths(repo, resolved):
                other = read_at_rev(repo, resolved, name)
                if other is not None:
                    index.setdefault(digest_bytes(other), name)

        moved_to = index.get(pin.sha256)
        rows.append({
            "pin": pin,
            "status": "moved" if moved_to else "gone",
            "found_sha256": None,
            "found_size": None,
            "note": f"now at {moved_to}" if moved_to else "not at any instruction path",
        })
    return rows


def format_report(rows: list[dict], skill: str, rev: str, resolved: str) -> str:
    header = f"eval-pin report — skill `{skill}` against {rev} ({resolved[:12]})"
    width = max((len(r["pin"].path) for r in rows), default=4)
    out = [header, ""]
    for r in rows:
        pin = r["pin"]
        detail = r["note"]
        if r["status"] == "drifted":
            detail = (f"pinned sha256={pin.sha256} bytes={pin.size}; "
                      f"now sha256={r['found_sha256']} bytes={r['found_size']}")
        row = f"  {r['status']:<8} {pin.path.ljust(width)}"
        out.append(f"{row}  {detail}" if detail else row.rstrip())
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    out += ["", f"{len(rows)} pinned file(s): {summary}."]
    if counts.get("current") != len(rows):
        out.append("Report only — this tool never fails on drift; a record is "
                   "evidence of the bytes it names, not of head.")
    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_emit(args, repo: Path) -> int:
    block, missing = build_block(repo, args.skill)
    if missing:
        print(f"note: not pinned (absent under {repo}): {', '.join(missing)}",
              file=sys.stderr)
    print(block.render())
    return EXIT_OK


def _cmd_write(args, repo: Path) -> int:
    record = Path(args.write)
    if not record.is_file():
        raise PinError(f"no such record: {record}")
    text = record.read_text(encoding="utf-8")

    skill = args.skill or skill_from_record(text)
    if not skill:
        raise PinError(
            f"cannot tell which skill {record} is about — it has no eval-pin block "
            f"and no filled `| Skill | ... |` row; pass --skill"
        )

    block, missing = build_block(repo, skill)
    if missing:
        print(f"note: not pinned (absent under {repo}): {', '.join(missing)}",
              file=sys.stderr)

    updated = upsert_block(text, block)
    if updated == text:
        print(f"{record}: pin block already current ({len(block.pins)} file(s)).")
        return EXIT_OK
    record.write_text(updated, encoding="utf-8")
    verb = "refreshed" if find_block(text) else "inserted"
    print(f"{record}: {verb} eval-pin block for `{skill}` "
          f"({len(block.pins)} file(s) pinned).")
    return EXIT_OK


def _cmd_report(args, repo: Path) -> int:
    record = Path(args.report)
    if not record.is_file():
        raise PinError(f"no such record: {record}")
    block = parse_block(record.read_text(encoding="utf-8"))
    if block is None:
        raise PinError(
            f"{record} has no eval-pin block — pins are for NEW records; this tool "
            f"never invents one for a historical result"
        )
    resolved = _resolve_rev(repo, args.rev)
    rows = report(repo, block, resolved)
    print(format_report(rows, block.skill, args.rev, resolved))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit, write and report the content pins of an eval record.",
        epilog="Historical records are evidence: nothing here backfills one.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--emit", action="store_true",
                      help="print a pin block for --skill, from the working tree")
    mode.add_argument("--write", metavar="RECORD",
                      help="insert or refresh the pin block inside a record file")
    mode.add_argument("--report", metavar="RECORD",
                      help="classify each pinned file against --rev")
    parser.add_argument("--skill", metavar="NAME",
                        help="skill whose instruction files are pinned "
                             "(required by --emit; inferred by --write)")
    parser.add_argument("--rev", default="HEAD", metavar="REV",
                        help="revision --report compares against (default: HEAD)")
    parser.add_argument("--repo", default=str(REPO_ROOT), metavar="DIR",
                        help="repository root (default: this checkout)")
    args = parser.parse_args(argv)

    if args.emit and not args.skill:
        parser.error("--emit needs --skill")

    repo = Path(args.repo).resolve()
    try:
        if args.emit:
            return _cmd_emit(args, repo)
        if args.write:
            return _cmd_write(args, repo)
        return _cmd_report(args, repo)
    except PinError as exc:
        print(f"record_pins: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"record_pins: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
