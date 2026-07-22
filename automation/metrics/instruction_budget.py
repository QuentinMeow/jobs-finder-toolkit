#!/usr/bin/env python3
"""Static instruction-file token-budget check (anti-bloat guard).

Measures every ``AGENTS.md``, ``skills/*/SKILL.md``, ``LESSONS.md``, and
``reference.md`` and reports lines / bytes / estimated tokens (bytes / 4).
Instruction files are context every agent session pays for, so each has a hard
size budget; exceeding it forces a consolidation pass, not an exception.

Usage:
    .venv/bin/python automation/metrics/instruction_budget.py           # report + warn, exit 0
    .venv/bin/python automation/metrics/instruction_budget.py --strict  # exit 1 on any violation

Default mode prints a table + any warnings and always exits 0 (measure-only).
``--strict`` exits 1 on violations; the pre-commit hook and CONTRIBUTING checks
run ``--strict`` so the budget is a hard gate.
"""

from __future__ import annotations

import argparse
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
    "AGENTS.md": 500,    # warn when > 500 lines
    # The GENERATED store README (map + cookbook) is store-derived, so it is
    # measured ONLY when the store is configured AND the file exists — never in
    # CI (data_root unset). Budgeted in TOKENS (~one SKILL.md's worth) so the
    # cold-read map an agent pays for can't quietly bloat.
    "STORE_README": 700,
}

# Kinds whose budget is compared against estimated TOKENS, not line count.
TOKEN_BUDGET_KINDS = {"STORE_README"}

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


def _iter_targets(root: Path):
    """Yield (kind, path) for each tracked instruction file we budget.

    Targets live at known locations (repo-root AGENTS.md + per-skill files under
    ``skills/*/``), so we glob those explicitly rather than walking the
    tree — that keeps ``.venv``/``tmp``/gitignored ``references_private`` out.
    """
    for path in sorted(root.glob("AGENTS.md")):
        yield ("AGENTS.md", path)

    skills = root / "skills"
    if skills.is_dir():
        for path in sorted(skills.glob("*/AGENTS.md")):
            yield ("AGENTS.md", path)
        for name in ("SKILL.md", "LESSONS.md", "reference.md"):
            for path in sorted(skills.glob(f"*/{name}")):
                yield (name, path)

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
        measure = est_tokens if kind in TOKEN_BUDGET_KINDS else n_lines
        over = budget is not None and measure > budget
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
                "over": over,
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
        if r["budget"] is None:
            status = "n/a"
        elif r["over"]:
            status = "OVER"
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

    if violations:
        print()
        print(f"{len(violations)} file(s) over budget:")
        for v in violations:
            if v["kind"] in TOKEN_BUDGET_KINDS:
                print(f"  ! {v['path']}: {v['tokens']} tokens > {v['budget']} budget")
            else:
                print(f"  ! {v['path']}: {v['lines']} lines > {v['budget']} budget")
        if args.strict:
            print("\nFAIL (--strict): instruction-file budget exceeded.")
            return 1
        print("\nWARN: over budget (warn-only; run with --strict to enforce).")
    else:
        print("\nOK: all instruction files within budget.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
