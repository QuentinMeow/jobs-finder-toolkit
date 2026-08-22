#!/usr/bin/env python3
"""Merge a pull request in this repo — after classifying WHICH OF TWO WORLDS it is in.

This repo contains two kinds of pull request, and **they need opposite commands**.
Nothing in `gh` (2.94.0) tells them apart, and every human-readable signal — the
UI, the API's success reply, CI — looks the same in both. So the classification is
not advice, it is the first step, and it is why this is a script instead of prose.

**World A — a member of a native GitHub stack.** A stack here is a first-class
server-side object with its own number, drawn from the same sequence as PR numbers
(which is why `gh pr view 190` says "Could not resolve to a PullRequest": 190 is a
stack). A stack member **cannot be merged by `gh pr merge`** — the API answers
HTTP 403. It must go through `PUT repos/{owner}/{repo}/pulls/{n}/merge-async`.
Inside a stack, GitHub rebases the next entry onto the stack base by itself, so a
member's base is never hand-edited.

**World B — an ordinary PR (`stackEntry` is null).** `gh pr merge --merge` is the
command, and **nothing retargets anything, ever**. The next PR up must be
retargeted explicitly, after its base has merged — and the retarget must then be
READ BACK, because an unverified retarget is the same bug as no retarget.

**Why the assertion differs per world.** For a stacked PR, `baseRefName == "main"`
proves nothing: entries read `main` whether or not they sit at the bottom. The
bottom is `stackEntry.position == 1` (1-based, 1 = bottom). For a non-stacked PR,
`baseRefName` is the whole guard — this is the check that would have caught the
merge of `#198` into an already-merged branch 84 seconds after its base landed.

**Why the exit code is not the result.** The async PUT returns HTTP 202 with
`{"status": "pending", "details": {"uuid": ...}}`, and `gh` exits 0. That is a
RECEIPT, not a merge. The outcome arrives from `GET .../merge-async/<uuid>`, whose
terminal states are `merged`, `failed`, and `enqueued` — and `enqueued` (a merge
queue took the request) is terminal WITHOUT being merged. So this script polls to a
terminal state and then confirms independently with `GET repos/{o}/{r}/pulls/{n}/merge`
(HTTP 204 = merged, 404 = not), which keeps working after the async record expires.
If the two sources disagree, it refuses rather than reporting either one.

DRY RUN IS THE DEFAULT. Nothing merges without `--execute`.

Refusals (all non-zero, never best-effort — this script has no "try anyway" path):

  * a non-stacked PR whose base is not the intended base (the `#198` guard);
  * a stacked PR whose `position` is not 1, unless `--atomic` names the complete
    contiguous prefix (positions 1..k) that will be swept on purpose;
  * a head SHA that moved between classification and merge;
  * a PR that is draft, closed, or already merged;
  * an atomic sweep member whose latest-commit check rollup is not `SUCCESS`,
    or whose rollup cannot be proven from GraphQL;
  * the poll ceiling reached while the request is still `pending`;
  * a terminal `enqueued` — the merge queue has it, it is not on the trunk;
  * the async record and the merge-confirmation endpoint disagreeing;
  * classification unavailable (the `/stacks` idea or the `stackEntry` field gone) —
    with no way to tell the worlds apart, guessing a track is the failure mode this
    script exists to remove.

`--squash`, `--rebase`, and `--delete-branch` are rejected at argument parsing and
are not offered: the first two rewrite every SHA on the branch, orphaning the
review-ledger rows keyed to those commit ranges, and deleting a base branch CLOSES
the PR above it (this happened to `#136`) besides making the rewritten commits
unreachable in a fresh clone. `gh pr merge --auto` is not a fallback either:
`allow_auto_merge` is false on this repo, and GitHub does not offer auto-merge for
stacks.

THE POST-MERGE CUTOVER, and why it lives here of all places. Agent work leaves
orphan branches and a main checkout that drifts behind `origin/main` — measured at
88 commits behind in one session, a state in which a tool written that morning did
not exist in the owner's working tree at all. The cause is not a missing tool: a
planner (`automation/workspace/cleanup.py`) and a dashboard
(`automation/workspace/status.py`) both exist, and the dashboard is mandated as
every session's first command. The cause is that **at the moment cleanup becomes
possible, no process is running** — cleanup needs the merge to be visible in
`origin/main`, which needs a fetch, and the agent's session ends AT the merge.

Exactly one process is alive at that moment, and it already holds every fact
needed: this script. So after each independently confirmed merge it fetches,
fast-forwards `main` in the MAIN working tree, and prints a two-SHA RECEIPT —
`<before>..<after>, N commits` — on every run, including `N == 0` and including a
run it refused. A receipt is the point: a warning banner can be reported green, a
pair of SHAs cannot.

What the cutover will not do, ever: it never merges, rebases, resets, stashes, or
checks out anything (`git merge --ff-only` is the only tree-changing command); it
never deletes a REMOTE branch (`delete_branch_on_merge` is off here on purpose —
deleting a base branch closed `#136` one second later — and remote sweeping is an
open owner decision whose default path is "no agent deletes a remote branch"); it
never removes a worktree; and it retires a local branch only with `git branch -d`,
only when no worktree holds it, and only after `git merge-tree --write-tree` proves
`origin/main` already contains its content. Refusing to cut over is NEVER a failed
merge: the merge already happened, so a refusal prints a `CUTOVER REFUSED` block
plus the receipt and leaves the exit code alone. `--no-cutover` skips the whole
step; the cutover never runs during a dry run.

Usage:

    .venv/bin/python skills/github-workflow/scripts/merge_stack.py 41 42
    .venv/bin/python skills/github-workflow/scripts/merge_stack.py --execute 41

Exit codes: 0 = the plan printed (dry run) or every named PR merged and was
confirmed; 1 = a refusal or a failed merge; 2 = a usage error.

This script shells out to `gh` and to local `git`, and to nothing else. It imports
no repo-root Python (`docs/handbook/skills-and-vendoring.md`) and makes no direct
HTTP call. It writes no file of its own; the only state it changes is what the
cutover changes in the local repository — remote-tracking refs from a fetch, a
fast-forwarded local `main`, and a `git branch -d` of a branch already contained in
`origin/main`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DEFAULT_BASE = "main"
DEFAULT_REMOTE = "origin"
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_POLL_CEILING_S = 300.0

#: Rejected before anything runs. The value is the reason printed to the caller.
BANNED_FLAGS = {
    "--squash": (
        "a squash merge rewrites every SHA on the branch, so every review-ledger "
        "row keyed to those commits is orphaned"
    ),
    "-s": "same as --squash",
    "--rebase": (
        "a rebase merge rewrites every SHA on the branch, so every review-ledger "
        "row keyed to those commits is orphaned"
    ),
    "-r": "same as --rebase",
    "--delete-branch": (
        "deleting a base branch CLOSES the PR above it (#136), and it makes the "
        "rewritten commits unreachable, degrading orphaned ledger rows to UNKNOWN "
        "OBJECT in a fresh clone"
    ),
    "-d": "same as --delete-branch",
}

CLASSIFY_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      state
      isDraft
      baseRefName
      headRefName
      headRefOid
      mergeable
      commits(last: 1) {
        nodes {
          commit {
            oid
            statusCheckRollup { state }
          }
        }
      }
      stackEntry {
        position
        stack { number size }
      }
    }
  }
}
"""

#: Every field the two tracks are decided from. A missing one is a refusal, not a
#: default: `stackEntry: null` is a legitimate answer ("not stacked"), an ABSENT
#: `stackEntry` key means the API no longer answers the question at all.
#:
#: `headRefName` is DELIBERATELY not in here. Nothing about the merge depends on
#: it — it is only the name of the local branch the cutover may retire — so its
#: absence must degrade that one optional step, not refuse a merge that is
#: otherwise fully determined.
REQUIRED_FIELDS = ("number", "state", "isDraft", "baseRefName", "headRefOid",
                   "stackEntry")

_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class Refusal(Exception):
    """A condition this script will not work around. Always exits non-zero."""


# --------------------------------------------------------------------------- gh


def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run one `gh` invocation; return (exit code, stdout, stderr).

    Never a pipeline. `$?` after a pipeline is the LAST stage's status, so a red
    gate read through `| tail` reads as green (`AGENTS.md` -> Shell & Paths). Here
    the status comes straight off the process object, and both streams are captured
    rather than piped anywhere.
    """
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as exc:  # gh not installed / not on PATH
        raise Refusal(f"cannot run `gh`: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def _http_status(*streams: str) -> int | None:
    """The HTTP status `gh` reported, if it reported one."""
    for stream in streams:
        match = _HTTP_STATUS_RE.search(stream or "")
        if match:
            return int(match.group(1))
    return None


def _dig(payload, *keys):
    """Walk nested dicts without raising on a null branch."""
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_uuid(*streams: str) -> str | None:
    for stream in streams:
        match = _UUID_RE.search(stream or "")
        if match:
            return match.group(0)
    return None


def resolve_repo(explicit: str | None) -> str:
    """`OWNER/NAME`, from `--repo` or from `gh repo view`."""
    if explicit:
        parts = explicit.split("/")
        if len(parts) != 2 or not all(parts):
            raise Refusal(f"--repo {explicit!r} is not OWNER/NAME")
        return explicit
    code, out, err = _run_gh(["repo", "view", "--json", "nameWithOwner",
                              "--jq", ".nameWithOwner"])
    if code != 0:
        raise Refusal("cannot resolve the repository from the current directory "
                      f"({(err or out).strip()}). Pass --repo OWNER/NAME.")
    name = out.strip()
    if "/" not in name:
        raise Refusal(f"`gh repo view` returned {name!r}, which is not OWNER/NAME")
    return name


# ---------------------------------------------------------------- classification


def _not_a_pull_request(repo: str, number: int) -> str:
    """The message for a number GitHub will not resolve to a PR.

    Worth its own wording because the obvious reading — "the PR was deleted" —
    is usually wrong here: a STACK is a first-class object that takes a number
    from the same sequence as pull requests, so `gh pr view 190` fails simply
    because 190 names a stack.
    """
    return (f"#{number}: GitHub will not resolve this number to a pull request. "
            "In this repo a number may name a STACK instead — stacks are "
            "first-class objects drawn from the same number sequence — so check "
            f"`gh api repos/{repo}/stacks` before concluding the PR was deleted.")


def classify(repo: str, number: int) -> dict:
    """Read the one piece of state that decides the track: `stackEntry`.

    No `gh` subcommand surfaces stack membership — not `gh pr view`, not
    `gh pr list` — so this goes to GraphQL, which exposes it read-only.
    """
    owner, name = repo.split("/")
    code, out, err = _run_gh([
        "api", "graphql",
        "-f", f"query={CLASSIFY_QUERY}",
        "-F", f"owner={owner}",
        "-F", f"name={name}",
        "-F", f"number={number}",
    ])
    detail = (err or out).strip()
    if code != 0:
        if "Could not resolve to a PullRequest" in detail:
            raise Refusal(_not_a_pull_request(repo, number))
        raise Refusal(
            f"#{number}: the classification query failed ({detail}). Refusing "
            "rather than guessing a track: the two worlds need opposite merge "
            "commands, and picking the wrong one either 403s or merges into a "
            "stale branch.")
    try:
        payload = json.loads(out)
    except ValueError as exc:
        raise Refusal(f"#{number}: classification returned unreadable JSON "
                      f"({exc}); refusing rather than guessing a track.") from exc
    if payload.get("errors"):
        raise Refusal(
            f"#{number}: classification returned GraphQL errors "
            f"({json.dumps(payload['errors'])}). If `stackEntry` is the field "
            "named, GitHub no longer answers 'is this PR in a stack?' the way "
            "this script asks — fix the query before merging anything by hand.")
    pull = _dig(payload, "data", "repository", "pullRequest")
    if pull is None:
        raise Refusal(_not_a_pull_request(repo, number))
    missing = [field for field in REQUIRED_FIELDS if field not in pull]
    if missing:
        raise Refusal(
            f"#{number}: classification is missing {', '.join(missing)}. "
            "Refusing rather than guessing a track.")
    return pull


def track_of(pull: dict) -> str:
    """`A` for a stack member, `B` for an ordinary PR."""
    return "A" if pull.get("stackEntry") else "B"


def _stack_cell(pull: dict) -> str:
    entry = pull.get("stackEntry")
    if not entry:
        return "-"
    stack = entry.get("stack") or {}
    return (f"#{stack.get('number', '?')} pos {entry.get('position', '?')}"
            f"/{stack.get('size', '?')}")


def planned_command(repo: str, pull: dict) -> str:
    """The exact command this script would run for `pull`."""
    number = pull["number"]
    if track_of(pull) == "A":
        return (f"gh api --method PUT repos/{repo}/pulls/{number}/merge-async "
                f"-f merge_method=merge -f sha={pull['headRefOid']}")
    return (f"gh pr merge {number} --repo {repo} --merge "
            f"--match-head-commit {pull['headRefOid']}")


def format_table(pulls: list[dict]) -> str:
    headers = ["PR", "TRACK", "STATE", "DRAFT", "STACK", "BASE", "HEAD",
               "MERGEABLE"]
    rows = [headers]
    for pull in pulls:
        rows.append([
            f"#{pull['number']}",
            track_of(pull),
            str(pull["state"]),
            "yes" if pull["isDraft"] else "no",
            _stack_cell(pull),
            str(pull["baseRefName"]),
            str(pull["headRefOid"])[:8],
            str(pull.get("mergeable") or "?"),
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  " + "  ".join(cell.ljust(widths[i])
                                      for i, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  " + "  ".join("-" * width for width in widths))
    return "\n".join(lines)


# ------------------------------------------------------------------- assertions


def assert_open(pull: dict) -> None:
    number = pull["number"]
    if pull["isDraft"]:
        raise Refusal(f"#{number} is a DRAFT. Mark it ready before merging.")
    if pull["state"] == "MERGED":
        raise Refusal(f"#{number} is already MERGED. Nothing to do; re-running a "
                      "merge is how a stale base gets merged into twice.")
    if pull["state"] != "OPEN":
        raise Refusal(f"#{number} is {pull['state']}, not OPEN.")


def assert_head_unmoved(classified: dict, fresh: dict) -> None:
    if classified["headRefOid"] != fresh["headRefOid"]:
        raise Refusal(
            f"#{classified['number']}: the head moved between classification "
            f"({classified['headRefOid'][:8]}) and merge "
            f"({fresh['headRefOid'][:8]}). The plan you read is not the change "
            "that would land. Re-run and read the new plan.")


def assert_atomic_checks_succeeded(pull: dict) -> None:
    """Require the current head's combined check rollup to be ``SUCCESS``.

    This is deliberately atomic-only. Ordinary PR merges continue to rely on
    GitHub's branch-protection decision, while a top-entry atomic request needs
    an explicit proof for every lower PR it will sweep without naming in the
    request itself. Any absent or unexpected GraphQL shape is unsafe here.
    """
    number = pull["number"]
    commits = pull.get("commits")
    nodes = commits.get("nodes") if isinstance(commits, dict) else None
    if not isinstance(nodes, list) or len(nodes) != 1:
        raise Refusal(
            f"#{number}: cannot prove the latest commit's check status because "
            "GraphQL did not return exactly one commits(last: 1) node. Refusing "
            "the atomic sweep before its single irreversible request.")
    node = nodes[0]
    commit = node.get("commit") if isinstance(node, dict) else None
    if not isinstance(commit, dict):
        raise Refusal(
            f"#{number}: cannot prove the latest commit's check status because "
            "the GraphQL commit node is unavailable. Refusing the atomic sweep "
            "before its single irreversible request.")
    if commit.get("oid") != pull["headRefOid"]:
        raise Refusal(
            f"#{number}: the status-check rollup belongs to commit "
            f"{str(commit.get('oid') or '?')[:8]}, not the classified head "
            f"{pull['headRefOid'][:8]}. Refusing the atomic sweep before its "
            "single irreversible request.")
    rollup = commit.get("statusCheckRollup")
    if not isinstance(rollup, dict) or "state" not in rollup:
        raise Refusal(
            f"#{number}: the latest commit has no usable statusCheckRollup. "
            "The atomic path fails closed when checks are absent or their "
            "GraphQL shape is unavailable.")
    state = rollup["state"]
    if state != "SUCCESS":
        raise Refusal(
            f"#{number}: the latest commit's status-check rollup is {state!r}, "
            "not 'SUCCESS'. Every explicitly named swept member must be green "
            "before the atomic PUT.")


def assert_bottom_of_stack(pull: dict, atomic: bool) -> None:
    entry = pull["stackEntry"]
    position = entry.get("position")
    stack = entry.get("stack") or {}
    if position == 1 or atomic:
        return
    raise Refusal(
        f"#{pull['number']} is at position {position} of stack "
        f"#{stack.get('number', '?')} (size {stack.get('size', '?')}), not the "
        "bottom. Merging entry k merges entries 1..k ATOMICALLY, into one merge "
        "commit named after entry k — so this would silently land every PR below "
        "it too. Pass --atomic if that is what you want. Note that for a stacked "
        "PR `baseRefName` proves nothing here: entries read `main` whether or not "
        "they are at the bottom.")


def validate_atomic_sweep(pulls: list[dict]) -> None:
    """Prove that `pulls` names one stack's complete swept prefix, 1..k.

    GitHub's atomic endpoint accepts only the selected top entry; it does not
    accept the lower entries as request parameters. Requiring callers to name
    the full prefix gives the driver something concrete to preflight before that
    one irreversible request, instead of silently trusting unnamed swept PRs.
    """
    if not pulls:
        raise Refusal("--atomic needs at least one pull request.")
    if any(track_of(pull) != "A" for pull in pulls):
        ordinary = [f"#{pull['number']}" for pull in pulls
                    if track_of(pull) != "A"]
        raise Refusal(
            "--atomic is only for one native GitHub stack; these named pull "
            f"requests are ordinary: {', '.join(ordinary)}.")

    for pull in pulls:
        assert_open(pull)

    stack_numbers = {
        (pull["stackEntry"].get("stack") or {}).get("number")
        for pull in pulls
    }
    if len(stack_numbers) != 1 or None in stack_numbers:
        cells = ", ".join(f"#{pull['number']}={_stack_cell(pull)}"
                          for pull in pulls)
        raise Refusal(f"--atomic names members of different stacks: {cells}.")

    positions = [pull["stackEntry"].get("position") for pull in pulls]
    expected = list(range(1, len(pulls) + 1))
    if positions != expected:
        top = max((position for position in positions
                   if isinstance(position, int)), default="?")
        raise Refusal(
            "--atomic must name every swept member in bottom-to-top order, "
            f"positions 1..k. Named positions are {positions}; selected top is "
            f"position {top}. Name the complete contiguous prefix {expected}.")


def format_atomic_sweep(repo: str, pulls: list[dict]) -> str:
    """Explain the one-request effect of a validated atomic prefix."""
    top = pulls[-1]
    entry = top["stackEntry"]
    stack = entry.get("stack") or {}
    numbers = ", ".join(f"#{pull['number']}" for pull in pulls)
    return (
        "Atomic fast path (one top-entry async request):\n"
        f"  stack #{stack.get('number', '?')}: merging #{top['number']} at "
        f"position {entry.get('position')} sweeps positions 1.."
        f"{entry.get('position')} ({numbers}) into one merge commit.\n"
        f"  {planned_command(repo, top)}"
    )


def preflight_atomic_sweep(repo: str, classified: list[dict]) -> list[dict]:
    """Freshly validate and head-pin every named member before the one PUT."""
    fresh = [classify(repo, pull["number"]) for pull in classified]
    validate_atomic_sweep(fresh)
    for before, after in zip(classified, fresh):
        assert_head_unmoved(before, after)
        assert_atomic_checks_succeeded(after)
    print("  atomic preflight passed: every named member is in the same stack, "
          "OPEN, non-draft, green, contiguous through the selected top, and "
          "head-pinned.")
    return fresh


def assert_intended_base(pull: dict, base: str) -> None:
    if pull["baseRefName"] == base:
        return
    raise Refusal(
        f"#{pull['number']} is not stacked and its base is "
        f"{pull['baseRefName']!r}, not {base!r}. Outside a native stack NOTHING "
        "retargets — not GitHub, not `gh` — so merging now lands this work on "
        f"{pull['baseRefName']!r}, wherever that branch happens to point. This is "
        "exactly how #198 merged into an already-merged branch 84 seconds after "
        "its base landed on main: CI was green, the API returned success, the UI "
        "said 'Merged', and the only signal was this field. Retarget first: "
        f"gh pr edit {pull['number']} --base {base}")


# ----------------------------------------------------------------- merge (exec)


def confirm_merged(repo: str, number: int) -> bool:
    """The independent check: `GET /pulls/{n}/merge` is 204 merged, 404 not.

    This outlives the async record (which expires after about a day) and does not
    depend on the merge path taken, so it is the second opinion every merge here
    is confirmed against.
    """
    code, out, err = _run_gh(["api", f"repos/{repo}/pulls/{number}/merge"])
    if code == 0:
        return True
    status = _http_status(err, out)
    if status == 404:
        return False
    raise Refusal(
        f"#{number}: the merge check answered neither 204 nor 404 "
        f"({status or 'no HTTP status'}: {(err or out).strip()}). Refusing to "
        "report a merge state nothing confirmed.")


def poll_async(repo: str, number: int, uuid: str, interval: float,
               ceiling: float) -> dict:
    """Poll the async merge record to a TERMINAL state, or refuse."""
    deadline = time.monotonic() + ceiling
    while True:
        code, out, err = _run_gh(
            ["api", f"repos/{repo}/pulls/{number}/merge-async/{uuid}"])
        if code != 0:
            raise Refusal(f"#{number}: cannot read the async merge record "
                          f"{uuid} ({(err or out).strip()}).")
        try:
            record = json.loads(out)
        except ValueError as exc:
            raise Refusal(f"#{number}: async merge record is unreadable "
                          f"({exc}).") from exc
        status = record.get("status")
        print(f"  poll {uuid}: status={status!r}")
        if status == "merged":
            return record
        if status == "failed":
            raise Refusal(f"#{number}: the async merge FAILED "
                          f"({json.dumps(record)}).")
        if status == "enqueued":
            raise Refusal(
                f"#{number}: the async merge is ENQUEUED. That is terminal but "
                "it is NOT merged — a merge queue accepted the request and will "
                "decide later. Nothing below this PR may be merged on the "
                "assumption that this one landed.")
        if status != "pending":
            raise Refusal(f"#{number}: unknown async merge status {status!r} "
                          f"({json.dumps(record)}); refusing to interpret it.")
        if time.monotonic() >= deadline:
            raise Refusal(
                f"#{number}: still 'pending' after {ceiling:g}s. The request may "
                "yet land, so do NOT re-fire it — poll "
                f"`gh api repos/{repo}/pulls/{number}/merge-async/{uuid}` and "
                f"`gh api repos/{repo}/pulls/{number}/merge` before doing "
                "anything else.")
        time.sleep(interval)


def wait_for_confirmation(repo: str, number: int, interval: float,
                          ceiling: float) -> None:
    """Poll only the independent 204/404 check (used when no uuid is available)."""
    deadline = time.monotonic() + ceiling
    while True:
        if confirm_merged(repo, number):
            return
        if time.monotonic() >= deadline:
            raise Refusal(
                f"#{number}: not merged after {ceiling:g}s of confirmation "
                "polling. Do not re-fire the request; read its state first.")
        time.sleep(interval)


def merge_track_a(repo: str, pull: dict, opts, *, preflighted: bool = False) -> None:
    """A stack member: `merge-async`, poll, then confirm independently.

    The atomic path supplies the just-preflighted top entry so no extra network
    read can replace the state that the full-prefix validation approved.
    """
    number = pull["number"]
    fresh = pull if preflighted else classify(repo, number)
    if track_of(fresh) != "A":
        raise Refusal(f"#{number} left its stack between classification and "
                      "merge; re-run and read the new plan.")
    assert_open(fresh)
    if not preflighted:
        assert_head_unmoved(pull, fresh)
    assert_bottom_of_stack(fresh, opts.atomic)

    code, out, err = _run_gh([
        "api", "--method", "PUT", f"repos/{repo}/pulls/{number}/merge-async",
        "-f", "merge_method=merge", "-f", f"sha={fresh['headRefOid']}",
    ])
    uuid = None
    if code == 0:
        try:
            record = json.loads(out)
        except ValueError:
            record = {}
        uuid = _dig(record, "details", "uuid") or _first_uuid(out)
        print(f"  PUT accepted: status={record.get('status')!r} uuid={uuid} "
              "-- HTTP 202 is a receipt, not a merge.")
    else:
        status = _http_status(err, out)
        if status != 409:
            raise Refusal(f"#{number}: the async merge request was rejected "
                          f"({status or 'no HTTP status'}: "
                          f"{(err or out).strip()}).")
        uuid = _first_uuid(out, err)
        print(f"  PUT returned 409: a merge request for #{number} is already in "
              "flight. Polling it; NOT re-firing.")
    if uuid:
        poll_async(repo, number, uuid, opts.poll_interval, opts.timeout)
    else:
        print("  no uuid to poll; falling back to the independent merge check.")
        wait_for_confirmation(repo, number, opts.poll_interval, opts.timeout)

    if not confirm_merged(repo, number):
        raise Refusal(
            f"#{number}: the async record and the merge check DISAGREE — the "
            "record reached a merged/confirmed state and "
            f"`gh api repos/{repo}/pulls/{number}/merge` still answers 404. "
            "Refusing to report either one as the truth.")
    print(f"  #{number} MERGED (confirmed by GET /pulls/{number}/merge -> 204).")


def merge_track_b(repo: str, pull: dict, opts) -> None:
    """An ordinary PR: `gh pr merge --merge`, then confirm."""
    number = pull["number"]
    fresh = classify(repo, number)
    if track_of(fresh) != "B":
        raise Refusal(f"#{number} joined a stack between classification and "
                      "merge; re-run and read the new plan.")
    assert_open(fresh)
    assert_head_unmoved(pull, fresh)
    assert_intended_base(fresh, opts.base)

    code, out, err = _run_gh([
        "pr", "merge", str(number), "--repo", repo, "--merge",
        "--match-head-commit", fresh["headRefOid"],
    ])
    if code != 0:
        status = _http_status(err, out)
        hint = ""
        if status == 403:
            hint = (" HTTP 403 on `gh pr merge` is the stack-membership refusal; "
                    "re-classify, because this PR was read as non-stacked.")
        raise Refusal(f"#{number}: `gh pr merge` failed "
                      f"({(err or out).strip()}).{hint}")
    if not confirm_merged(repo, number):
        raise Refusal(
            f"#{number}: `gh pr merge` exited 0 but "
            f"`gh api repos/{repo}/pulls/{number}/merge` answers 404. The two "
            "sources disagree; refusing to report a merge.")
    print(f"  #{number} MERGED (confirmed by GET /pulls/{number}/merge -> 204).")


def retarget(repo: str, number: int, base: str) -> None:
    """Retarget a non-stacked PR and READ IT BACK.

    An unverified retarget is the same bug as no retarget — `#198` merged into a
    stale base with nothing red anywhere, and the only field that would have said
    so was one nobody read.
    """
    before = classify(repo, number)
    if track_of(before) != "B":
        raise Refusal(
            f"#{number}: joined a native stack before retargeting. Stack "
            "members are rebased by GitHub and must never be hand-edited.")
    if before["baseRefName"] == base:
        print(f"  #{number} already targets {base}; retarget is a no-op "
              "(`gh pr edit` not called, so no duplicate CI was triggered).")
        return

    code, out, err = _run_gh(["pr", "edit", str(number), "--repo", repo,
                              "--base", base])
    if code != 0:
        raise Refusal(f"#{number}: `gh pr edit --base {base}` failed "
                      f"({(err or out).strip()}).")
    after = classify(repo, number)
    if after["baseRefName"] != base:
        raise Refusal(
            f"#{number}: the retarget did NOT take — the base still reads "
            f"{after['baseRefName']!r}, not {base!r}. Merging now would land the "
            "work on that branch, which is the #198 failure exactly.")
    print(f"  #{number} retargeted to {base} (read back and confirmed).")


def report_sweep(repo: str, remaining: list[dict]) -> list[dict]:
    """Re-read the PRs still queued; drop any GitHub merged atomically with ours.

    Merging entry k of a stack merges entries 1..k into ONE merge commit named
    after entry k, so a PR named later on the command line can already be merged
    by the time its turn comes. That is the documented behaviour, so it is
    reported and skipped rather than refused.
    """
    still_queued = []
    for pull in remaining:
        after = classify(repo, pull["number"])
        if after["state"] == "MERGED":
            print(f"  #{after['number']} was swept into the same atomic merge "
                  f"(state=MERGED, base={after['baseRefName']}); skipping it.")
            continue
        if (after["baseRefName"] != pull["baseRefName"]
                or _stack_cell(after) != _stack_cell(pull)):
            print(f"  #{after['number']} moved: base={after['baseRefName']}, "
                  f"stack={_stack_cell(after)} (was base={pull['baseRefName']}, "
                  f"stack={_stack_cell(pull)}).")
        still_queued.append(after)
    return still_queued


# --------------------------------------------------------- post-merge cutover
#
# Everything below runs AFTER a merge that was already independently confirmed.
# That single fact decides every design choice here:
#
#   * nothing in this section may change the exit code. A cutover this script
#     declines is a state for the OWNER to resolve, never a failed merge, and
#     reporting a merged PR as un-merged is the one outcome worse than an orphan
#     branch. Hence `CutoverRefused`, which is caught inside `cutover()` and
#     never reaches `main()`'s `Refusal` handler;
#   * the receipt prints on EVERY path — success, no-op, and refusal alike.
#     A warning banner can be reported green; `<before>..<after>, N commits`
#     cannot, and when the cutover was refused the two SHAs are what shows the
#     gap that is still there;
#   * fast-forward ONLY. No merge, no rebase, no reset, no checkout, no stash.
#     `git merge --ff-only` either moves the ref or changes nothing.


class CutoverRefused(Exception):
    """A cutover step this script will not perform.

    Deliberately NOT a `Refusal`: a `Refusal` exits 1, and the merge that
    preceded this has already landed on the trunk.
    """


#: An object id, as `git rev-parse` and `git merge-tree --write-tree` print one.
#: Mirrored from `automation/workspace/status.py` (`_OID_RE`) so the containment
#: probe below keeps that module's exact semantics.
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")

#: Files and directories git leaves in the git dir while an operation is half
#: finished. Mirrored from `automation/workspace/cleanup.py`
#: (`_in_progress_operation`): `git status --porcelain` can be EMPTY in the
#: middle of some of these, so a clean status is not on its own a safe tree.
_IN_PROGRESS_MARKERS = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)


def _run_git(args: list[str], cwd: str | None = None,
             env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run one local `git` command; return (exit code, stdout, stderr).

    Never a pipeline, for the reason `_run_gh` gives. `--no-optional-locks` so a
    read here never fights a concurrent session for the index lock.
    """
    command = ["git", "--no-optional-locks"]
    if cwd is not None:
        command += ["-C", cwd]
    command += args
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              env={**os.environ, **env} if env else None)
    except OSError as exc:
        raise CutoverRefused(f"cannot run `git`: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def _git_line(args: list[str], cwd: str, env: dict[str, str] | None = None) -> str | None:
    """The single stripped line `git` printed, or None if the command failed."""
    code, out, _ = _run_git(args, cwd, env)
    if code != 0:
        return None
    return out.strip() or None


def _detail(out: str, err: str) -> str:
    return (err.strip() or out.strip() or "no output").replace("\n", " ")


def branch_delete_argv(branch: str) -> list[str]:
    """The ONLY branch-deletion command this script may build.

    `-d` asks git to prove the branch is contained before deleting it. `-D` and
    `--force` ask git to skip that proof, and this repo bans both outright, so
    they are not spelled anywhere in this module and a test asserts that by
    reading the module's own string literals.
    """
    return ["branch", "-d", branch]


# ------------------------------------------------- locating the working trees


def find_main_worktree(start: str) -> str:
    """Absolute path of the MAIN working tree — git's own definition.

    `--git-dir` equals `--git-common-dir` in the main working tree and in no
    other, so this holds no matter which linked worktree the caller runs from.
    That matters: an agent merges from a worktree, and the checkout that drifts
    behind `origin/main` is the one it is NOT standing in.
    """
    code, out, err = _run_git(["rev-parse", "--git-dir", "--git-common-dir"],
                              start)
    if code != 0:
        raise CutoverRefused(
            f"cannot locate the main working tree from {start!r}: "
            f"{_detail(out, err)}")
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if len(lines) != 2:
        raise CutoverRefused(
            "cannot locate the main working tree: `git rev-parse --git-dir "
            f"--git-common-dir` printed {len(lines)} line(s), not 2")
    git_dir, common_dir = (os.path.realpath(os.path.join(start, line))
                           for line in lines)
    if git_dir == common_dir:
        candidate = _git_line(["rev-parse", "--show-toplevel"], start)
        if not candidate:
            raise CutoverRefused(
                "the repository this ran in has no working tree (a bare "
                "repository has no `main` to fast-forward)")
        return os.path.realpath(candidate)
    # A linked worktree. `<main>/.git` is the common dir, so its parent is the
    # main working tree — confirmed below rather than assumed.
    candidate = os.path.dirname(common_dir)
    verified = _git_line(["rev-parse", "--show-toplevel"], candidate)
    if not verified or os.path.realpath(verified) != candidate:
        raise CutoverRefused(
            f"cannot locate the main working tree: {candidate!r} is the parent "
            "of the common git dir but git does not report it as a working "
            "tree top level")
    if is_main_worktree(candidate) is not True:
        raise CutoverRefused(
            f"cannot locate the main working tree: {candidate!r} does not "
            "satisfy git's own test (`--git-dir` == `--git-common-dir`)")
    return candidate


def is_main_worktree(path: str) -> bool | None:
    """True/False per git's definition; None when git could not answer."""
    code, out, _ = _run_git(["rev-parse", "--git-dir", "--git-common-dir"], path)
    if code != 0:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if len(lines) != 2:
        return None
    first, second = (os.path.realpath(os.path.join(path, line))
                     for line in lines)
    return first == second


def parse_worktrees(porcelain: str) -> list[dict]:
    """`git worktree list --porcelain` -> [{path, branch, detached, bare}].

    Pure, so the parse is testable without a repository. `branch` is the short
    name (`refs/heads/x` -> `x`) or None for a detached or bare entry.
    """
    entries: list[dict] = []
    current: dict | None = None
    for raw in porcelain.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            current = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"path": value, "branch": None, "detached": False,
                       "bare": False}
            entries.append(current)
        elif current is None:
            continue
        elif key == "branch":
            current["branch"] = value[len("refs/heads/"):] if value.startswith(
                "refs/heads/") else value
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    return entries


def worktrees_of(main_wt: str) -> list[dict]:
    code, out, err = _run_git(["worktree", "list", "--porcelain"], main_wt)
    if code != 0:
        raise CutoverRefused(f"`git worktree list` failed: {_detail(out, err)}")
    return parse_worktrees(out)


def worktree_holding(worktrees: list[dict], branch: str) -> str | None:
    """The path of the worktree with `branch` checked out, or None."""
    for entry in worktrees:
        if entry["branch"] == branch:
            return entry["path"]
    return None


# --------------------------------------------------- is the tree safe to move


def in_progress_operation(main_wt: str) -> str | None:
    git_dir = _git_line(["rev-parse", "--git-dir"], main_wt)
    if not git_dir:
        return None
    root = os.path.join(main_wt, git_dir) if not os.path.isabs(git_dir) else git_dir
    for marker, label in _IN_PROGRESS_MARKERS:
        if os.path.exists(os.path.join(root, marker)):
            return label
    return None


def worktree_changes(main_wt: str) -> tuple[list[str], list[str]]:
    """(tracked changes, untracked paths) from `git status --porcelain`.

    They are separated because they are not the same risk. A TRACKED change is
    a concurrent session's uncommitted work and this tool must not go anywhere
    near it. An UNTRACKED file is not part of any branch, and `git merge
    --ff-only` already fails closed rather than clobbering one — so untracked
    files are reported and do not block, which is the difference between a tool
    that runs and one that refuses on every real checkout.
    """
    code, out, err = _run_git(["status", "--porcelain"], main_wt)
    if code != 0:
        raise CutoverRefused(f"`git status --porcelain` failed: "
                             f"{_detail(out, err)}")
    tracked, untracked = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        (untracked if line.startswith("?? ") else tracked).append(line[3:].strip())
    return tracked, untracked


# ---------------------------------------------------- the containment probe
#
# MIRRORED, not imported, from `automation/workspace/status.py` (`MergeProbe` +
# `_merged_state`). A skill's `scripts/` may not import repo-root Python
# (`docs/handbook/skills-and-vendoring.md`), and the vendoring gate only syncs
# `automation/shared/` into a skill's `scripts/_vendor/` — `automation/workspace`
# is not a vendorable source, and this skill has no `_vendor/` at all. So the
# semantics are reproduced exactly and named here so the two can be diffed:
#
#     contained(base, branch)  ==  (git merge-tree --write-tree base branch)
#                                  == base^{tree}
#
# "merging this branch into the base would change nothing." Ancestry is NOT
# enough — `git branch --merged` misses squash merges — and a `git patch-id`
# probe is banned near this decision because patch-id ignores whitespace and
# would call genuinely unique work contained. The one thing NOT mirrored is
# status.py's ancestor-only fallback for git < 2.38: under-reporting `merged` is
# harmless for a dashboard and fatal for a deletion, so here an unusable probe
# is `unknown` and `unknown` always KEEPS the branch.

CONTAINED = "contained"
NOT_CONTAINED = "not-contained"
CONTAINMENT_UNKNOWN = "unknown"


def _probe_env(main_wt: str) -> tuple[dict[str, str] | None, str | None]:
    """Redirect `--write-tree`'s object writes into a throwaway directory.

    The probe writes real tree objects. They are gc-able, but this script has no
    business leaving litter in the owner's object store, so writes go to a temp
    directory while `GIT_ALTERNATE_OBJECT_DIRECTORIES` (ABSOLUTE — a relative
    alternate resolves against the wrong directory) keeps every real object
    readable.
    """
    objects = _git_line(["rev-parse", "--git-path", "objects"], main_wt)
    if not objects:
        return None, None
    real = objects if os.path.isabs(objects) else os.path.join(main_wt, objects)
    try:
        sandbox = tempfile.mkdtemp(prefix="merge-stack-probe-")
    except OSError:
        return None, None
    return ({"GIT_OBJECT_DIRECTORY": sandbox,
             "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.realpath(real)},
            sandbox)


def containment(main_wt: str, base_ref: str, branch: str) -> str:
    """Does `base_ref` already contain everything `branch` has?"""
    base_tree = _git_line(["rev-parse", f"{base_ref}^{{tree}}"], main_wt)
    if not base_tree or not _GIT_OID_RE.match(base_tree):
        return CONTAINMENT_UNKNOWN
    env, sandbox = _probe_env(main_wt)
    try:
        code, out, _ = _run_git(
            ["merge-tree", "--write-tree", base_ref, branch], main_wt, env)
    finally:
        if sandbox:
            shutil.rmtree(sandbox, ignore_errors=True)
    head = out.split("\n", 1)[0].strip()
    # Exit 1 WITH a tree on stdout is a conflicting merge — a real answer
    # ("merging would change the base"). Exit 1 with nothing is a ref that does
    # not resolve, and 128 is an unrelated history. Neither is evidence.
    if code in (0, 1) and _GIT_OID_RE.match(head):
        return CONTAINED if head == base_tree else NOT_CONTAINED
    return CONTAINMENT_UNKNOWN


# --------------------------------------------------------------- the cutover


def _short(oid: str | None) -> str:
    return (oid or "?")[:12]


def _ahead_behind(main_wt: str, local: str, remote_ref: str) -> tuple[int, int] | None:
    """(commits local has that remote lacks, commits remote has that local lacks)."""
    line = _git_line(["rev-list", "--left-right", "--count",
                      f"{local}...{remote_ref}"], main_wt)
    if not line:
        return None
    parts = line.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def retire_branches(main_wt: str, branches: list[str], base_ref: str,
                    remote: str, emit) -> None:
    """`git branch -d` each merged head branch that is provably safe to retire.

    Every branch that is KEPT says why. A silent keep is the failure this whole
    section exists to end.
    """
    worktrees = worktrees_of(main_wt)
    for branch in branches:
        if not _git_line(["rev-parse", "--verify", "--quiet",
                          f"refs/heads/{branch}"], main_wt):
            emit(f"  branch {branch}: nothing to retire (no local branch of "
                 f"that name)")
            continue
        holder = worktree_holding(worktrees, branch)
        if holder is not None:
            emit(f"  branch {branch}: KEPT -- checked out in the worktree "
                 f"{holder}. This tool never removes a worktree; retire it with "
                 f"`automation/workspace/cleanup.py`, then re-run.")
            continue
        verdict = containment(main_wt, base_ref, branch)
        if verdict != CONTAINED:
            why = ("its content is NOT contained in " + base_ref
                   if verdict == NOT_CONTAINED
                   else "git could not prove containment, and an unanswerable "
                        "probe keeps the branch")
            emit(f"  branch {branch}: KEPT -- {why}.")
            continue
        code, out, err = _run_git(branch_delete_argv(branch), main_wt)
        if code != 0:
            emit(f"  branch {branch}: KEPT -- `git branch -d` declined: "
                 f"{_detail(out, err)}. There is no -D here; resolve it "
                 f"yourself or leave the branch.")
            continue
        emit(f"  branch {branch}: DELETED locally ({base_ref} contains its "
             f"content; `git branch -d`).")
        if _git_line(["rev-parse", "--verify", "--quiet",
                      f"refs/remotes/{remote}/{branch}"], main_wt):
            emit(f"    {remote}/{branch} is now retirable on the remote. This "
                 f"tool deletes NO remote branch: deleting a base branch closed "
                 f"#136 one second after its child merged, and remote sweeping "
                 f"is an open owner decision whose default path is 'no agent "
                 f"deletes a remote branch'.")


def cutover(branches: list[str], *, start: str = ".", remote: str = DEFAULT_REMOTE,
            base: str = DEFAULT_BASE, unnamed: list[int] | None = None,
            emit=print) -> None:
    """Fetch, fast-forward the main working tree's `base`, print the receipt.

    Catches everything. This runs after a confirmed merge, so no failure here
    may propagate: the caller's exit code is about the merge, not about this.
    """
    emit("Post-merge cutover:")
    for number in unnamed or []:
        emit(f"  #{number}: no head branch name in the classification payload; "
             f"no local branch will be retired for it.")
    main_wt: str | None = None
    local_ref = f"refs/heads/{base}"
    remote_ref = f"refs/remotes/{remote}/{base}"
    before: str | None = None
    fetched = False
    refusal: str | None = None
    remedy: str | None = None
    try:
        main_wt = find_main_worktree(start)
        emit(f"  main working tree: {main_wt}")
        before = _git_line(["rev-parse", "--verify", "--quiet", local_ref],
                           main_wt)
        if before is None:
            raise CutoverRefused(
                f"the main working tree has no local branch {base!r}, so there "
                "is nothing to fast-forward")
        remedy = (f"git -C {main_wt} fetch {remote} && "
                  f"git -C {main_wt} merge --ff-only {remote}/{base}")

        remotes = (_git_line(["remote"], main_wt) or "").split()
        if remote not in remotes:
            raise CutoverRefused(
                f"there is no remote named {remote!r} in {main_wt}, so the "
                f"merge cannot be made visible locally. Add it, or fast-forward "
                f"{base} from wherever it does live.")
        code, out, err = _run_git(["fetch", remote], main_wt)
        if code != 0:
            raise CutoverRefused(
                f"`git fetch {remote}` exited {code}: {_detail(out, err)}. "
                f"Local {base} cannot be proven behind or ahead of anything "
                "until a fetch succeeds.")
        fetched = True
        emit(f"  fetched {remote}")

        if not _git_line(["rev-parse", "--verify", "--quiet", remote_ref],
                         main_wt):
            raise CutoverRefused(
                f"{remote}/{base} does not exist after the fetch, so there is "
                "no fetched trunk to fast-forward onto")

        operation = in_progress_operation(main_wt)
        if operation:
            raise CutoverRefused(
                f"a {operation} is in progress in the main working tree. "
                "Finish or abort it yourself; this tool touches nothing while "
                "git is mid-operation.")

        tracked, untracked = worktree_changes(main_wt)
        if untracked:
            emit(f"  note: {len(untracked)} untracked path(s) in the main "
                 "working tree; a fast-forward cannot clobber one (git fails "
                 "closed), so they do not block.")
        if tracked:
            shown = ", ".join(sorted(tracked)[:4])
            more = "" if len(tracked) <= 4 else f", +{len(tracked) - 4} more"
            raise CutoverRefused(
                f"the main working tree has uncommitted changes to "
                f"{len(tracked)} tracked path(s) ({shown}{more}) -- a "
                "concurrent session's work. Nothing here will touch it. Commit "
                "or stash it YOURSELF, then run the command above.")

        worktrees = worktrees_of(main_wt)
        holder = worktree_holding(worktrees, base)
        if holder is None:
            head = _git_line(["symbolic-ref", "--quiet", "--short", "HEAD"],
                             main_wt)
            raise CutoverRefused(
                f"the main working tree does not have {base} checked out (HEAD "
                f"is {head or 'detached'}), and no other worktree holds it "
                f"either. Check {base} out there yourself, then run the command "
                "above.")
        if os.path.realpath(holder) != os.path.realpath(main_wt):
            raise CutoverRefused(
                f"{base} is checked out in {holder}, not in the main working "
                f"tree. Fast-forwarding it from here would move a branch out "
                "from under a live checkout. Do it in that worktree, or free "
                f"{base} first.")
        head = _git_line(["symbolic-ref", "--quiet", "--short", "HEAD"], main_wt)
        if head != base:
            raise CutoverRefused(
                f"the main working tree's HEAD is {head or 'detached'}, not "
                f"{base}. Check {base} out there yourself, then run the command "
                "above.")

        gap = _ahead_behind(main_wt, local_ref, remote_ref)
        if gap is None:
            raise CutoverRefused(
                f"git could not count the distance between {base} and "
                f"{remote}/{base}; refusing to move a ref on an unreadable "
                "relationship.")
        ahead, behind = gap
        if ahead:
            raise CutoverRefused(
                f"local {base} has DIVERGED: {ahead} commit(s) that "
                f"{remote}/{base} does not have, {behind} the other way. A "
                "fast-forward is not possible and this tool will not merge, "
                "rebase or reset. Resolve it yourself.")
        if behind:
            code, out, err = _run_git(["merge", "--ff-only", f"{remote}/{base}"],
                                      main_wt)
            if code != 0:
                raise CutoverRefused(
                    f"`git merge --ff-only {remote}/{base}` exited {code}: "
                    f"{_detail(out, err)}")
    except CutoverRefused as declined:
        refusal = str(declined)
    except Exception as unexpected:  # never turn a merged PR into a failure
        refusal = (f"an unexpected error while cutting over "
                   f"({type(unexpected).__name__}: {unexpected})")

    after = (_git_line(["rev-parse", "--verify", "--quiet", local_ref], main_wt)
             if main_wt else None)
    if refusal:
        emit(f"  CUTOVER REFUSED -- {refusal}")
        emit("    The merge itself is unaffected: it already landed and was "
             "independently confirmed.")
        if remedy:
            emit(f"    Run this yourself when the tree is ready:\n      {remedy}")

    moved = 0
    if main_wt and before and after:
        counted = _git_line(["rev-list", "--count", f"{before}..{after}"], main_wt)
        moved = int(counted) if counted and counted.isdigit() else 0
    emit(f"  receipt: {base} {_short(before)}..{_short(after)}, {moved} commits")
    if main_wt and fetched:
        gap = _ahead_behind(main_wt, local_ref, remote_ref)
        if gap is not None:
            ahead, behind = gap
            if ahead or behind:
                emit(f"  gap: local {base} is {behind} commit(s) behind and "
                     f"{ahead} ahead of {remote}/{base} "
                     f"({_short(_git_line(['rev-parse', remote_ref], main_wt))})")
            else:
                emit(f"  gap: none -- local {base} equals {remote}/{base}")
    elif not fetched:
        emit(f"  gap: UNKNOWN -- no successful fetch, so the distance to "
             f"{remote}/{base} was never measured")

    if not branches:
        return
    if not (main_wt and fetched):
        emit("  branch retirement: SKIPPED -- containment can only be judged "
             f"against a freshly fetched {remote}/{base}. Branches kept: "
             f"{', '.join(branches)}")
        return
    try:
        retire_branches(main_wt, branches, f"{remote}/{base}", remote, emit)
    except CutoverRefused as declined:
        emit(f"  branch retirement: SKIPPED -- {declined}")
    except Exception as unexpected:
        emit(f"  branch retirement: SKIPPED -- unexpected "
             f"{type(unexpected).__name__}: {unexpected}")


def run_cutover(opts, pulls: list[dict]) -> None:
    """The cutover entry point used after every confirmed merge in `main()`."""
    if getattr(opts, "no_cutover", False):
        print("Post-merge cutover: SKIPPED (--no-cutover). Local `main` is "
              "unchanged and any merged branch is still here.")
        return
    branches = [pull["headRefName"] for pull in pulls
                if pull.get("headRefName")]
    unnamed = [pull["number"] for pull in pulls if not pull.get("headRefName")]
    cutover(branches, start=opts.cutover_root, remote=DEFAULT_REMOTE,
            base=opts.base, unnamed=unnamed)


# -------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_stack.py",
        description=("Classify a pull request as a native-stack member or an "
                     "ordinary PR, then merge it the way that world requires. "
                     "Dry run by default."),
        epilog=("There is deliberately no --squash, --rebase or --delete-branch: "
                "the first two rewrite every SHA on the branch and orphan the "
                "review-ledger rows keyed to those ranges, and deleting a base "
                "branch closes the PR above it. --auto is not offered either "
                "(allow_auto_merge is false here, and GitHub does not auto-merge "
                "stacks)."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prs", metavar="pr", nargs="+", type=int,
                        help="PR numbers, in the order they should merge")
    parser.add_argument("--repo", metavar="OWNER/NAME", default=None,
                        help="target repository (default: `gh repo view`)")
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help=f"intended base for non-stacked PRs (default: "
                             f"{DEFAULT_BASE})")
    parser.add_argument("--execute", action="store_true",
                        help="actually merge; without it this prints the plan "
                             "and stops")
    parser.add_argument("--atomic", action="store_true",
                        help="merge one native stack prefix with one request; "
                             "name every swept PR in positions 1..k, bottom to "
                             "top")
    parser.add_argument("--no-cutover", action="store_true",
                        help="skip the post-merge cutover entirely: no fetch, "
                             "no fast-forward of the main working tree's base "
                             "branch, no local branch retirement (for a caller "
                             "that must not touch the working tree)")
    parser.add_argument("--cutover-root", metavar="PATH", default=".",
                        help="where to start looking for the MAIN working tree "
                             "(default: the current directory). Any path inside "
                             "the repository works -- a linked worktree is "
                             "resolved to the main one via --git-common-dir")
    parser.add_argument("--poll-interval", type=float,
                        default=DEFAULT_POLL_INTERVAL_S, metavar="SECONDS",
                        help=f"async poll interval (default: "
                             f"{DEFAULT_POLL_INTERVAL_S:g})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_POLL_CEILING_S,
                        metavar="SECONDS",
                        help=f"async poll ceiling (default: "
                             f"{DEFAULT_POLL_CEILING_S:g})")
    return parser


def reject_banned_flags(argv: list[str]) -> str | None:
    """The merge strategies this repo does not permit, refused before parsing."""
    for arg in argv:
        flag = arg.split("=", 1)[0]
        if flag in BANNED_FLAGS:
            return (f"{flag} is not a flag of this script: {BANNED_FLAGS[flag]}. "
                    "This repo merges with a merge commit and keeps every branch.")
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    banned = reject_banned_flags(argv)
    if banned:
        print(f"merge_stack.py: {banned}", file=sys.stderr)
        return 2
    opts = build_parser().parse_args(argv)

    try:
        repo = resolve_repo(opts.repo)
        classified = [classify(repo, number) for number in opts.prs]

        if opts.atomic:
            validate_atomic_sweep(classified)

        mode = "EXECUTE" if opts.execute else "DRY RUN (nothing merges without --execute)"
        print(f"merge_stack.py: {repo} -- {mode}")
        print(format_table(classified))
        print()
        if opts.atomic:
            print(format_atomic_sweep(repo, classified))
        else:
            print("Plan, in the order given:")
            for index, pull in enumerate(classified):
                world = ("stack member -- `gh pr merge` answers HTTP 403 here"
                         if track_of(pull) == "A"
                         else "not stacked -- nothing retargets it but you")
                print(f"  #{pull['number']} ({world})")
                print(f"      {planned_command(repo, pull)}")
                following = classified[index + 1:index + 2]
                if track_of(pull) == "B" and following:
                    print(f"      then, only after it merges: read "
                          f"#{following[0]['number']}'s base; if needed, "
                          f"gh pr edit {following[0]['number']} --repo {repo} "
                          f"--base {opts.base}")
        if opts.no_cutover:
            print("Post-merge cutover: DISABLED by --no-cutover. Local "
                  f"{opts.base} will stay where it is and every merged branch "
                  "stays local.")
        else:
            print(f"Post-merge cutover: after each confirmed merge -- fetch "
                  f"{DEFAULT_REMOTE}, fast-forward {opts.base} in the MAIN "
                  f"working tree (--ff-only only), retire each merged head "
                  f"branch with `git branch -d` when no worktree holds it and "
                  f"{DEFAULT_REMOTE}/{opts.base} contains its content, and "
                  f"print a <before>..<after> receipt. No remote branch and no "
                  f"worktree is ever removed.")
        print()

        if not opts.execute:
            print("Dry run: stopping here. Re-run with --execute to merge. "
                  "(The cutover runs only under --execute.)")
            return 0

        if opts.atomic:
            fresh = preflight_atomic_sweep(repo, classified)
            top = fresh[-1]
            print(f"Sending one top-entry request for #{top['number']}; this "
                  f"sweeps positions 1..{len(fresh)}:")
            merge_track_a(repo, top, opts, preflighted=True)
            for swept in fresh[:-1]:
                if not confirm_merged(repo, swept["number"]):
                    raise Refusal(
                        f"#{swept['number']}: the top entry merged, but this "
                        "explicitly named swept member is not independently "
                        "confirmed merged.")
                print(f"  #{swept['number']} swept and independently confirmed "
                      f"by GET /pulls/{swept['number']}/merge -> 204.")
            print("All named pull requests merged and independently confirmed.")
            # ONE merge commit landed, so one cutover — carrying every branch
            # the sweep retired, not just the top entry's.
            run_cutover(opts, fresh)
            return 0

        queue = list(classified)
        while queue:
            pull = queue.pop(0)
            print(f"Merging #{pull['number']} (track {track_of(pull)}):")
            if track_of(pull) == "A":
                merge_track_a(repo, pull, opts)
                queued_before = {item["number"] for item in queue}
                queue = report_sweep(repo, queue)
                swept = queued_before - {item["number"] for item in queue}
                run_cutover(opts, [pull, *(item for item in classified
                                           if item["number"] in swept)])
            else:
                merge_track_b(repo, pull, opts)
                run_cutover(opts, [pull])
                if queue and track_of(queue[0]) == "B":
                    retarget(repo, queue[0]["number"], opts.base)
                queue = [classify(repo, item["number"]) for item in queue]
        print("All named pull requests merged and independently confirmed.")
        return 0
    except Refusal as refusal:
        print(f"merge_stack.py: REFUSED -- {refusal}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
