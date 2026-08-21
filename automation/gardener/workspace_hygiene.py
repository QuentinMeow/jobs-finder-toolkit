"""gardener routine: flag branches and worktrees nobody came back to.

Branches and worktrees accumulate the same way queue items do, and for the same
reason: finishing a piece of work moves attention somewhere else, and nothing
ever comes back to say "this one is done, and its branch is still here". The
measured shape of it in this repository is a row of ``worktree-agent-*``
branches whose content is already in main, plus the occasional registration
whose directory the owner deleted by hand — which silently WEDGES its branch,
because ``git switch`` refuses a branch another worktree claims and ``git gc``
only prunes that metadata after three months.

WHY THIS IS A GARDENER ROUTINE AND NOT A GATE. "This branch has been idle for
three weeks" is a prompt for judgement, not a violated invariant, and the
binding precedent is ``queue_hygiene``: an age threshold in the reconciler
fails EVERY unrelated commit in the repo once the clock runs out. This routine
**always exits 0**. Nothing here blocks anything.

REPORT-ONLY (no ``--apply``). Every remedy is a decision — keep it, finish it,
or retire it — and retiring is its own deliberate command
(``automation/workspace/cleanup.py``, dry-run by default, which writes a script
rather than deleting anything).

WHAT IT PRINTS FOR THE PRIVATE OVERLAY: counts only, never a branch name and
never a path. A branch name in the overlay carries the same identity as a
filename there, and this report is written to be pasted.

Usage:
    .venv/bin/python automation/gardener/gardener.py workspace-hygiene
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

# The dashboard owns what a branch's state IS; this routine reports on the set
# it produces rather than deriving a second, disagreeing definition.
sys.path.insert(0, str(C.REPO_ROOT / "automation" / "workspace"))
import status  # noqa: E402

# ── thresholds ───────────────────────────────────────────────────────────────
#
# Nothing here gates, so each can be tightened without turning a false positive
# into a stopped repo.

# Two weeks with no commit and no edit. Deliberately the same window as
# `queue_hygiene.TASK_MAX_DWELL_DAYS`: a task that has not moved in a fortnight
# and the branch it was being written on are usually the same finding, and two
# different definitions of "stalled" would report them as two.
BRANCH_MAX_IDLE_DAYS = 14

# How many names to print before switching to a count. A report that prints
# forty branch names is a report nobody reads to the end.
NAME_LIMIT = 12

PRIVATE_POLICY = ("counts only — an overlay branch name carries the same "
                  "identity as a filename there")
PRIVATE_MIRROR = "private"

RETIREMENT_COMMAND = "automation/workspace/cleanup.py --fetch"


def scan(root: Path, now: float | None = None) -> dict:
    """Findings for ONE repository. Pure: reads ``root``, prints nothing."""
    result: dict = {
        "root": root, "present": False, "error": None,
        "states": {}, "merged_idle": [], "wedged": [], "idle": [],
        "branches": 0, "worktrees": 0, "base_ref": None, "merge_probe": None,
    }
    if status._git_toplevel(root) != root.resolve():
        return result
    result["present"] = True
    try:
        repo = status.inspect_repository("REPO", root, now=now)
    except status.GitError as error:
        result["error"] = str(error)
        return result

    result["base_ref"] = repo.base_ref
    result["merge_probe"] = repo.merge_probe
    result["worktrees"] = len(repo.worktrees)
    locals_ = [branch for branch in repo.branches if branch.scope != "R"]
    result["branches"] = len(locals_)
    for branch in locals_:
        result["states"][branch.state] = result["states"].get(branch.state, 0) + 1
        days = None if branch.age_seconds is None else branch.age_seconds // 86400
        if branch.state == status.STATE_WEDGED:
            result["wedged"].append({"name": branch.name,
                                     "path": branch.wedged_at, "days": days})
            continue
        if branch.state == status.STATE_MERGED and branch.worktree_path is None:
            result["merged_idle"].append({"name": branch.name, "days": days,
                                          "intent": branch.intent})
            continue
        if days is not None and days >= BRANCH_MAX_IDLE_DAYS:
            result["idle"].append({"name": branch.name, "days": days,
                                   "source": branch.evidence_source,
                                   "intent": branch.intent})
    return result


# ── reporting ────────────────────────────────────────────────────────────────

def _print_public(res: dict, root: Path) -> int:
    findings = 0
    states = " · ".join(f"{count} {name}" for name, count
                        in sorted(res["states"].items())) or "no local branches"
    print(f"  {res['branches']} local branch(es), {res['worktrees']} worktree(s): "
          f"{states}")

    if res["merged_idle"]:
        findings += len(res["merged_idle"])
        # The SOURCE beside the number: this verdict is local. `merged` here
        # means "contained by the ref named below", and that ref was not
        # refreshed, because the dashboard never fetches.
        print(f"  branches whose content is already in {res['base_ref']} with no "
              f"worktree ({len(res['merged_idle'])}) — LOCAL evidence, no fetch "
              f"was performed:")
        for entry in res["merged_idle"][:NAME_LIMIT]:
            age = "unknown age" if entry["days"] is None else f"{entry['days']}d idle"
            print(f"    - {entry['name']} — {age}")
        if len(res["merged_idle"]) > NAME_LIMIT:
            print(f"    … and {len(res['merged_idle']) - NAME_LIMIT} more")
        print(f"    retire them with: {RETIREMENT_COMMAND}  (dry-run; it writes a "
              f"script, it deletes nothing)")
    else:
        print(f"  no branch is both contained by {res['base_ref']} and free of a "
              f"worktree.")

    if res["wedged"]:
        findings += len(res["wedged"])
        print(f"  WEDGED branches ({len(res['wedged'])}) — a worktree registration "
              f"outlived its directory, so `git switch` refuses the branch and "
              f"`git gc` will not clear it for three months:")
        for entry in res["wedged"]:
            where = (status._short_path(entry["path"], root)
                     if entry["path"] is not None else "unknown path")
            print(f"    - {entry['name']} — registration at {where}")
        print("    `git worktree prune` clears the unlocked ones and destroys "
              "nothing; a LOCKED one needs `git worktree unlock <path>` first.")

    if res["idle"]:
        findings += len(res["idle"])
        print(f"  branches idle past {BRANCH_MAX_IDLE_DAYS} days with work not in "
              f"{res['base_ref']} ({len(res['idle'])}):")
        for entry in res["idle"][:NAME_LIMIT]:
            intent = f" — {entry['intent']}" if entry["intent"] else ""
            print(f"    - {entry['name']} — {entry['days']}d "
                  f"[{entry['source']}]{intent}")
        if len(res["idle"]) > NAME_LIMIT:
            print(f"    … and {len(res['idle']) - NAME_LIMIT} more")
    else:
        print(f"  no unmerged branch has been idle past {BRANCH_MAX_IDLE_DAYS} days.")

    if res["merge_probe"] != status.PROBE_MERGE_TREE:
        print(f"  {status.PROBE_DEGRADED_NOTE}")
    return findings


def _print_private(res: dict) -> None:
    """Counts ONLY. See PRIVATE_POLICY for why this half never names a branch."""
    print(f"  {PRIVATE_POLICY}")
    if not res["present"]:
        print(f"  {PRIVATE_MIRROR}/: not a git repository here — nothing to check.")
        return
    if res["error"]:
        print(f"  {PRIVATE_MIRROR}/: could not be inspected.")
        return
    print(f"  {res['branches']} local branch(es), {res['worktrees']} worktree(s)")
    print(f"  contained by its base with no worktree: {len(res['merged_idle'])}")
    print(f"  wedged by a stale worktree registration: {len(res['wedged'])}")
    print(f"  idle past {BRANCH_MAX_IDLE_DAYS} days: {len(res['idle'])}")


def run(apply: bool = False) -> int:
    C.print_header("workspace-hygiene (report-only)", apply=False)
    today = datetime.date.today()
    public = scan(C.REPO_ROOT)
    if not public["present"]:
        print("  this tree is not a git repository — nothing to check.")
    elif public["error"]:
        print(f"  git could not answer: {public['error']}")
    else:
        print(f"  public repo (as of {today}, no fetch):")
        _print_public(public, C.REPO_ROOT)

    mirror = C.REPO_ROOT / PRIVATE_MIRROR
    if mirror.is_dir():
        print(f"  {PRIVATE_MIRROR}/ overlay:")
        _print_private(scan(mirror))

    print("  (report-only — keep it, finish it, or retire it deliberately. "
          "Nothing is blocked meanwhile.)")
    return 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
