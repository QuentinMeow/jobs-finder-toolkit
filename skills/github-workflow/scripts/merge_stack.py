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
  * a stacked PR whose `position` is not 1, unless `--atomic` says so on purpose;
  * a head SHA that moved between classification and merge;
  * a PR that is draft, closed, or already merged;
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

Usage:

    .venv/bin/python skills/github-workflow/scripts/merge_stack.py 41 42
    .venv/bin/python skills/github-workflow/scripts/merge_stack.py --execute 41

Exit codes: 0 = the plan printed (dry run) or every named PR merged and was
confirmed; 1 = a refusal or a failed merge; 2 = a usage error.

This script shells out to `gh` and nothing else. It imports no repo-root Python
(`docs/handbook/skills-and-vendoring.md`), makes no direct HTTP call, and writes no
file anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

DEFAULT_BASE = "main"
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
      headRefOid
      mergeable
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


def merge_track_a(repo: str, pull: dict, opts) -> None:
    """A stack member: `merge-async`, poll, then confirm independently."""
    number = pull["number"]
    fresh = classify(repo, number)
    if track_of(fresh) != "A":
        raise Refusal(f"#{number} left its stack between classification and "
                      "merge; re-run and read the new plan.")
    assert_open(fresh)
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
                        help="allow merging a stack entry above position 1, "
                             "which lands every entry below it in one commit")
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

        mode = "EXECUTE" if opts.execute else "DRY RUN (nothing merges without --execute)"
        print(f"merge_stack.py: {repo} -- {mode}")
        print(format_table(classified))
        print()
        print("Plan, in the order given:")
        for index, pull in enumerate(classified):
            world = ("stack member -- `gh pr merge` answers HTTP 403 here"
                     if track_of(pull) == "A"
                     else "not stacked -- nothing retargets it but you")
            print(f"  #{pull['number']} ({world})")
            print(f"      {planned_command(repo, pull)}")
            following = classified[index + 1:index + 2]
            if track_of(pull) == "B" and following:
                print(f"      then, only after it merges: gh pr edit "
                      f"{following[0]['number']} --repo {repo} "
                      f"--base {opts.base}")
        print()

        if not opts.execute:
            print("Dry run: stopping here. Re-run with --execute to merge.")
            return 0

        queue = list(classified)
        while queue:
            pull = queue.pop(0)
            print(f"Merging #{pull['number']} (track {track_of(pull)}):")
            if track_of(pull) == "A":
                merge_track_a(repo, pull, opts)
                queue = report_sweep(repo, queue)
            else:
                merge_track_b(repo, pull, opts)
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
