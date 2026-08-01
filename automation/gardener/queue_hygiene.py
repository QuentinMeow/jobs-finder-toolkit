"""gardener routine: flag aging items in the coordination queues (message-queue/ + tasks/).

The queues are where the owner and the agents talk to each other across sessions.
Everything in them is designed NOT to block: a `decisions/` item states a default
path agents follow while it is pending, a `clarifications/` item states an
assumption, a `reviews/` item is explicitly safe to ignore, and a task's status is
just the folder it sits in. That is the right design and it has one predictable
failure mode — **nothing ever comes back to say an item got old**. A decision
pending for a month means agents have been running on a guessed default for a
month; a task that has sat in `1_in-progress` since it was claimed is either
stalled or forgotten; a `reviews/` item past the 30-day sweep is litter.

WHY THIS IS A GARDENER ROUTINE AND NOT A RECONCILER CHECK. "This item is 40 days
old" is a prompt for judgement, not a violated invariant. The reconciler is a
blocking gate — pre-commit and CI, exit 1 on any finding — so an age flag added
there would fail **every unrelated commit in the repo** until somebody groomed a
backlog. That is an outage produced by a grooming reminder, the same trap
``roadmap-staleness`` was moved here to escape. The reconciler keeps the
correctness half (``check_queue_schema``/``check_task_structure``: a malformed
item is a defect the committing agent can fix in seconds); age lives here.

REPORT-ONLY (no ``--apply``): every remedy is a human judgement — answer it,
un-stall it, or delete it. Nothing here is safe to automate, so nothing is.
**Always exits 0** — ``verify-links`` remains the ``--all`` gate.

WHAT IT PRINTS FOR THE PRIVATE MIRROR: counts only, never a filename. See
:data:`PRIVATE_POLICY` below — that rule is the reason this routine is safe to
paste into a PR description, which is the one thing ``verify-links`` output is not.

Usage:
    .venv/bin/python automation/gardener/queue_hygiene.py
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# The reconciler owns what a task folder IS (it gates on the name and the required
# files), so this routine imports its definitions rather than carrying a second copy.
# A reminder that disagreed with the gate about which folders are tasks would report
# on a set nobody else recognises. reconcile.py is stdlib-only and does no work at
# import time.
sys.path.insert(0, str(C.REPO_ROOT / "automation" / "reconcile"))
import reconcile  # noqa: E402

# ── thresholds ───────────────────────────────────────────────────────────────
#
# None of these gate anything, so each can be tightened without turning a false
# positive into a stopped repo. They are deliberately NOT one shared number: the
# cost of an aging item differs by queue.

# `reviews/`: not a choice — AGENTS.md's boot ritual already says agents sweep
# reviews "older than 30 days". This routine reports what that rule would sweep,
# rather than inventing a second definition of old for the same folder.
REVIEW_MAX_AGE_DAYS = 30

# `decisions/`: shorter than the review window on purpose. An unread review costs
# nothing while it waits — "doing nothing must be safe" is that queue's contract.
# A pending decision costs continuously: agents are executing its default path, so
# every extra week is more work built on a guess the owner has not confirmed.
# Three weeks is long enough to survive an owner who is away, short enough that
# default-path drift surfaces while it is still cheap to unwind.
DECISION_MAX_AGE_DAYS = 21

# `tasks/`: two weeks in one status. In the window this was written for, in-review
# tasks were reaching review within ten days of being filed, so a fortnight is
# ~2x the observed lifecycle — long enough that a normally-moving task never trips
# it, short enough to catch the ones nobody came back to.
TASK_MAX_DWELL_DAYS = 14

# The two statuses that mean "someone is mid-flight". `0_backlog` is excluded
# deliberately — an old backlog item is a backlog, not a problem, and D3 of the
# process-weight decision argues at length that counting them is the wrong lever.
# `2_blocked` is excluded because its wait is by definition somebody else's;
# `4_done` has its own ~90-day prune in tasks/README.md.
DWELL_STATUSES = ("1_in-progress", "3_in-review")

# What this routine may print about items under the private overlay.
#
# The rule: COUNTS ONLY — never a filename, a title, or a field value.
#
# Three reasons, in order of weight.
# 1. In the private mirror the filename IS the content. message-queue/README.md
#    routes items there precisely when they name "the owner's real
#    pipeline/identity", and the naming rule is a kebab slug of the item's
#    subject — so `<real-company>-onsite-loop-scheduling.md` is a leak with no
#    body attached.
# 2. This report is written to be pasted — into chat, a handover, a PR
#    description. `verify-links` takes the opposite stance and consequently has
#    to carry a standing "never paste a run into a PR" warning in
#    `skills/gardener/SKILL.md`. A report that needs a warning label is a report
#    that will eventually be pasted anyway, by the one agent who did not read it.
# 3. Nothing downstream would catch the mistake: the leak guard scans tracked
#    FILES, not a routine's stdout, so a private slug printed here reaches a
#    public PR with every mechanical detector silent.
# There is deliberately no --private-detail flag: it would re-arm exactly what
# this design removes, and the only person who can read those items can `ls` the
# folder they are already counted from.
PRIVATE_POLICY = "counts only — private item names are content (see PRIVATE_POLICY)"

# Where the private mirrors live (AGENTS.md, "Async Collaboration" / "Process Folders").
PRIVATE_MIRROR = "private"
MIRROR_HINT = f"{PRIVATE_MIRROR}/message-queue/ and {PRIVATE_MIRROR}/tasks/"

_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# ``- **Key**: value`` — the same bold-key line shape the reconciler's ``_has_key``
# gates on. The gate proves the key is THERE; this reads what it says.
_STAGE_HEADING_RE = re.compile(r"^#{2,4}\s+Stage\s+(?P<id>\d+[a-z]?)\b(?P<rest>.*)$", re.I)
_STAGE_REF_RE = re.compile(r"stage\s+(\d+[a-z]?)", re.I)
SHIPPED_MARKER = "SHIPPED"


def _field(text: str, key: str) -> str | None:
    """Value of a ``- **Key**: value`` line, folding indented continuation lines.

    Continuations matter: a ``Revisit when`` condition routinely wraps, and reading
    only its first line would miss the stage number that makes it checkable.
    """
    pattern = re.compile(rf"^- \*\*{re.escape(key)}\??\*\*\s*:\s*(?P<value>.*)$")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        value = [m.group("value").strip()]
        for cont in lines[i + 1:]:  # indented + non-blank == still this value
            if cont[:1] in (" ", "\t") and cont.strip():
                value.append(cont.strip())
                continue
            break
        return " ".join(value).strip()
    return None


def _first_iso(value: str | None) -> datetime.date | None:
    """The first ``YYYY-MM-DD`` in ``value`` — Filed lines carry trailing prose."""
    if not value:
        return None
    m = _ISO_RE.search(value)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _read(path: Path) -> str:
    """File text, tolerating anything. A hygiene reminder must not die on a bad byte."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _md_items(folder: Path) -> list[Path]:
    """Markdown items in a queue folder (READMEs and non-md files excluded).

    Mirrors ``reconcile._items``; kept local rather than imported because that
    helper is private to the gate.
    """
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.suffix == ".md" and p.name != "README.md" and p.is_file())


def _last_worklog_date(task_dir: Path) -> datetime.date | None:
    """Newest ``## YYYY-MM-DD — session n`` heading in the task's worklog, if any."""
    worklog = task_dir / "worklog.md"
    if not worklog.is_file():
        return None
    dates = [d for line in _read(worklog).splitlines()
             if line.startswith("## ") and (d := _first_iso(line))]
    return max(dates) if dates else None


def shipped_stages(design_roots: list[Path]) -> dict[str, set[str]]:
    """``{design-slug: {stage-id marked SHIPPED}}`` from each execution-plan.md.

    A stage is "shipped" when its own heading says so — the execution plans in
    ``docs/designs/*/`` already record it that way (``## Stage 3 — pipeline
    integration — SHIPPED (PR #52)``), which is why no git history is needed and
    why this keeps working in an exported tree.
    """
    out: dict[str, set[str]] = {}
    for root in design_roots:
        if not root.is_dir():
            continue
        for plan in sorted(root.glob("*/execution-plan.md")):
            stages: set[str] = set()
            for line in _read(plan).splitlines():
                m = _STAGE_HEADING_RE.match(line)
                if m and SHIPPED_MARKER in m.group("rest").upper():
                    stages.add(m.group("id").lower())
            if stages:
                out.setdefault(plan.parent.name, set()).update(stages)
    return out


def _revisit_hit(revisit: str, shipped: dict[str, set[str]]) -> tuple[str, str] | None:
    """``(design-slug, stage-id)`` when a revisit condition names a SHIPPED stage."""
    lowered = revisit.lower()
    stages = {m.group(1).lower() for m in _STAGE_REF_RE.finditer(lowered)}
    if not stages:
        return None
    for slug, done in sorted(shipped.items()):
        if slug in lowered:
            for stage in sorted(stages & done):
                return slug, stage
    return None


def scan(root: Path, today: datetime.date,
         design_roots: list[Path] | None = None) -> dict:
    """Aging findings for ONE tree (the public root, or the private mirror).

    Pure: reads ``root``, prints nothing, and never touches the repo it was not
    handed. ``design_roots`` are the ``docs/designs/`` folders whose execution
    plans resolve a parked item's revisit condition.
    """
    queue = root / "message-queue"
    tasks = root / "tasks"
    result: dict = {
        "root": root,
        "queue_present": queue.is_dir(),
        "tasks_present": tasks.is_dir(),
        "reviews": [], "reviews_total": 0,
        "decisions": [], "decisions_total": 0,
        "tasks": [], "tasks_total": 0,
        "parked": [], "parked_total": 0,
        "undated": [],
    }
    result["present"] = result["queue_present"] or result["tasks_present"]
    if not result["present"]:
        return result

    shipped = shipped_stages(design_roots or [])

    for item in _md_items(queue / "needs-human/reviews"):
        result["reviews_total"] += 1
        text = _read(item)
        filed = _first_iso(_field(text, "Filed"))
        if filed is None:
            result["undated"].append({"name": item.name, "queue": "reviews"})
            continue
        age = (today - filed).days
        if age > REVIEW_MAX_AGE_DAYS:
            result["reviews"].append({"name": item.name, "filed": filed, "age": age})

    for item in _md_items(queue / "needs-human/decisions"):
        result["decisions_total"] += 1
        text = _read(item)
        status = (_field(text, "Status") or "").lower()
        filed = _first_iso(_field(text, "Filed"))
        parked = "parked" in status
        if parked:
            result["parked_total"] += 1
            # A parked item is deferred ON PURPOSE, so its age is not a finding —
            # its revisit CONDITION is. AGENTS.md tells agents to skip parked items
            # "unless their revisit condition matches this session's work", and
            # nothing ever re-reads them to notice the condition came true.
            hit = _revisit_hit(_field(text, "Revisit when") or "", shipped)
            if hit:
                result["parked"].append({"name": item.name, "design": hit[0],
                                         "stage": hit[1], "filed": filed})
            continue
        if filed is None:
            result["undated"].append({"name": item.name, "queue": "decisions"})
            continue
        age = (today - filed).days
        if age > DECISION_MAX_AGE_DAYS:
            result["decisions"].append({"name": item.name, "filed": filed, "age": age})

    for status in DWELL_STATUSES:
        sdir = tasks / status
        if not sdir.is_dir():
            continue
        for entry in sorted(sdir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            result["tasks_total"] += 1
            # Best available "last touched", newest first: a dated worklog entry
            # (written by the session that worked it), else the filed date encoded
            # in the task id. The id date is an UPPER bound on dwell — a task filed
            # in March and claimed yesterday still reads as months old — so the
            # source is reported alongside the number rather than hidden in it.
            stamp, source = _last_worklog_date(entry), "worklog"
            if stamp is None:
                stamp, source = _first_iso(entry.name), "filed"
            if stamp is None:
                if not reconcile.TASK_ID_RE.match(entry.name):
                    # A malformed folder name is the reconciler's finding, not ours.
                    continue
                result["undated"].append({"name": entry.name, "queue": status})
                continue
            age = (today - stamp).days
            if age > TASK_MAX_DWELL_DAYS:
                result["tasks"].append({"id": entry.name, "status": status,
                                        "age": age, "source": source, "stamp": stamp})
    return result


# ── reporting ────────────────────────────────────────────────────────────────

def _print_public(res: dict) -> None:
    findings = 0
    if res["queue_present"]:
        if res["reviews"]:
            findings += len(res["reviews"])
            print(f"  reviews/ past {REVIEW_MAX_AGE_DAYS} days "
                  f"({len(res['reviews'])} of {res['reviews_total']}):")
            for r in res["reviews"]:
                print(f"    - {r['name']} — filed {r['filed']}, {r['age']} days")
        else:
            print(f"  reviews/: none past {REVIEW_MAX_AGE_DAYS} days "
                  f"({res['reviews_total']} item(s)).")

        if res["decisions"]:
            findings += len(res["decisions"])
            print(f"  decisions/ pending past {DECISION_MAX_AGE_DAYS} days "
                  f"({len(res['decisions'])} of {res['decisions_total']}):")
            for d in res["decisions"]:
                print(f"    - {d['name']} — filed {d['filed']}, {d['age']} days")
        else:
            print(f"  decisions/: none pending past {DECISION_MAX_AGE_DAYS} days "
                  f"({res['decisions_total']} item(s)).")

        if res["parked"]:
            findings += len(res["parked"])
            print(f"  parked decisions whose revisit condition has SHIPPED "
                  f"({len(res['parked'])} of {res['parked_total']} parked):")
            for p in res["parked"]:
                print(f"    - {p['name']} — waits on {p['design']} stage "
                      f"{p['stage']}, which its execution plan marks SHIPPED")
        elif res["parked_total"]:
            print(f"  parked decisions: {res['parked_total']}, none whose revisit "
                  "condition names a shipped stage.")

    if res["tasks_present"]:
        if res["tasks"]:
            findings += len(res["tasks"])
            print(f"  tasks dwelling past {TASK_MAX_DWELL_DAYS} days in "
                  f"{'/'.join(DWELL_STATUSES)} ({len(res['tasks'])} of {res['tasks_total']}):")
            for t in res["tasks"]:
                note = "last worklog entry" if t["source"] == "worklog" else "filed (upper bound)"
                print(f"    - {t['id']} — {t['status']}, {t['age']} days "
                      f"[{note} {t['stamp']}]")
        else:
            print(f"  tasks: none dwelling past {TASK_MAX_DWELL_DAYS} days in "
                  f"{'/'.join(DWELL_STATUSES)} ({res['tasks_total']} item(s)).")

    if res["undated"]:
        print(f"  no parseable date ({len(res['undated'])}) — age unknown, not counted:")
        for u in res["undated"]:
            print(f"    - {u['queue']}/{u['name']}")

    if not findings:
        print("  nothing aging past its threshold.")


def _print_private(res: dict) -> None:
    """Counts ONLY. See PRIVATE_POLICY for why this half never names an item."""
    print(f"  {PRIVATE_POLICY}")
    if not res["present"]:
        print(f"  {PRIVATE_MIRROR}/message-queue + {PRIVATE_MIRROR}/tasks: "
              "not mounted — nothing to check.")
        return
    print(f"  reviews/ past {REVIEW_MAX_AGE_DAYS}d: {len(res['reviews'])} "
          f"of {res['reviews_total']}")
    print(f"  decisions/ pending past {DECISION_MAX_AGE_DAYS}d: "
          f"{len(res['decisions'])} of {res['decisions_total']}")
    print(f"  parked decisions on a shipped stage: {len(res['parked'])} "
          f"of {res['parked_total']} parked")
    print(f"  tasks dwelling past {TASK_MAX_DWELL_DAYS}d: {len(res['tasks'])} "
          f"of {res['tasks_total']}")
    if res["undated"]:
        print(f"  items with no parseable date: {len(res['undated'])}")
    total = (len(res["reviews"]) + len(res["decisions"])
             + len(res["parked"]) + len(res["tasks"]))
    if total:
        print(f"  open {MIRROR_HINT} to see which — this routine will not name them.")


def run(apply: bool = False) -> int:
    C.print_header("queue-hygiene (report-only)", apply=False)
    today = C.today()
    public_designs = C.REPO_ROOT / "docs" / "designs"
    public = scan(C.REPO_ROOT, today, [public_designs])

    if not public["present"]:
        # The published export ships neither message-queue/ nor tasks/; so does a
        # contributor clone that has not adopted the process folders.
        print("  no message-queue/ or tasks/ in this tree — nothing to check.")
    else:
        print(f"  public tree (as of {today}):")
        _print_public(public)

    mirror = C.REPO_ROOT / PRIVATE_MIRROR
    if mirror.is_dir():
        print(f"  {PRIVATE_MIRROR}/ mirror:")
        _print_private(scan(mirror, today, [public_designs, mirror / "docs" / "designs"]))

    print("  (report-only — answer, un-stall, or delete. Nothing is blocked meanwhile.)")
    return 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
