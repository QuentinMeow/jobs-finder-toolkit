# Merging in this repo — the two-track runbook

`SKILL.md` carries the short corrected recipe. This file is the escalation: the
full classification step, both tracks end to end, the catalogue of ways a merge
here fails while looking successful, and the evidence every claim rests on.

Read it before merging anything, before writing a merge recipe into another
document, and whenever a merge "succeeded" but the trunk does not have the work.

## Worked PR body example

```markdown
## What changes for you

### Exports no longer overwrite yesterday's file

**Before.** `export.py` always wrote `out.csv`. Running it twice in one day
replaced the first run's file with no warning, and there was no way to get the
earlier one back.

**After.** It writes `out-<YYYY-MM-DD>.csv` and refuses to overwrite a file that
already exists.

**What you'll notice.** Anything that reads `out.csv` by name stops finding it —
scripts, spreadsheets, and the weekly mail job all need the new name. The export
directory now accumulates one file per day; nothing deletes them, so that is a
folder you have to clean out yourself.

### The export takes longer

**Before.** A run finished in about two seconds.

**After.** A run takes about nine seconds, because it now checksums each row
before writing so a truncated file is detected instead of shipped.

**What you'll notice.** The wait is noticeable when you run it by hand. It is
unchanged inside the nightly job, which nobody watches.

## What & why

`out.csv` was a fixed name chosen when the export ran once a week. It now runs on
demand, so the fixed name means the newest run destroys the previous one.

## Design

Date-stamping is done by the caller, not inside the writer, so the writer stays
usable for one-off paths in tests.

## Verification

Run at `9c1f2ab`, this branch's tip after its last rebase — not the worktree it
was written in.

```
$ python -m unittest discover tests                               exit 0
$ .venv/bin/python automation/gardener/verify_links.py            exit 0
```

Deltas this PR caused: +1 test file, +3 tests. No tree-wide totals here — those
come from the post-merge canonical counts job on `main`.

Ran the export twice in one day against a scratch directory and confirmed the
second run exits 1 instead of overwriting.

## What was filed

Follow-up task for pruning old exports; no queue items.
```

## 1. Why there are two tracks at all

This repository contains two kinds of pull request, and **they need opposite
commands**. Nothing in `gh` 2.94.0 distinguishes them: `gh pr list`, `gh pr view`,
`gh pr checks` and the web UI look identical in both cases.

- **A member of a native GitHub stack.** A stack here is a first-class
  server-side object with its own number, drawn from the same sequence as pull
  request numbers. GitHub offers to convert a chain of PRs into one when the base
  of each equals the head of the one below; **accepting that offer changes which
  merge commands work on those PRs**. Ten stacks exist in this repo.
- **An ordinary pull request** — GraphQL's `stackEntry` is `null`. This is the
  world `gh pr merge` was written for.

The classification is not advice, it is the first step. Get it wrong in one
direction and the merge returns HTTP 403; get it wrong in the other and the work
merges into a stale branch with nothing red anywhere (see
[the #198 incident](#5-evidence)).

| | Stack member (Track A) | Ordinary PR (Track B) |
|---|---|---|
| Tell | `stackEntry` is non-null | `stackEntry` is `null` |
| Merge command | `PUT repos/{owner}/{repo}/pulls/{n}/merge-async` | `gh pr merge <n> --merge` |
| `gh pr merge` | **HTTP 403** — refused | the correct command |
| Bottom-of-stack test | `stackEntry.position == 1`, or explicit `--atomic` with every lower historical position named and confirmed (1-based) | `baseRefName == main` |
| Retargeting the next PR | GitHub rebases it onto the stack base itself — **do not hand-edit a member's base** | **nothing retargets it but you** — `gh pr edit <n+1> --base main`, then read it back |
| Merging is | **atomic** — entry *k* lands every currently unmerged entry below it through *k* in ONE merge commit named after *k* | one PR, one merge commit |

**The 403 is about stack membership and nothing else.** It is not the token
(scopes include `repo`; `viewerPermission` is `ADMIN`), not the merge method
(`allow_merge_commit` is `true`), and not branch protection (`main` is
unprotected; the single ruleset restricts only `deletion` and `non_fast_forward`).

**For a stacked PR, `baseRefName == "main"` proves nothing.** Entries read `main`
whether or not they sit at the bottom, so the base field cannot answer "is this
the one I may merge?" there. Position 1 is the ordinary bottom. When lower
positions already merged and GitHub preserves those historical positions, only
the driver's explicit complete-prefix `--atomic` proof may establish the lowest
unmerged member.

## 2. Step 0 — classify, always, before anything else

The script does this and refuses when it cannot:

```bash
# Dry run is the DEFAULT; nothing merges without --execute.
.venv/bin/python skills/github-workflow/scripts/merge_stack.py 41 42
```

It prints a classification table (track, state, draft, stack + position, base,
head SHA, mergeable) and the exact command it would run for each PR, then stops.
`--execute` runs the plan; every refusal below exits non-zero rather than trying
something else.

By hand, the same two probes:

```bash
# Every stack in the repo. `?state=open` is IGNORED by this endpoint — filter on
# `.open` yourself. The endpoint is undocumented; it works.
gh api repos/{owner}/{repo}/stacks --jq '.[] | {number, open, prs: [.pull_requests[].number]}'

# Is THIS PR in a stack, and where in it? `position` is 1-based; 1 is the bottom.
gh api graphql -f query='query { repository(owner:"<owner>", name:"<repo>") {
  pullRequest(number: 87) {
    baseRefName state isDraft headRefOid
    stackEntry { position stack { number size } }
  } } }'
```

Two things that look like bugs and are not:

- **A failing `gh pr view <n>` may mean *n* is a stack.** Stacks draw numbers
  from the same sequence as PRs, so `gh pr view 190` answers "Could not resolve
  to a PullRequest with the number of 190" — 190 is a stack, not a deleted PR.
  Check `/stacks` before concluding anything was removed.
- **Neither `gh pr list` nor `gh pr view` surfaces stack membership.** There is no
  flag for it. GraphQL's `stackEntry` is the only read path.

**If classification is unavailable — the `/stacks` endpoint gone, the `stackEntry`
field renamed — stop.** Do not guess a track. The whole point of the step is that
the two worlds are indistinguishable without it.

## 3. Track A — merging a stack member

A stack member merges through the async endpoint, and **the endpoint's exit code
is not the result**.

```bash
# 1. Assert position == 1 (unless the driver's explicit atomic complete-prefix
#    proof names and confirms every historical lower position).
# 2. Fire the request. `sha` pins the head you classified.
gh api --method PUT repos/{owner}/{repo}/pulls/<n>/merge-async \
    -f merge_method=merge -f sha=<headRefOid>
# -> HTTP 202 {"status":"pending","details":{"uuid":"..."}} and `gh` exits 0.
#    That is a RECEIPT. Nothing has merged.

# 3. Poll to a TERMINAL state.
gh api repos/{owner}/{repo}/pulls/<n>/merge-async/<uuid>

# 4. Confirm independently. 204 (exit 0) = merged, 404 (exit 1) = not.
gh api repos/{owner}/{repo}/pulls/<n>/merge > local/scratch/merge-check.log 2>&1
echo "EXIT=$?"
```

Terminal states of the async record, and what each means:

| `status` | Terminal? | Merged? | What to do |
|---|---|---|---|
| `pending` | no | no | keep polling (2s is fine; stop at 300s) |
| `merged` | yes | yes | confirm with step 4, then continue |
| `failed` | yes | no | read the record; fix the cause; do not retry blindly |
| `enqueued` | **yes** | **no** | a merge queue accepted the request and will decide later. Nothing below this PR may be merged on the assumption that this one landed |

**HTTP 409 on the PUT means a request is already in flight.** Poll it. Do not
re-fire — a second request is how one PR gets merged twice into two different
places.

**Step 4 is not redundant.** The async record expires after about a day, so it
stops being evidence; `GET /pulls/{n}/merge` keeps answering forever and does not
depend on which path the merge took. When the two sources disagree, report neither
— that disagreement is itself the finding.

**Merging a stack is atomic, and this is the surprise.** Merging entry *k* merges
every currently unmerged entry below it through *k* into **one** merge commit,
titled after entry *k*. If all seven positions are open, merging the top lands
all seven and leaves six PRs pointing at a merge commit that names none of them.
If lower positions already merged, only the remaining open group lands now.
Merge the lowest unmerged entry unless you specifically want the ready group;
`merge_stack.py` refuses a historical `position != 1` without an explicit
complete-prefix `--atomic` proof.

**Ready contiguous groups have a fast path.** Name every historical position
1…*k* in bottom-to-top order and select `--atomic`; the driver requires one
native stack and exactly one state shape: a leading `MERGED` prefix (possibly
empty) followed by a nonempty `OPEN` suffix. On `--execute` it freshly re-reads
every member and rejects changed state, base, head, stack, position, or size. It
independently confirms each historical merged member through durable `GET
/merge -> 204`, requires every open member to be non-draft, mergeable, green,
and head-pinned, then sends **one** async request for the open top. It polls that
request to a terminal state and independently confirms the top and every open
member swept by that new merge:

```bash
# Dry run first: says explicitly that #<top> sweeps positions 1..9.
.venv/bin/python skills/github-workflow/scripts/merge_stack.py --atomic \
  <position-1> <position-2> <position-3> <position-4> <position-5> \
  <position-6> <position-7> <position-8> <position-9>

# After reading that plan:
.venv/bin/python skills/github-workflow/scripts/merge_stack.py --atomic --execute \
  <position-1> <position-2> <position-3> <position-4> <position-5> \
  <position-6> <position-7> <position-8> <position-9>
```

This same form resumes a partially merged stack. Keep the already-merged lower
positions in the command; they are verified and skipped without a PUT. Never
pass only the higher historical position: a hole, reversed order, mixed stack,
closed-unmerged predecessor, 404/unknown merge confirmation, or topology/head
movement refuses before the one irreversible request. Dry-run output separates
the historical prefix from the open suffix so it never describes earlier work
as part of the new atomic merge.

The latency reason is measured, not hypothetical: one ready nine-entry atomic
merge completed in about **6 seconds**, while an older eleven-entry sequential
merge took about **8 minutes 19 seconds**. The group sizes differ, so this is not
a per-entry benchmark; it is evidence that avoiding ten extra request/poll/
retarget cycles removes the dominant stack-merge wait when the whole open group
is already approved and ready. If a rung is not ready, stop before it. A ready
position 1 may merge alone; after that, GitHub preserves historical positions,
so resume later with `--atomic` and the complete prefix rather than passing the
higher PR alone.

**Do not hand-edit a stack member's base.** Inside a native stack GitHub rebases
the next entry onto the stack base by itself. `gh pr edit --base` here fights the
server.

**After the merge, re-read the PRs above.** A member you were about to merge may
already be `MERGED` — swept into the atomic group. `merge_stack.py` reports this
and skips it rather than refusing, because it is documented behaviour rather than
a fault.

## 4. Track B — merging an ordinary pull request

Outside a native stack **nothing retargets, ever** — not GitHub, not `gh`. A base
branch keeps whatever ref it was given at creation, including a ref that has since
merged and stopped moving.

```bash
# 1. THE GUARD: the base must be what you intend to merge into.
gh pr view <n> --json number,state,isDraft,baseRefName,headRefOid

# 2. Merge with a merge commit, pinned to the head you classified.
gh pr merge <n> --merge --match-head-commit <headRefOid>

# 3. Confirm. 204 = merged.
gh api repos/{owner}/{repo}/pulls/<n>/merge > local/scratch/merge-check.log 2>&1
echo "EXIT=$?"

# 4. Read the NEXT PR's base — only now. Edit only when it differs, then read it
#    back. A base already equal to `main` is a no-op; do not retrigger its CI.
gh pr view <n+1> --json baseRefName
gh pr edit <n+1> --base main               # only if the read differed
gh pr view <n+1> --json baseRefName        # after an edit, must say "main"
```

**Step 1 is the guard that `#198` needed.** Checking `baseRefName` before merging
is the entire defence in this world, because every other signal — CI, the API's
reply, the UI's "Merged" badge — is green in the failure case.

**Step 4's read-back is not ceremony.** An unverified retarget is the same bug as
no retarget: you cannot tell them apart from the command's exit code, and the
consequence is identical. The read before editing matters too: an already-correct
base needs no mutation, and skipping that redundant `gh pr edit` avoids starting
another CI run for a PR whose target did not need to change.

**Retarget only after the base has actually merged.** Retargeting `<n+1>` first
makes its diff include its parent's commits, so the PR under review stops being
the change you wrote.

**Never `--squash`, `--rebase`, or `--delete-branch`.** The first two rewrite
every SHA on the branch, orphaning the review-ledger rows keyed to those commit
ranges. Deleting a base branch **closes** the PR above it (this happened to
`#136`) and makes the rewritten commits unreachable, degrading orphaned rows from
`EXISTS here but is NOT an ancestor` to `UNKNOWN OBJECT` in a fresh clone.
`merge_stack.py` rejects all three at argument parsing.

**`gh pr merge --auto` is not a fallback.** `allow_auto_merge` is `false` on this
repo, and GitHub does not support auto-merge for stacks.

## 5. Evidence

Every claim above is a reading of this repo's own history, taken with read-only
`gh`. The commands are reproducible; run them rather than trusting the table.

### The ten stacks

`gh api repos/{owner}/{repo}/stacks` returns ten records. Each stack's number is
its own, and the numbers inside the parentheses are its member PRs, bottom first.

| Stack | Members |
|---|---|
| 193 | 191, 192 |
| 190 | 183, 186, 187, 189 |
| 133 | 122 … 132 |
| 119 | 117, 118 |
| 116 | 113, 114, 115 |
| 112 | 108 … 111 |
| 104 | 99 … 103 |
| 97 | 95, 96 |
| 93 | 89 … 92 |
| 88 | 81 … 87 |

`?state=open` on that endpoint is ignored; filter client-side on `.open`. All ten
read `open: false`.

### Membership is readable, and position is 1-based

`pullRequest(number: 87) { stackEntry { position stack { number size } } }`
returns `position: 7, stack: {number: 88, size: 7}` — #87 is the top of a
seven-entry stack, and `gh pr view 190` fails because 190 is that stack's sibling
object, not a PR.

### Merging a stack is atomic

Three stacks show it directly: every member carries the **same** merge commit.

| Stack | Members | Shared merge commit | Subject |
|---|---|---|---|
| 88 | #81, #84, #87 (checked) | `281bc9333e8f84c8c5049aef808f438df0f335cd` | "Merge pull request #87 …" |
| 116 | #113, #114, #115 | `562655f8fa81b305dc3f6a77c1b6d03b391df228` | — |
| 97 | #95, #96 | `5adfb1f8a1ab7c5d12bca677716fc7cc85d1ad98` | — |

**The tell for reading history:** a stack merged atomically keeps its original
chained bases forever. In stack 88, #81 reads `base=main`, #84 reads
`base=phase-0c/skill-visibility-ssot`, #87 reads
`base=phase-4/remove-inbound-symlinks` — and all three merged in one commit. A
stack merged one entry at a time ends with every entry reading `base=main`
instead. So the base field is a fossil of how the stack was merged, never a
statement about where a member sits now.

### The #198 incident — nothing was red

This is why Track B's guard exists.

| Time (UTC) | Event | SHA |
|---|---|---|
| 05:42:45 | #194 merges `chore/08-capture-answers-and-sign-merges` into `main` | `14aec2ae` |
| 05:44:09 | #198 merges — **84 seconds later** — while its base still reads `chore/08-capture-answers-and-sign-merges` | `a6b5a7da`, parents `06dc5ab` + `4a196a7` |
| 05:45:28 | rescue PR #199 (`chore/08-… → main`) drags the work onto the trunk | `c3af637b` |

#198 was `stackEntry: null`, and its timeline contains **no** `BaseRefChangedEvent`
— nothing retargeted it, because outside a stack nothing ever does. Its first
parent `06dc5ab` is the pre-merge tip of that branch, not `main`. CI passed, the
API returned success, the UI said "Merged". The only signal was `baseRefName`,
and nobody read it.

Reproduce the merge state of any PR without the expiring async record:

```bash
gh api repos/{owner}/{repo}/pulls/198/merge > local/scratch/check.log 2>&1
echo "EXIT=$?"     # 0 -> HTTP 204 -> merged
gh api repos/{owner}/{repo}/pulls/40/merge  > local/scratch/check.log 2>&1
echo "EXIT=$?"     # 1 -> HTTP 404 -> not merged
```

Note the redirect. **Never pipe a command whose exit code you are about to
read** — `$?` after a pipeline is the last stage's status, so `| tail` turns a
red gate green (`AGENTS.md` → Shell & Paths).

### Deleting a base branch closes the child

#136's timeline, one second apart:

| Time (UTC) | Event |
|---|---|
| 21:05:08 | `base_ref_deleted` |
| 21:05:09 | `closed` |
| 21:08:43 | `reopened` (after the branch was restored) |
| 21:08:44 | `base_ref_changed` |
| 21:09:20 | `merged` |

`delete_branch_on_merge` is `false` on this repo and stays that way.

### Repository settings this runbook depends on

`gh api repos/{owner}/{repo}` reports `delete_branch_on_merge: false`,
`allow_auto_merge: false`, `allow_merge_commit: true`, `allow_squash_merge: true`,
`allow_rebase_merge: true`. The last two are enabled server-side and are still
forbidden on a stack by this repo's own rules — the ledger rows are keyed to
commit ranges, and a rewrite orphans them.

## 6. Failure-mode catalogue

Ordered by how convincingly each one looks like success.

| Failure | What you see | What actually happened | Guard |
|---|---|---|---|
| Merged into a stale base | green CI, "Merged" badge, API success | the base branch had already merged and stopped moving; your work landed on it, not on the trunk | read `baseRefName` before merging (Track B step 1) |
| 202 read as "merged" | `gh` exits 0, body says `pending` | the request was only accepted | poll to a terminal state, then confirm 204 |
| `enqueued` read as merged | a terminal status, no error | a merge queue holds the request; the trunk does not have the work | treat `enqueued` as not-merged |
| Retarget that did not take | `gh pr edit` exits 0 | the base is unchanged | re-read `baseRefName` afterwards |
| Redundant retarget reruns CI | the child already targets the intended base | `gh pr edit --base` mutates an already-correct PR and starts duplicate work | read first; skip the edit when equal |
| Whole open stack merged by accident | one merge commit, six PRs closed | merging entry *k* lands every currently unmerged lower entry through *k* atomically | assert position 1, or require explicit complete-prefix `--atomic` |
| `gh pr merge` on a stack member | HTTP 403 | stack members cannot use it | classify first |
| A PR number that will not resolve | "Could not resolve to a PullRequest" | the number names a **stack** | check `/stacks` |
| Base branch deleted | the child PR is closed, not retargeted | GitHub closes children of a deleted base | never `--delete-branch` |
| Re-firing after a 409 | two merge requests | one was already in flight | poll, do not re-fire |
| Ledger rows orphaned | `--verify-all` reports `UNKNOWN OBJECT` | a squash/rebase merge (or a deleted branch) rewrote the SHAs the rows name | merge commits only; never delete a branch |

## 7. What is NOT verified

Written down so nobody promotes a plausible guess into a rule:

- That `gh pr merge --merge` succeeds on a non-stacked PR **in this repo** is
  strongly implied by `allow_merge_commit: true` and an unprotected `main`, but
  it has not been observed here.
- Whether `merge-async` works on a **non-stacked** PR is untested.
- Whether `gh pr edit --base` is refused when a PR has children is untested.
- Whether GitHub ever converts a base-chain into a stack **without being asked**
  is unknown; the documentation implies conversion is an explicit act.

## 8. Running the gates locally

`automation/gates/run_gates.py` runs every blocking gate — the pre-commit chain and
the CI-only suites — as shell-free subprocesses whose output is **redirected**, never
piped, to `local/gates/<name>.log`. The exit code you read is the gate's own.

| Flag | Effect |
|---|---|
| `--list` | print the table and exit without running anything |
| `--impact-from <ref>` | run policy plus the long lanes affected since the ref's merge-base **and by the working tree**; uncertainty expands to every lane |
| `--group hook` \| `--group ci` | run only that group; default is both |
| `--only <a>,<b>` · `--skip <a>,<b>` | narrow the selection by name |
| `--fail-fast` | stop at the first red gate |
| `--tail N` | how much of a failing log prints inline (default 15) |
| `--jobs N` | parallelism; some gates are forced serial because they share the index |

Four behaviours worth knowing before you trust a green run:

- **SKIP is not PASS.** A gate that cannot run here — no LibreOffice for the example
  render, no `private/` mount for the two `--require-roots` forms — reports SKIP, is
  named on its own line in the summary, and is excluded from the green count. The
  final line reads `ALL GREEN (n of N gates ran; k skipped: …)` so the skips are
  never silent.
- **Read the denominator, and know the three exit codes.** `n of N` is how many gates
  actually executed against how many the table holds; a `coverage:` line and, when the
  run narrowed, a `lanes NOT run (…)` line sit directly above the verdict. `ALL GREEN`
  + exit 0 needs at least one gate to have run. A run where **nothing** executed —
  empty selection, or everything skipped — says `NO EVIDENCE` and exits **3**, which is
  neither green nor red: nothing was proven either way. A failure is still `RED` + 1.
- **`example-render` dirties the worktree.** It regenerates four tracked example
  DOCX/PDFs whose bytes are not reproducible. CI does this in a throwaway checkout;
  you are not in one. `git checkout -- examples/` afterwards unless those bytes are
  the point of your change.
- **The table cannot quietly fall behind CI.** `automation/gates/tests` re-parses
  `.github/workflows/ci.yml`, and fails when a step is neither in the table nor
  excused in writing in `NOT_RUN_LOCALLY` — and fails in the other direction too, so
  an excuse for something CI no longer runs is also an error.

**Run the impact-scoped form before opening a PR, not just before committing:**

```bash
.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
```

It uses the same fail-closed path classifier as CI and always includes policy gates.
An unknown, foundational, deleted, or otherwise ambiguous input expands to the full
suite automatically. Run the no-flag full form deliberately when validating a release
or changing the classifier itself. The pre-commit hook remains a strict subset: a
branch can commit clean and still be red in an affected CI-only suite.

**`--lane` is repeatable and comma-separated, and neither form drops a lane.** It
used to be a plain store, so `--lane a --lane b` silently ran only `b` — a run that
asked for two lanes checked one and printed `ALL GREEN`. If you name lanes by hand,
read the `running N of M gates (lane: …)` header back: it echoes what was actually
selected, and the summary's `lanes NOT run (…)` line names what you left out.

### 8.1 Do not substitute your own lane list for the impact-scoped run

Naming lanes by hand is the single most expensive mistake available here, because
it is invisible until CI. Measured on the 2026-08-07 publish cycle: two lanes were
run locally instead of `--impact-from`, the `publish` lane went red in CI, and
recovering cost **42% of the whole 10m32s cycle** — one wasted CI run, the local
diagnosis, and a second CI run. The local command that would have prevented it
takes well under a minute.

**Uncommitted work is no longer invisible.** `--impact-from` compares a committed Git
range, so it once reported `focused; lanes: policy; reason: the Git range contains no
changes`, ran 8 gates in ~28s, and printed `ALL GREEN` over a tree full of unstaged
edits — indistinguishable from a clean full run, and proof of nothing. The runner now
classifies the working tree (tracked edits plus untracked, `.gitignore` honoured) and
**unions** its lanes into the selection, so a dirty tree can only ever widen the run.
Still read the header back: it prints the lanes selected, the lanes **dropped**, and
the uncommitted-change count. A dirty tree therefore costs more gates than a clean
one, and a single unowned untracked file expands to the full suite.

Three guards now exist, and none replaces running the real thing:

- the reconciler's `shipped-docs-name-shipped-tooling` check fails at **commit**
  time when a shipped `docs/handbook/` page names an `automation/` tree that
  `export_public.py` does not export — the specific drift behind that failure;
- `--impact-from` expands to the full suite on any input it cannot classify;
- a run in which no gate executed can no longer read green: it says `NO EVIDENCE`
  and exits 3, and every green line carries `n of N`.

### 8.2 Budgeting the slow steps

Approximate costs, so you can decide what to run and what to background rather than
discovering the cost mid-cycle:

| Step | Typical | Notes |
|---|---|---|
| `--impact-from origin/main --jobs 8` | seconds to a few minutes | scales with how much the diff touches; the cheapest insurance available |
| `tests-gardener`, `tests-cutover` | ~40–110s each | the two slowest local suites |
| `example-render`, the PDF lanes | ~50s | needs LibreOffice; dirties tracked example files |
| One CI run, end to end | ~1.5–2 min | the long pole is `tests (job-search)` |
| `gh pr checks --watch` | as long as CI | it is a *wait*, not work — see below |

Rules that keep those from compounding:

- **Give every watch and every long gate an explicit timeout**, and always
  redirect rather than pipe, so the exit code you read is the command's own.
- **A red CI job is diagnosed locally, never by pushing a guess.** Pull the failing
  job's log (`gh run view --job <id> --log-failed`), reproduce with the matching
  local lane, fix, and only then push. Each speculative push costs a full CI run.
- **Do not re-run green lanes to feel sure.** Re-run the lane that failed plus
  `--impact-from`; the rest already passed on the same tree.
- **Batch the fix.** If one push is going to be needed anyway, land every known
  correction in it rather than discovering them one CI cycle at a time.
- **Checking out `main` mid-task removes any tooling the branch added**, including
  the scripts you may be measuring or validating with. Finish on the branch, then
  switch — and `git fetch` before `git pull --ff-only`, or a stale remote-tracking
  ref makes the pull a no-op that looks like a failure.

## 9. `Closes #N` — the line that closes the loop

**A PR that fixes an issue says so in its body, in a line GitHub parses:**

```
Closes #312
```

One line per issue it fixes, anywhere in the body; `Fixes #N` and `Resolves #N`
are equivalent. GitHub closes the issue when the PR merges into the default
branch, and it does it whether or not anybody remembers.

Why this is written down. Issues here are closed by hand or not at all, and "not
at all" wins: **nine consecutive fix PRs (#329–#337) carried zero closing
keywords**, so every issue they fixed stayed open. An open issue that is already
fixed costs more than a missing one — the next agent researches it, an audit
counts it as outstanding work, and the backlog stops describing the repository.
Merging is the only moment when "this is done" is known for certain and cheap to
record, so that is where the recording belongs.

Rules:

- **The line goes in the PR body, not in a commit message.** A commit trailer
  works only on the default branch's own commits, and this repo merges through
  merge commits and stacks; the body is the surface that always works.
- **A stack member closes only what IT fixes.** Merging a stack lands every
  currently unmerged entry below the selected one through *k* in one merge
  commit, so a `Closes` line on the wrong entry closes an issue before its fix
  is on `main`.
- **Do not use it for an issue the PR only partially addresses.** Write
  `Part of #N` instead — GitHub ignores it, and the issue stays open honestly.
- **Nothing gates this.** It is a convention, deliberately: the eval gate and the
  review gate already fail commits, and one more blocking check would be process
  weight against an open owner decision. Adding the line takes five seconds; the
  cost of forgetting is paid by whoever reads the backlog next.

## Files

| Path | Purpose |
|---|---|
| `skills/github-workflow/SKILL.md` | The router — PR format, stacking, gates, `gh` recipes, and the short merge recipe |
| `skills/github-workflow/scripts/merge_stack.py` | Classifies a PR and merges it the way its world requires; dry run by default |
| `skills/github-workflow/scripts/tests/test_merge_stack.py` | `unittest` suite for the driver — mocked `gh`, no network |
| `automation/publish/review_ledger.yaml` | The append-only review record whose rows a SHA rewrite orphans |
