"""gardener routine: flag docs/roadmap/current-state.md when its date has aged out.

``docs/roadmap/current-state.md`` says what is true about this repo TODAY, and the
read order routes agents to it for exactly that. A ``Last-updated`` line nobody has
touched in a month means the document is describing a repo that has moved on.

WHY THIS IS A GARDENER ROUTINE AND NOT A GATE. Age was briefly enforced by the
reconciler's ``roadmap-dated`` check, which runs in ``automation/hooks/pre-commit``
and CI. With a 30-day window and a roadmap dated 2026-07-31, every commit in the repo
— a one-line fix to an unrelated script included — would have started failing on
2026-08-31 until somebody re-dated a planning document. That is an outage produced by
a grooming reminder. The MALFORMED cases stayed in the gate, where they belong (no
``desired-state.md``, an unparseable date, a future date: each is a defect in the file
the committing agent introduced or can fix in seconds). Age moved here, which is where
this repo already keeps its age flags — stale LESSONS sections, a drifted tailoring
card, expired discovery scans — surfaced on a sweep to a human who can act on them.

REPORT-ONLY (no ``--apply``): re-dating the roadmap means first making it true again,
which is a human's judgment, not a timestamp bump. **Always exits 0** — ``verify-links``
remains the ``--all`` gate.

Usage:
    .venv/bin/python automation/gardener/roadmap_staleness.py
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# The reconciler owns the roadmap's date FORMAT (it gates on the malformed cases), so
# this routine imports its parser rather than carrying a second copy of the regex.
# Two readers of one line that disagree about how to read it is the failure this
# import exists to make impossible. reconcile.py is stdlib-only and does no work at
# import time.
sys.path.insert(0, str(C.REPO_ROOT / "automation" / "reconcile"))
import reconcile  # noqa: E402

# How old ``current-state.md`` may be before this routine calls it stale.
#
# 30 days is this repo's existing definition of "old": message-queue reviews are swept
# at 30 days and discovery scans carry a 30-day hard TTL. It is also ~10x the observed
# cadence — current-state.md was rewritten eight times in the ten days before this
# number was chosen — so a roadmap that trips it is stale by any reading, not merely
# quiet. Nothing blocks when it trips, so the number can be tightened without turning
# a false positive into a stopped repo.
MAX_AGE_DAYS = 30


def analyze(today: datetime.date | None = None) -> dict:
    """``{path, exists, raw, stamp, age, stale}`` for the roadmap's current state."""
    current = C.REPO_ROOT / "docs" / "roadmap" / "current-state.md"
    result = {"path": current, "exists": current.is_file(), "raw": None,
              "stamp": None, "age": None, "stale": False}
    if not result["exists"]:
        return result
    raw, stamp = reconcile.parse_last_updated(current.read_text(encoding="utf-8"))
    result["raw"], result["stamp"] = raw, stamp
    if stamp is None:
        return result
    age = ((today or datetime.date.today()) - stamp).days
    result["age"] = age
    result["stale"] = age > MAX_AGE_DAYS
    return result


def run(apply: bool = False, today: datetime.date | None = None) -> int:
    C.print_header("roadmap-staleness (report-only)", apply=False)
    res = analyze(today=today)
    if not res["exists"]:
        # The published export ships no docs/roadmap/; so does a contributor clone
        # that has not adopted the process folders.
        print("  no docs/roadmap/current-state.md in this tree — nothing to check.")
        return 0
    print(f"  file: {C.rel(res['path'])}")
    if res["raw"] is None:
        print("  no Last-updated line — the reconciler's roadmap-dated gate reports this.")
        return 0
    if res["stamp"] is None:
        print(f"  Last-updated: {res['raw']!r} is not an ISO date — "
              "the reconciler's roadmap-dated gate reports this.")
        return 0
    if res["age"] < 0:
        print(f"  Last-updated: {res['raw']} is in the future — "
              "the reconciler's roadmap-dated gate reports this.")
        return 0
    if res["stale"]:
        print(f"  STALE: Last-updated {res['raw']} is {res['age']} days old "
              f"(limit {MAX_AGE_DAYS}).")
        print("  (report-only — describe what is true today, then re-date it. "
              "Nothing is blocked meanwhile.)")
    else:
        print(f"  current — Last-updated {res['raw']}, {res['age']} day(s) old "
              f"(limit {MAX_AGE_DAYS}).")
    return 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
