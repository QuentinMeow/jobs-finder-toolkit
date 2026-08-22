#!/usr/bin/env python3
"""Audit direct SKILL.md prompt surfaces without exposing their contents.

The report is deliberately structural: it emits the audited file path, numeric
measurements, and fixed category identifiers only.  It never emits a matching
directive, mode phrase, referenced path, heading, or front-matter value.  That
makes the same command safe to run with the separately versioned private overlay
mounted.

Default discovery covers every ``**/SKILL.md`` below ``skills/``,
``private/skills/`` when present, and ``.agents/skills/`` when present.  Symlinked
adapter trees are followed, but files are deduplicated by filesystem identity.
Use ``--skills-root`` to replace the public ``skills/`` root while retaining the
optional private and adapter roots below ``--repo-root``.

Usage::

    .venv/bin/python automation/metrics/skill_prompt_audit.py
    .venv/bin/python automation/metrics/skill_prompt_audit.py --json
    .venv/bin/python automation/metrics/skill_prompt_audit.py --strict

Lexical measurements are advisory.  ``--strict`` fails only when a direct prompt
is over 12,000 estimated tokens, its front-matter description is over 160 words,
or one Markdown section is over 250 lines. Sections at 80 lines still warn;
the higher hard limit keeps the first rollout regression-oriented instead of
making a pre-existing long section fail an otherwise clean checkout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BYTES_PER_TOKEN = 4
SCHEMA_VERSION = 1

# Inclusive advisory thresholds.  Strict thresholds are deliberately exclusive:
# a value exactly at the limit still passes.
DIRECT_TOKEN_WARN = (4_000, 8_000)
DIRECT_TOKEN_STRICT_GT = 12_000
DESCRIPTION_WORDS_WARN = 80
DESCRIPTION_WORDS_STRICT_GT = 160
SECTION_LINES_WARN = 80
SECTION_LINES_STRICT_GT = 250
DIRECTIVE_COUNT_WARN = 40
DIRECTIVE_DENSITY_WARN = 15.0
LITERAL_LINES_WARN = 100
LITERAL_FENCE_LINES_WARN = 40
LOAD_LINES_WARN = 25
BULK_LOADS_WARN = 5
REFERENCE_PATHS_WARN = 50

WORD_RE = re.compile(r"\b[\w]+(?:[-'’][\w]+)*\b", re.UNICODE)
HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+\S")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FRONT_MATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

# These are intentionally simple lexical tripwires, not semantic judgments.
# Their matches never leave this process.
STRONG_DIRECTIVE_RE = re.compile(
    r"\b(?:must(?:\s+not)?|never|always|required|mandatory|cannot|can't|"
    r"do\s+not|don't|shall(?:\s+not)?|only)\b",
    re.IGNORECASE,
)
LOAD_LINE_RE = re.compile(
    r"\b(?:read|load|open|inspect|consult|review|fetch|include|import)\b",
    re.IGNORECASE,
)
BULK_LOAD_RE = re.compile(
    r"\b(?:read|load|open|inspect|review|include|import)\s+"
    r"(?:all|every|the\s+entire|the\s+whole)\b|"
    r"\b(?:recursively|bulk[- ]load|in\s+bulk)\b|"
    r"\brg\s+--files\b|\bfind\b[^\n]*(?:-type\s+f|-name\b)",
    re.IGNORECASE,
)
OPPOSING_MODE_RE = re.compile(
    r"\b(?:except|unless|otherwise|instead|versus|vs\.?|on\s+the\s+other\s+hand)\b",
    re.IGNORECASE,
)
MARKDOWN_TARGET_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
BARE_PATH_RE = re.compile(
    r"(?<![\w`])(?:\.{0,2}/|/)?(?:[A-Za-z0-9_.$*{}<>=~-]+/)+"
    r"[A-Za-z0-9_.$*{}<>=?~-]+"
)
CATEGORY_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def default_skill_roots(
    repo_root: Path,
    public_roots: Sequence[Path] | None = None,
) -> list[Path]:
    """Return explicit/default public roots plus optional overlay/adapter roots."""
    repo_root = repo_root.resolve()
    roots = list(public_roots) if public_roots else [repo_root / "skills"]
    roots.extend((repo_root / "private" / "skills", repo_root / ".agents" / "skills"))

    normalized: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        candidate = root if root.is_absolute() else repo_root / root
        # strict=False preserves clean handling of optional absent roots.
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            normalized.append(candidate)
            seen.add(key)
    return normalized


def _walk_skill_files(root: Path) -> Iterable[Path]:
    """Yield nested SKILL.md files, following symlink dirs without cycles."""
    if not root.is_dir():
        return

    pending = [root]
    seen_dirs: set[tuple[int, int]] = set()
    while pending:
        directory = pending.pop()
        try:
            stat = directory.stat()
        except OSError:
            continue
        directory_id = (stat.st_dev, stat.st_ino)
        if directory_id in seen_dirs:
            continue
        seen_dirs.add(directory_id)

        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name, reverse=True)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    pending.append(entry)
                elif entry.name == "SKILL.md" and entry.is_file():
                    yield entry
            except OSError:
                continue


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def discover_skill_files(
    repo_root: Path,
    public_roots: Sequence[Path] | None = None,
) -> list[tuple[str, Path]]:
    """Return deterministic ``(display_path, real_path)`` skill targets.

    A file reached through public, private, and generated adapter roots is one
    prompt surface, not three.  Filesystem identity also deduplicates hard links.
    The resolved source path is used for display, so an adapter never hides that
    its source belongs to the private overlay.
    """
    repo_root = repo_root.resolve()
    found: dict[tuple[int, int], tuple[str, Path]] = {}
    for root in default_skill_roots(repo_root, public_roots):
        for candidate in _walk_skill_files(root):
            try:
                real = candidate.resolve(strict=True)
                stat = real.stat()
            except OSError:
                continue
            file_id = (stat.st_dev, stat.st_ino)
            display = _display_path(real, repo_root)
            previous = found.get(file_id)
            if previous is None or display < previous[0]:
                found[file_id] = (display, real)
    return sorted(found.values(), key=lambda item: item[0])


def _front_matter(lines: Sequence[str]) -> tuple[list[str], int]:
    if not lines or lines[0].strip() != "---":
        return [], 0
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            return list(lines[1:index]), index + 1
    return [], 0


def _description_words(front_matter: Sequence[str]) -> int:
    for index, line in enumerate(front_matter):
        match = FRONT_MATTER_KEY_RE.match(line)
        if not match or match.group(1) != "description":
            continue

        value = match.group(2).strip()
        pieces: list[str] = []
        if value and not re.fullmatch(r"[>|][+-]?[0-9]*", value):
            pieces.append(value)
        for continuation in front_matter[index + 1 :]:
            if continuation and not continuation[0].isspace():
                break
            pieces.append(continuation.strip())
        return len(WORD_RE.findall(" ".join(pieces)))
    return 0


def _longest_section(lines: Sequence[str], body_start: int) -> int:
    if body_start >= len(lines):
        return 0
    starts = [body_start]
    fence_char: str | None = None
    fence_width = 0
    for index in range(body_start, len(lines)):
        fence = FENCE_RE.match(lines[index])
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char, fence_width = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_width:
                fence_char, fence_width = None, 0
            continue
        if fence_char is None and HEADING_RE.match(lines[index]) and index != body_start:
            starts.append(index)
    ends = [*starts[1:], len(lines)]
    return max((end - start for start, end in zip(starts, ends)), default=0)


def _literal_metrics(lines: Sequence[str]) -> tuple[int, int]:
    total = 0
    longest = 0
    current = 0
    fence_char: str | None = None
    fence_width = 0
    for line in lines:
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char, fence_width = marker[0], len(marker)
                current = 0
            elif marker[0] == fence_char and len(marker) >= fence_width:
                longest = max(longest, current)
                fence_char, fence_width = None, 0
                current = 0
            else:
                current += 1
                total += 1
            continue
        if fence_char is not None:
            current += 1
            total += 1
    if fence_char is not None:
        longest = max(longest, current)
    return total, longest


def _referenced_path_count(text: str) -> int:
    references: set[str] = set()
    for match in MARKDOWN_TARGET_RE.finditer(text):
        references.add(match.group(1).strip("'\"<>.,;:"))
    for match in BACKTICK_RE.finditer(text):
        for token in match.group(1).split():
            cleaned = token.strip("'\"()[]{}<>.,;:")
            if "/" in cleaned:
                references.add(cleaned)
    for match in BARE_PATH_RE.finditer(text):
        references.add(match.group(0).strip("'\"()[]{}<>.,;:"))
    references.discard("")
    return len(references)


def _classify(metrics: dict) -> tuple[list[str], list[str]]:
    categories: list[str] = []
    failures: list[str] = []

    tokens = metrics["direct_estimated_tokens"]
    if tokens >= DIRECT_TOKEN_WARN[1]:
        categories.append("direct_prompt_high")
    elif tokens >= DIRECT_TOKEN_WARN[0]:
        categories.append("direct_prompt_elevated")
    if tokens > DIRECT_TOKEN_STRICT_GT:
        failures.append("direct_prompt_hard_limit")

    description_words = metrics["front_matter_description_words"]
    if description_words >= DESCRIPTION_WORDS_WARN:
        categories.append("description_verbose")
    if description_words > DESCRIPTION_WORDS_STRICT_GT:
        failures.append("description_hard_limit")

    section_lines = metrics["longest_section_lines"]
    if section_lines >= SECTION_LINES_WARN:
        categories.append("long_section")
    if section_lines > SECTION_LINES_STRICT_GT:
        failures.append("section_hard_limit")

    if metrics["strong_directive_count"] >= DIRECTIVE_COUNT_WARN:
        categories.append("directive_count")
    if metrics["strong_directives_per_1k_words"] >= DIRECTIVE_DENSITY_WARN:
        categories.append("directive_density")
    if metrics["literal_lines"] >= LITERAL_LINES_WARN:
        categories.append("literal_volume")
    if metrics["longest_literal_block_lines"] >= LITERAL_FENCE_LINES_WARN:
        categories.append("literal_block_length")
    if metrics["load_instruction_lines"] >= LOAD_LINES_WARN:
        categories.append("load_instruction_volume")
    if metrics["bulk_load_count"] >= BULK_LOADS_WARN:
        categories.append("bulk_loading")
    if metrics["referenced_path_count"] >= REFERENCE_PATHS_WARN:
        categories.append("reference_breadth")

    categories.extend(failures)
    categories = sorted(set(categories))
    failures = sorted(set(failures))
    if not all(CATEGORY_RE.fullmatch(category) for category in (*categories, *failures)):
        raise AssertionError("internal risk category is not sanitized")
    return categories, failures


def measure_skill(path: Path, display_path: str) -> dict:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    front_matter, body_start = _front_matter(lines)
    word_count = len(WORD_RE.findall(text))
    directives = len(STRONG_DIRECTIVE_RE.findall(text))
    literal_lines, longest_literal = _literal_metrics(lines)

    metrics = {
        "path": display_path,
        "direct_estimated_tokens": (len(data) + BYTES_PER_TOKEN - 1) // BYTES_PER_TOKEN,
        "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
        "words": word_count,
        "front_matter_description_words": _description_words(front_matter),
        "longest_section_lines": _longest_section(lines, body_start),
        "strong_directive_count": directives,
        "strong_directives_per_1k_words": round(
            directives * 1_000 / word_count, 2
        ) if word_count else 0.0,
        "literal_lines": literal_lines,
        "longest_literal_block_lines": longest_literal,
        "load_instruction_lines": sum(bool(LOAD_LINE_RE.search(line)) for line in lines),
        "bulk_load_count": sum(bool(BULK_LOAD_RE.search(line)) for line in lines),
        "referenced_path_count": _referenced_path_count(text),
        "opposing_mode_heuristic_count": sum(
            bool(OPPOSING_MODE_RE.search(line)) for line in lines
        ),
    }
    categories, failures = _classify(metrics)
    metrics["risk_categories"] = categories
    metrics["strict_failure_categories"] = failures
    return metrics


def thresholds_payload() -> dict:
    """Return the stable numeric policy recorded beside JSON baselines."""
    return {
        "direct_estimated_tokens": {
            "warn_at": list(DIRECT_TOKEN_WARN),
            "strict_over": DIRECT_TOKEN_STRICT_GT,
        },
        "front_matter_description_words": {
            "warn_at": DESCRIPTION_WORDS_WARN,
            "strict_over": DESCRIPTION_WORDS_STRICT_GT,
        },
        "longest_section_lines": {
            "warn_at": SECTION_LINES_WARN,
            "strict_over": SECTION_LINES_STRICT_GT,
        },
        "strong_directive_count": {"warn_at": DIRECTIVE_COUNT_WARN},
        "strong_directives_per_1k_words": {"warn_at": DIRECTIVE_DENSITY_WARN},
        "literal_lines": {"warn_at": LITERAL_LINES_WARN},
        "longest_literal_block_lines": {"warn_at": LITERAL_FENCE_LINES_WARN},
        "load_instruction_lines": {"warn_at": LOAD_LINES_WARN},
        "bulk_load_count": {"warn_at": BULK_LOADS_WARN},
        "referenced_path_count": {"warn_at": REFERENCE_PATHS_WARN},
    }


def build_audit(
    repo_root: Path,
    public_roots: Sequence[Path] | None = None,
) -> dict:
    rows = [
        measure_skill(real_path, display_path)
        for display_path, real_path in discover_skill_files(repo_root, public_roots)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "thresholds": thresholds_payload(),
        "summary": {
            "files": len(rows),
            "warning_files": sum(bool(row["risk_categories"]) for row in rows),
            "risk_categories": sum(len(row["risk_categories"]) for row in rows),
            "strict_failure_files": sum(
                bool(row["strict_failure_categories"]) for row in rows
            ),
            "strict_failure_categories": sum(
                len(row["strict_failure_categories"]) for row in rows
            ),
        },
        "files": rows,
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _format_table(rows: Sequence[dict]) -> str:
    header = (
        "PATH", "~TOK", "LINES", "DESC", "SEC", "DIR", "D/1K", "LIT",
        "FENCE", "LOAD", "BULK", "REFS", "MODES", "CATEGORIES",
    )
    display = []
    for row in rows:
        display.append((
            row["path"],
            str(row["direct_estimated_tokens"]),
            str(row["lines"]),
            str(row["front_matter_description_words"]),
            str(row["longest_section_lines"]),
            str(row["strong_directive_count"]),
            f"{row['strong_directives_per_1k_words']:.2f}",
            str(row["literal_lines"]),
            str(row["longest_literal_block_lines"]),
            str(row["load_instruction_lines"]),
            str(row["bulk_load_count"]),
            str(row["referenced_path_count"]),
            str(row["opposing_mode_heuristic_count"]),
            ",".join(row["risk_categories"]) or "-",
        ))
    widths = [
        max(len(header[index]), *(len(row[index]) for row in display))
        if display else len(header[index])
        for index in range(len(header))
    ]

    def format_row(columns: Sequence[str]) -> str:
        cells = [columns[0].ljust(widths[0])]
        cells.extend(
            columns[index].rjust(widths[index])
            for index in range(1, len(columns) - 1)
        )
        cells.append(columns[-1].ljust(widths[-1]))
        return "  ".join(cells)

    return "\n".join([
        format_row(header),
        format_row(tuple("-" * width for width in widths)),
        *(format_row(row) for row in display),
    ])


def render_text(report: dict, *, strict: bool = False) -> str:
    lines = [
        "Skill prompt-surface audit (content-safe; lexical/mode metrics advisory):",
        _format_table(report["files"]),
        "",
    ]
    summary = report["summary"]
    lines.append(
        f"{summary['files']} file(s); {summary['warning_files']} with advisory/hard "
        f"categories; {summary['strict_failure_files']} over a strict limit."
    )
    if summary["strict_failure_files"]:
        status = "FAIL (--strict): conservative prompt-surface limit exceeded."
        if not strict:
            status = "WARN: strict limit exceeded (rerun with --strict to enforce)."
        lines.append(status)
    else:
        lines.append("OK: no conservative prompt-surface limit exceeded.")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository root used for defaults and relative display paths",
    )
    parser.add_argument(
        "--skills-root",
        action="append",
        type=Path,
        dest="public_roots",
        help="public skills root (repeatable; replaces the default skills/ root)",
    )
    parser.add_argument("--json", action="store_true", help="emit stable JSON only")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 only on the three conservative hard limits",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_audit(args.repo_root, args.public_roots)
    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report, strict=args.strict))
    return 1 if args.strict and report["summary"]["strict_failure_files"] else 0


if __name__ == "__main__":
    sys.exit(main())
