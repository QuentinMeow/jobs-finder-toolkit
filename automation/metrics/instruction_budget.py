#!/usr/bin/env python3
"""Static instruction-file token-budget check (anti-bloat guard).

Measures every ``AGENTS.md`` in the tree — the root contract AND every
folder-local leaf, which auto-loads for any agent working in that folder — plus
``skills/*/SKILL.md``, ``LESSONS.md``, and ``reference.md``, and reports lines /
bytes / estimated tokens (bytes / 4). Instruction files are context every agent
session pays for, so each has a hard size budget; exceeding it forces a
consolidation pass, not an exception.

Usage:
    .venv/bin/python automation/metrics/instruction_budget.py           # report + warn, exit 0
    .venv/bin/python automation/metrics/instruction_budget.py --strict  # exit 1 on any violation

Default mode prints a table + any warnings and always exits 0 (measure-only).
``--strict`` exits 1 on violations; the pre-commit hook and CONTRIBUTING checks
run ``--strict`` so the budget is a hard gate.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED = REPO_ROOT / "automation" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

# Budgets. "Warn above" == the check flags the file; with
# --strict it also exits non-zero. reference.md is measured for visibility but
# has no hard budget yet, so it never triggers a warning.
BUDGETS = {
    "SKILL.md": 600,     # target <= 600 lines; warn above
    "LESSONS.md": 160,   # <= 160 lines (~one lesson-bullet block); warn above
    "AGENTS.md": 500,    # the ROOT contract, loaded at boot; warn when > 500 lines
    # A folder-local AGENTS.md leaf is a different tier: pointers, or lines
    # relocated out of an always-loaded file, and nothing else
    # (docs/designs/tree-instructions/README.md, "The three tiers").
    "AGENTS.md (leaf)": 100,
    # The GENERATED store README (map + cookbook) is store-derived, so it is
    # measured ONLY when the store is configured AND the file exists — never in
    # CI (data_root unset). Budgeted in TOKENS (~one SKILL.md's worth) so the
    # cold-read map an agent pays for can't quietly bloat.
    "STORE_README": 700,
}

# Kinds whose budget is compared against estimated TOKENS, not line count.
TOKEN_BUDGET_KINDS = {"STORE_README"}

# Secondary BYTE budgets, checked on top of the line budget above. The leaf tier
# is specified as "<= 100 lines AND <= 4 KiB", and the two are not
# interchangeable: 100 lines of dense prose is roughly twice the KiB figure, so
# a line count alone would let a leaf double in weight without tripping.
BYTE_BUDGETS = {
    "AGENTS.md (leaf)": 4096,
}

# A file at or past this fraction of its budget is reported NEAR. Advisory only: it
# never changes the exit code, in --strict or out of it.
#
# The budget is a cliff, and until now the report said nothing until you were over it.
# The failure that motivated this: a SKILL.md that grew 99 lines in one PR and landed
# at 568 of 600 — under budget, gate green, and 32 lines from forcing an unplanned
# consolidation on whoever edits it next. Whoever that is meets this table, so this is
# where the warning belongs.
#
# 0.90 rather than 0.95 because 568/600 is 94.7%: a threshold that misses the case it
# was written for is decoration. It buys 60 lines of runway on a SKILL.md and 16 on a
# LESSONS.md — enough to plan a considered cut instead of the cheapest one. Measured
# against the tree the day it was added, exactly one file is NEAR, so it is a signal
# and not a second row of noise on every run.
NEAR_BUDGET_FRACTION = 0.90

# Directory names the AGENTS.md walk never descends into: VCS/build/scratch
# trees, and the private overlay (a separate repository, reached through
# ``_private_skills_dir`` instead). Dot-directories are pruned wholesale, which
# also keeps the generated .agents/.claude/.cursor skill adapters out.
WALK_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "local",
    "private",
}

# Rough token estimate. English prose averages ~4 bytes/token; good enough for a
# static bloat tripwire (token count is the budget unit).
BYTES_PER_TOKEN = 4


def _store_readme_target():
    """Yield ``("STORE_README", path)`` when the store is configured and present.

    Conditional by design: the generated README lives inside the private data root,
    so CI (which leaves ``data_root`` unset) never measures it — only a machine with
    a real store does.
    """
    try:
        import config  # automation/shared/config.py
        root = config.data_root()
    except Exception:  # noqa: BLE001
        return
    if root is None:
        return
    readme = Path(root) / "README.md"
    if readme.is_file():
        yield ("STORE_README", readme)


def _private_skills_dir():
    """The overlay's ``skills/`` dir, or None when no overlay is mounted.

    Overlay-only skills used to be measured through inbound symlinks under the
    public ``skills/`` tree. Those links were deleted (a private tree may not wear
    a public name), which would silently have dropped the files from the budget —
    so they are read from the overlay directly instead. Conditional by design,
    exactly like ``_store_readme_target``: CI has no overlay and measures only
    the public files.
    """
    try:
        import config  # automation/shared/config.py
        if not config.overlay_mounted():
            return None
        skills = config.overlay_root() / "skills"
    except Exception:  # noqa: BLE001
        return None
    return skills if skills.is_dir() else None


def _agents_targets(root: Path):
    """Yield (kind, path) for every ``AGENTS.md`` under ``root``.

    Two tiers, two budgets: the file at ``root`` is the boot-time contract, and
    every other one is a folder leaf that auto-loads when an agent reads in that
    folder. Leaves are created reactively, in any folder, so there is no fixed
    list to glob — hence a walk, pruned by ``WALK_SKIP_DIRS``. ``os.walk`` does
    not follow symlinks, so a link pointing back into the tree cannot make one
    file count twice.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in WALK_SKIP_DIRS and not d.startswith(".")
        )
        if "AGENTS.md" not in filenames:
            continue
        path = Path(dirpath) / "AGENTS.md"
        yield ("AGENTS.md" if path.parent == root else "AGENTS.md (leaf)", path)


def _skill_targets(skills: Path, *, include_agents: bool = True):
    """Yield (kind, path) for the instruction files under a ``skills/`` root.

    ``include_agents=False`` for the public ``skills/`` dir, whose ``AGENTS.md``
    files the tree walk above already found; the overlay lives outside that walk
    and still needs them collected here.
    """
    if include_agents:
        for path in sorted(skills.glob("*/AGENTS.md")):
            yield ("AGENTS.md (leaf)", path)
    for name in ("SKILL.md", "LESSONS.md", "reference.md"):
        for path in sorted(skills.glob(f"*/{name}")):
            yield (name, path)


def _iter_targets(root: Path):
    """Yield (kind, path) for each instruction file we budget.

    ``AGENTS.md`` files are found by walking the tree, because a leaf may be
    created in any folder. The per-skill ``SKILL.md`` / ``LESSONS.md`` /
    ``reference.md`` files live at known locations and are globbed, here and in
    the overlay's private ``skills/``.
    """
    yield from _agents_targets(root)

    skills = root / "skills"
    if skills.is_dir():
        yield from _skill_targets(skills, include_agents=False)

    private_skills = _private_skills_dir()
    if private_skills is not None:
        yield from _skill_targets(private_skills)

    yield from _store_readme_target()


def _measure(path: Path):
    """Return (lines, bytes, est_tokens) for a file."""
    data = path.read_bytes()
    n_bytes = len(data)
    # Line count = number of newline-terminated lines (matches ``wc -l``).
    n_lines = data.count(b"\n")
    if data and not data.endswith(b"\n"):
        n_lines += 1
    est_tokens = n_bytes // BYTES_PER_TOKEN
    return n_lines, n_bytes, est_tokens


def build_report(root: Path):
    """Collect measurement rows and the list of budget violations."""
    rows = []
    violations = []
    for kind, path in _iter_targets(root):
        try:
            n_lines, n_bytes, est_tokens = _measure(path)
        except OSError:
            continue
        budget = BUDGETS.get(kind)
        byte_budget = BYTE_BUDGETS.get(kind)
        measure = est_tokens if kind in TOKEN_BUDGET_KINDS else n_lines
        over_primary = budget is not None and measure > budget
        over_bytes = byte_budget is not None and n_bytes > byte_budget
        over = over_primary or over_bytes
        near = not over and (
            (budget is not None and measure >= budget * NEAR_BUDGET_FRACTION)
            or (byte_budget is not None
                and n_bytes >= byte_budget * NEAR_BUDGET_FRACTION))
        try:
            display_path = path.relative_to(root).as_posix()
        except ValueError:
            display_path = str(path)
        rows.append(
            {
                "kind": kind,
                "path": display_path,
                "lines": n_lines,
                "bytes": n_bytes,
                "tokens": est_tokens,
                "budget": budget,
                "byte_budget": byte_budget,
                "over_primary": over_primary,
                "over_bytes": over_bytes,
                "over": over,
                "near": near,
            }
        )
        if over:
            violations.append(rows[-1])
    return rows, violations


def _format_table(rows) -> str:
    header = ("FILE", "LINES", "BYTES", "~TOKENS", "BUDGET", "STATUS")
    display = []
    for r in rows:
        budget = "-" if r["budget"] is None else str(r["budget"])
        if r.get("byte_budget") is not None:
            # Two dimensions, both hard: "<lines>+<bytes>B".
            budget = f"{budget}+{r['byte_budget']}B"
        if r["budget"] is None and r.get("byte_budget") is None:
            status = "n/a"
        elif r["over"]:
            status = "OVER"
        elif r.get("near"):
            status = "NEAR"
        else:
            status = "ok"
        display.append(
            (r["path"], str(r["lines"]), str(r["bytes"]), str(r["tokens"]), budget, status)
        )

    widths = [
        max(len(header[i]), *(len(row[i]) for row in display)) if display else len(header[i])
        for i in range(len(header))
    ]

    def fmt(cols):
        # First column left-justified (file path); numeric columns right-justified.
        cells = [cols[0].ljust(widths[0])]
        cells += [cols[i].rjust(widths[i]) for i in range(1, len(cols))]
        return "  ".join(cells)

    lines = [fmt(header), fmt(tuple("-" * w for w in widths))]
    lines += [fmt(row) for row in display]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on any budget violation (default: warn-only, exit 0)",
    )
    args = parser.parse_args(argv)

    rows, violations = build_report(REPO_ROOT)

    print("Instruction-file budget (lines; est. tokens = bytes / 4):")
    print(_format_table(rows))

    near = [r for r in rows if r.get("near")]
    if near:
        print()
        pct = int(NEAR_BUDGET_FRACTION * 100)
        print(f"{len(near)} file(s) NEAR budget (>= {pct}%) — advisory, never a failure:")
        for r in near:
            if r["budget"] is not None:
                measure = r["tokens"] if r["kind"] in TOKEN_BUDGET_KINDS else r["lines"]
                unit = "tokens" if r["kind"] in TOKEN_BUDGET_KINDS else "lines"
                print(f"  ~ {r['path']}: {measure} of {r['budget']} {unit} "
                      f"({r['budget'] - measure} left)")
            if r["byte_budget"] is not None and r["bytes"] >= r["byte_budget"] * NEAR_BUDGET_FRACTION:
                print(f"  ~ {r['path']}: {r['bytes']} of {r['byte_budget']} bytes "
                      f"({r['byte_budget'] - r['bytes']} left)")
        print("  Plan the next substantive edit to this file as a consolidation pass, "
              "not an addition.")

    if violations:
        print()
        print(f"{len(violations)} file(s) over budget:")
        for v in violations:
            if v["over_primary"]:
                if v["kind"] in TOKEN_BUDGET_KINDS:
                    print(f"  ! {v['path']}: {v['tokens']} tokens > {v['budget']} budget")
                else:
                    print(f"  ! {v['path']}: {v['lines']} lines > {v['budget']} budget")
            if v["over_bytes"]:
                print(f"  ! {v['path']}: {v['bytes']} bytes > {v['byte_budget']} budget")
        if args.strict:
            print("\nFAIL (--strict): instruction-file budget exceeded.")
            return 1
        print("\nWARN: over budget (warn-only; run with --strict to enforce).")
    else:
        print("\nOK: all instruction files within budget.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
