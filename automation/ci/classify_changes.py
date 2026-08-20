#!/usr/bin/env python3
"""Conservatively select the long-running CI lanes affected by a Git range.

The classifier is intentionally a small, stdlib-only bootstrap program: it runs
before dependencies are installed and turns every uncertainty into the full lane
matrix.  Documentation and repository-process records are the sole inert class.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


LANES = (
    "maintenance",
    "render",
    "resume",
    "shared",
    "job-search",
    "applications",
    "publish",
)
PDF_LANES = ("render", "resume")

# These records are still checked by the fast, always-on policy job.  They do not
# need a dependency install, LibreOffice, or a long unit-test lane of their own.
INERT_PREFIXES = (
    "docs/",
    "history/",
    "memory/",
    "message-queue/",
    "tasks/",
)
INERT_ROOT_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "LESSONS.md",
    "README.md",
}
ALWAYS_ON_ONLY_PATHS = {
    # Every public PR appends this receipt.  The fast review gate validates it;
    # selecting the publish unit-test lane here would make every PR long-running.
    "automation/publish/review_ledger.yaml",
}
INERT_SKILL_FILES = {"SKILL.md", "LESSONS.md", "reference.md"}

# A mistake in any of these inputs can invalidate every narrower ownership rule.
FULL_PREFIXES = (
    ".github/",
    "automation/ci/",
    "automation/shared/mail/",
    "automation/shared/store/",
    "automation/vendoring/",
)
FULL_ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    ".gitmodules",
    "config.example.yaml",
    "config.yaml",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
}
DEPENDENCY_SUFFIXES = (
    ".lock",
    "requirements.in",
    "requirements.txt",
)


@dataclass(frozen=True)
class Change:
    status: str
    paths: tuple[bytes, ...]


@dataclass(frozen=True)
class Classification:
    lanes: tuple[str, ...]
    full: bool
    reason: str
    changes: tuple[Change, ...] = ()

    @property
    def matrix(self) -> dict[str, list[dict[str, str]]]:
        return {"include": [{"lane": lane} for lane in self.lanes]}


class ClassificationError(RuntimeError):
    """An input could not be trusted enough for a narrow selection."""


def parse_name_status(output: bytes) -> tuple[Change, ...]:
    """Parse ``git diff --name-status -z -M`` output without line splitting."""
    if not isinstance(output, bytes):
        raise ClassificationError("Git diff output was not bytes")
    if output == b"":
        return ()
    if not output.endswith(b"\0"):
        raise ClassificationError("Git diff output was not NUL-terminated")

    fields = output[:-1].split(b"\0")
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        raw_status = fields[index]
        index += 1
        try:
            status = raw_status.decode("ascii")
        except UnicodeDecodeError as error:
            raise ClassificationError("Git returned a non-ASCII change status") from error

        if status in {"A", "D", "M", "T", "U", "X", "B"}:
            path_count = 1
        elif (
            len(status) > 1
            and status[0] in {"C", "R"}
            and status[1:].isdigit()
            and 0 <= int(status[1:]) <= 100
        ):
            path_count = 2
        else:
            raise ClassificationError(f"Git returned unsupported status {status!r}")

        if index + path_count > len(fields):
            raise ClassificationError(f"Git status {status!r} was missing a path")
        paths = tuple(fields[index:index + path_count])
        if any(not path for path in paths):
            raise ClassificationError(f"Git status {status!r} contained an empty path")
        if any(b"\n" in path or b"\r" in path for path in paths):
            # Such names are valid to Git, but unsafe to project into logs/reasons.
            raise ClassificationError("changed path contained a line break")
        changes.append(Change(status, paths))
        index += path_count
    return tuple(changes)


def _text(path: bytes) -> str:
    # Git permits non-UTF-8 path bytes. Replacement keeps classification
    # fail-closed while ensuring summaries and GITHUB_OUTPUT remain encodable.
    return path.decode("utf-8", "replace").replace("\\", "/")


def is_inert(path: bytes) -> bool:
    name = _text(path)
    if (
        name in INERT_ROOT_FILES
        or name in ALWAYS_ON_ONLY_PATHS
        or name.startswith(INERT_PREFIXES)
    ):
        return True
    parts = name.split("/")
    return len(parts) == 3 and parts[0] == "skills" and parts[2] in INERT_SKILL_FILES


def _is_dependency_or_config(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return (
        path in FULL_ROOT_FILES
        or base in {"Pipfile", "poetry.lock", "uv.lock"}
        or base.endswith(DEPENDENCY_SUFFIXES)
    )


def lanes_for_path(path: bytes) -> tuple[str, ...] | None:
    """Return owned lanes, ``()`` for inert, or ``None`` for full fallback."""
    name = _text(path)
    if is_inert(path):
        return ()
    if name.startswith(FULL_PREFIXES) or _is_dependency_or_config(name):
        return None

    # Canonical shared code is a foundation for several skills.  Its own tests are
    # narrow, but changing the implementation must exercise all downstream lanes.
    if name.startswith("automation/shared/"):
        if name.startswith("automation/shared/tests/"):
            return ("shared",)
        return None

    rules = (
        (("automation/publish/",), ("publish",)),
        (("skills/resume-writer/scripts/",), ("render", "resume")),
        (("examples/me/applications/6_drafted/", "examples/fixtures/resume-writer/",
          "examples/me/career/resume/"), ("render", "resume")),
        (("skills/job-search/", "automation/search-recall-audit/"), ("job-search",)),
        (("skills/application-tracker/scripts/", "skills/email-assistant/scripts/",
          "skills/behavioral-interview-prep/scripts/",
          "skills/interview-calendar/"), ("applications",)),
        (("automation/store/", "automation/company-levels/", "examples/store/"),
         ("shared",)),
        (("automation/reconcile/", "automation/gardener/", "automation/hooks/",
          "automation/metrics/", "automation/gates/", "automation/evals/",
          "automation/cutover/", "automation/workspace/",
          "skills/github-workflow/scripts/"), ("maintenance",)),
        (("evals/",), ("maintenance",)),
    )
    for prefixes, lanes in rules:
        if name.startswith(prefixes):
            return lanes

    # Test-free skill guidance and agent metadata do not need long suites.
    if name.startswith("skills/") and (
        name.endswith(".md") or "/agents/" in name
    ):
        return ()
    return None


def full_classification(reason: str, changes: Iterable[Change] = ()) -> Classification:
    return Classification(LANES, True, reason, tuple(changes))


def classify(changes: Sequence[Change]) -> Classification:
    """Select lanes, falling back to all lanes for every unsafe change shape."""
    selected: set[str] = set()
    for change in changes:
        status = change.status
        if status in {"T", "U", "X", "B"}:
            return full_classification(
                f"status {status} cannot be narrowed safely", changes
            )
        if status == "D":
            if not is_inert(change.paths[0]):
                return full_classification(
                    f"non-inert deletion: {_text(change.paths[0])}", changes
                )
            continue
        if status.startswith("R"):
            if not all(is_inert(path) for path in change.paths):
                return full_classification(
                    "non-inert rename: " + " -> ".join(map(_text, change.paths)),
                    changes,
                )
            continue

        # Copies do not remove the source; classify only the destination.
        path = change.paths[1] if status.startswith("C") else change.paths[0]
        owned = lanes_for_path(path)
        if owned is None:
            return full_classification(f"unowned or foundational path: {_text(path)}", changes)
        selected.update(owned)

    lanes = tuple(lane for lane in LANES if lane in selected)
    if not changes:
        reason = "the Git range contains no changes"
    elif not lanes:
        reason = "all changed paths are documentation or process records"
    else:
        reason = "every changed path has a focused CI owner"
    return Classification(lanes, False, reason, tuple(changes))


def git_changes(repository: Path, base: str, head: str) -> tuple[Change, ...]:
    """Read one immutable Git range using the rename-aware NUL format."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", "-z", "-M", base, head, "--"],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise ClassificationError(f"could not execute Git: {error}") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip().replace("\n", " ")
        raise ClassificationError(
            f"git diff exited {result.returncode}" + (f": {detail}" if detail else "")
        )
    return parse_name_status(result.stdout)


def classify_range(repository: Path, base: str, head: str) -> Classification:
    try:
        return classify(git_changes(repository, base, head))
    except (ClassificationError, OSError, ValueError) as error:
        return full_classification(f"fail-closed classifier error: {error}")


def github_outputs(classification: Classification) -> dict[str, str]:
    test_lanes = tuple(
        lane for lane in classification.lanes if lane not in PDF_LANES
    )
    pdf_lanes = tuple(lane for lane in classification.lanes if lane in PDF_LANES)
    return {
        "matrix": json.dumps(classification.matrix, separators=(",", ":")),
        "lanes": json.dumps(list(classification.lanes), separators=(",", ":")),
        "test_matrix": json.dumps(
            {"include": [{"lane": lane} for lane in test_lanes]},
            separators=(",", ":"),
        ),
        "test_lanes": json.dumps(list(test_lanes), separators=(",", ":")),
        "pdf_lanes": json.dumps(list(pdf_lanes), separators=(",", ":")),
        "full": str(classification.full).lower(),
        "reason": classification.reason,
    }


def write_github_outputs(path: Path, outputs: Mapping[str, str]) -> None:
    """Append outputs using GitHub's delimiter form, safe for arbitrary values."""
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in outputs.items():
            delimiter = "__CI_CLASSIFIER_OUTPUT__"
            while delimiter in value:
                delimiter += "_"
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def print_summary(classification: Classification) -> None:
    mode = "FULL" if classification.full else "FOCUSED"
    lanes = ", ".join(classification.lanes) if classification.lanes else "none"
    print(f"CI change classification: {mode}")
    print(f"changed entries: {len(classification.changes)}")
    print(f"long-running lanes: {lanes}")
    print(f"reason: {classification.reason}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base Git revision (requires --head)")
    parser.add_argument("--head", help="head Git revision (requires --base)")
    parser.add_argument(
        "--force-full",
        metavar="REASON",
        help="run every lane without reading a Git range",
    )
    parser.add_argument(
        "--repository", type=Path, default=Path.cwd(), help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="output file (defaults to the GITHUB_OUTPUT environment variable)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    has_range_arg = args.base is not None or args.head is not None
    if args.force_full is not None and has_range_arg:
        parser.error("--force-full is mutually exclusive with --base/--head")
    if args.force_full is None and (args.base is None or args.head is None):
        parser.error("provide --force-full REASON or both --base and --head")
    if args.force_full is not None and not args.force_full.strip():
        parser.error("--force-full REASON must not be blank")

    classification = (
        full_classification(f"forced full matrix: {args.force_full.strip()}")
        if args.force_full is not None
        else classify_range(args.repository, args.base, args.head)
    )
    print_summary(classification)
    output_path = args.github_output
    if output_path is None and os.environ.get("GITHUB_OUTPUT"):
        output_path = Path(os.environ["GITHUB_OUTPUT"])
    if output_path is not None:
        try:
            write_github_outputs(output_path, github_outputs(classification))
        except OSError as error:
            print(f"classifier: could not write GitHub outputs: {error}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
