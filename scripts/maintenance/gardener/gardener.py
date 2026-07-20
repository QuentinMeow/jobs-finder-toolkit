"""gardener front-end — dispatch the memory-hygiene routines.

The gardener keeps this repo's agent-memory zones from growing without bound
(see ``AGENTS.md`` → "Memory Map" for the zones and retention windows). Every
routine DEFAULTS TO DRY-RUN, prints a plan/diff, and MOVES rather than
deletes; ``--apply`` is an explicit opt-in that a human confirms.

Routines:
    expire-discoveries   move discovery scans past their TTL to archive/ (--apply)
    compact-logs         prune stale search-log rows / rebuild derived log (--apply)
    lessons-report       flag stale + near-duplicate LESSONS entries (report-only)
    verify-links         check referenced paths + symlinks + vendor drift (exit 1 on break)
    self-measure         recompute the pipeline funnel + memory metrics (--apply writes yaml)

Usage:
    .venv/bin/python scripts/maintenance/gardener/gardener.py <routine> [--apply]
    .venv/bin/python scripts/maintenance/gardener/gardener.py --all      # every routine, dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compact_logs  # noqa: E402
import expire_discoveries  # noqa: E402
import lessons_report  # noqa: E402
import self_measure  # noqa: E402
import verify_links  # noqa: E402

# Routine name -> (callable taking apply flag or nothing, supports_apply).
ROUTINES = {
    "expire-discoveries": (lambda apply: expire_discoveries.run(apply), True),
    "compact-logs": (lambda apply: compact_logs.run(apply), True),
    "lessons-report": (lambda apply: lessons_report.run(), False),
    "verify-links": (lambda apply: verify_links.run(), False),
    "self-measure": (lambda apply: self_measure.run(apply), True),
}
# Order used by --all (verify-links last so its exit code is the overall gate).
ALL_ORDER = ["self-measure", "expire-discoveries", "compact-logs",
             "lessons-report", "verify-links"]


def run_all() -> int:
    rc = 0
    for name in ALL_ORDER:
        fn, _ = ROUTINES[name]
        print(f"\n{'=' * 78}")
        rc = fn(False) or rc  # always dry-run under --all
    print(f"\n{'=' * 78}\ngardener --all complete (dry-run). "
          "Run an individual routine with --apply to act.")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("routine", nargs="?", choices=sorted(ROUTINES),
                    help="the routine to run")
    ap.add_argument("--apply", action="store_true",
                    help="opt in to writes/moves (ignored by report-only routines and --all)")
    ap.add_argument("--all", action="store_true",
                    help="run every routine in dry-run mode")
    args = ap.parse_args(argv)

    if args.all:
        return run_all()
    if not args.routine:
        ap.error("give a routine name or --all")
    fn, supports_apply = ROUTINES[args.routine]
    if args.apply and not supports_apply:
        print(f"note: '{args.routine}' is report-only; --apply has no effect.")
    return fn(args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
