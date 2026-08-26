---
name: github-workflow
visibility: public
description: Get finished work from a local branch onto GitHub — refresh main, retire finished agent branches and worktrees, write the PR description, clear push gates, and drive `gh` for PRs, CI, merges, and stack rebases. Use for any GitHub operation in this repo, including pushes, PR creation or editing, CI checks, merges, and post-merge cleanup.
---

# GitHub Workflow — from a finished branch to a merged PR

Everything between "the work is done" and "it is on `main`": how the PR
description is written, how a stack of PRs is built (no special tool), the gates
this repo puts in front of a push, and the `gh` commands for each step.

## When to Use

- "Open a PR." · "Write / rewrite the PR description." · "Describe this branch."
- "Split this into stacked PRs." · "Stack this on top of the previous PR."
- "Is CI green?" · "Why did CI fail?" · "Merge the stack." · "Rebase the stack."
- Any push from this repo — the gates below apply whether or not a PR follows.

## 0. Refresh `main` and retire finished agent work

Before any `gh` command or push, and again after a GitHub mutation:

1. Resolve the owning repository and its `main` worktree. If that worktree is
   clean, always try `git -C <main-worktree> pull --ff-only origin main`. If it
   is dirty, fetch `origin` but preserve every edit and report why the pull was
   skipped. Never stash, reset, or overwrite another worktree to make this pass.
2. If the active task branch must absorb the refreshed `main`, resolve conflicts
   whose correct result is supported by the task and tests. Preserve both sides
   of unrelated or owner-authored changes; a reviewed branch is never
   force-pushed silently. A diverged local `main` is not auto-merged: keep it and
   surface the local-only commits instead of manufacturing a trunk merge.
3. Sweep local branches and worktrees whose branch starts `codex/` or `claude/`.
   “Useless” means fresh `origin/main` already contains its exact tree, not that
   it merely looks old. Also require that no open PR names the branch as head or
   base, no worktree has live changes or a live lock, and retiring it cannot
   orphan unique commits or review-ledger evidence. An unanswerable check keeps
   the item.
4. Retire an unowned local branch with `git branch -d` only. For a worktree, use
   `automation/workspace/cleanup.py --fetch --include-harness-worktrees` and
   carry out only the qualifying `codex/` / `claude/` rows; it moves directories
   into recoverable `local/workspace/trash-*` storage and re-checks safety at run
   time. Never use `-D`, `rm`, or `git worktree remove`. This standing sweep is
   local-only: it does not authorize deleting remote branches.

Run the sweep even when it finds zero candidates, and report that number. The
repository decision behind these boundaries is
`memory/decisions/merged-branches-are-swept-after-their-prs-close.md`.

## 1. The PR description format

**The headline rule: a PR description opens with a section written for the human
who will use the thing, in plain English, before any technical detail.** A reader
must learn what is different for them before meeting a single file path.

Structure of that opening section:

| Part | What goes in it |
|------|-----------------|
| Heading | `## What changes for you` (the first `##` in the body — nothing above it) |
| One sub-block per distinct change | A `###` naming the change in user terms, not module terms |
| **Before.** | What happened, or what was broken, in concrete terms |
| **After.** | What happens now |
| **What you'll notice.** | The practical day-to-day effect — including friction, extra steps, or annoyance |

Writing rules:

- Short sentences. Name the actual command, file, or behaviour.
- No metaphors and no marketing words. The banned list is
  `BANNED_TERMS` in `skills/github-workflow/scripts/check_pr_body.py`
  (`--list-banned` prints it).
- **Say plainly when something gets slower, noisier, or requires manual work.
  A PR that only lists benefits is under-reported** — treat a missing downside
  as a finding against your own draft, not as good news.
- Only after that section come the technical ones: what & why, the design, how it
  was verified, what was filed (tasks, queue items, memory entries).
- This repo's `.github/pull_request_template.md` starts at `## What & why`. The
  human-facing section goes **above** it; the template's checklist stays.

The full fictional worked example lives in
[`reference.md`](reference.md#worked-pr-body-example); read it when drafting a
new body or correcting one that lacks a concrete before/after effect.

### Check the body before posting it

```bash
# From a file
.venv/bin/python skills/github-workflow/scripts/check_pr_body.py local/pr-body.md
# Or from an existing PR
gh pr view <n> --json body --jq .body | \
    .venv/bin/python skills/github-workflow/scripts/check_pr_body.py
```

It checks three mechanical properties of the format: the first `##` heading is
the human-facing one, that section carries at least one `**Before.**` and one
`**After.**`, and no banned word appears in prose (code fences are skipped
entirely; backticking a word lets you name it). Exit 1 lists every
finding with its line.

A fourth property — whether the body discharges the eval gate — needs to know
what the diff touched, so it runs only when the caller passes the changed paths:
CI's `pr-body` job invokes this same script with `--changed-files` (the output of
`git diff --name-only` against the merge-base) and `--eval-gate-only`. That is
gate 11 below, and it is the only one of the four that CI blocks on; run it the
same way before you push. **A pass is not a review** — whether the downsides are
actually stated is a judgment the checker cannot make, so re-read the draft for
that yourself. It does **not** check your numbers; that is the next section.

### A body states exit codes and deltas — never an absolute tree-wide count

**The rule: an individual PR body never states an absolute tree-wide count** —
"2669 references", "161 ledger rows", "43 records", "Ran 41 tests". It states each
gate's **exit code** and the **deltas this PR caused** ("+2 ledger rows",
"+1 canary"). Absolute counts have exactly one home: the **post-merge canonical
counts job**, which measures `main` after the merge, where the number is finally a
property of the tree it names.

**Why, in one line:** a count is a property of a commit, not of a change, so a
number measured on a branch is wrong by construction the moment the stack moves
under it — you author off `main`, measure there, then rebase into stack position,
where every PR below you has changed the very tree the count describes.

Prose alone did not fix this. Four correction passes over one stack rewrote the
same class of false number — 25 bodies, then 11 of 13, then 4 of 41 — and the last
instance (`#177`, claiming 2669 where its real parent gave 2686) was published
*after* three separate prose warnings, one of them written by a pass that then
published wrong numbers of its own. So this is a ban, not a caution. The mechanical
check is filed at P0:
`tasks/0_backlog/2026-07-31-pr-verification-blocks-are-measured-off-the-stack/`.

So, when you write a `## Verification` block:

- **Run the gates on the commit you are actually publishing** — after your last
  rebase, not on the branch you wrote on. The four fast gates cost about four
  seconds together; run them and the SHA in one go, and paste the exit codes:

  ```bash
  git rev-parse --short HEAD    # the SHA that goes beside every result below
  .venv/bin/python automation/reconcile/reconcile.py --check         ; echo "EXIT=$?"
  .venv/bin/python automation/gardener/verify_links.py               ; echo "EXIT=$?"
  .venv/bin/python automation/metrics/instruction_budget.py --strict ; echo "EXIT=$?"
  .venv/bin/python automation/vendoring/sync_vendored.py --check     ; echo "EXIT=$?"
  ```
- **Put the SHA next to every result**, exit code or delta alike: `EXIT=0 (at
  71de852)`. A bare result with no commit beside it is not evidence of anything,
  and a reader cannot tell a stale paste from a fresh one without it.
- **Never combine two runs into one line.** Copying half a transcript from one
  tree and half from another produces a line that matches no commit in the
  history — which is harder to spot, and worse, than a plainly stale number.
- **A delta is a measurement too.** Take it from one run on the commit you are
  publishing, as "`<at your parent>` → `<at your tip>`" — never as arithmetic on a
  figure you read somewhere else.
- **Do not treat "compare against your parent" as a substitute for the ban.**
  Measured on this stack: at `#175` the **correct** count (2668) was exactly equal
  to its parent's, and the **fabricated** one (2670) sat cleanly above it — so the
  comparison would have flagged the truth and passed the invention. It did fire
  correctly at `#174` (2658, below its parent's 2664), and a count above your
  parent's tells you nothing at all. Spotting a suspicious count is free; it is
  never evidence, and it never replaces re-running the gate.
- **If you genuinely cannot re-run something** (it needs the private overlay,
  another machine, a live board), say what it ran on and that it was not
  reproduced. Do not publish a result you did not take.

## 2. Stacked PRs — GitHub detects the pattern, no tool required

Do **not** reach for a special stacking tool. GitHub recognizes a stack on its own
whenever all three of these hold:

1. at least two open PRs in the same repository;
2. the bottom PR targets `main` (or another trunk);
3. each next PR's base branch **exactly equals** the previous PR's head branch.

When it sees that pattern it offers to convert the chain into a stack. So the
whole technique is one flag:

```bash
gh pr create --base main            --head feat/01-parser   --title '...' --body-file local/pr-1.md
gh pr create --base feat/01-parser  --head feat/02-renderer --title '...' --body-file local/pr-2.md
gh pr create --base feat/02-renderer --head feat/03-cli     --title '...' --body-file local/pr-3.md
```

**Accepting that offer changes which merge commands work.** A native stack is a
first-class server-side object with its own number; its members **cannot** be
merged by `gh pr merge` (HTTP 403), they merge through
`PUT repos/{owner}/{repo}/pulls/<n>/merge-async`, one entry merges every entry
below it atomically, and GitHub rebases the next entry itself. This repo has ten
such stacks, so "is this PR in a stack?" is a live question on every merge here.

**When to split at all.** A long task with several separable concerns, where each
piece is one reviewable idea and the lower piece makes sense on its own. If a
reviewer cannot approve the bottom PR without reading the top one, it is one PR,
not a stack. Note that `CONTRIBUTING.md` asks *outside contributors* to avoid
stacks and to state ordering in the descriptions instead; stacking is for
branches you own in this repo.

**Name branches so the order is legible.** A numeric segment does it:
`feat/01-parser`, `feat/02-renderer`, `feat/03-cli`. The number is for humans
scanning `gh pr list`; nothing reads it.

**Canaries run once, at the tip.** A rung of a stack is not a shipping state, so an
intermediate PR that touches a skill's instruction files may discharge gate 11 with
`Eval gate: stack — <why>; tip: <#PR or branch>` — naming the tip is the whole
commitment, and the tip then reports a run covering every skill the **stack**
touched. Read form 3 under gate 11 before using it: the tip's own `pr-body` job
sees only the tip's own commits, so it is bound by the gate only if that diff
itself touches an instruction file.

**Classify first: the two worlds need opposite commands.** `gh pr list`,
`gh pr view` and the UI look identical for a stack member and an ordinary PR. Two
probes tell them apart: `gh api repos/{owner}/{repo}/stacks` lists every stack
(`?state=open` is ignored — filter on `.open`), and GraphQL's
`pullRequest { baseRefName stackEntry { position stack { number size } } }` says
whether *this* PR is in one and where. A **stack member** merges only through
`PUT .../pulls/<n>/merge-async` (`gh pr merge` answers HTTP 403) and needs
`stackEntry.position == 1` — inside a stack `baseRefName` reads `main` for entries
that are not at the bottom, so it proves nothing there. An **ordinary PR** merges
with `gh pr merge <n> --merge` and needs `baseRefName` to be the branch you intend;
nothing retargets it but you. Merging out of order strands the PRs below, and
**deleting a head branch on merge closes** the PR above it rather than retargeting
it (`#136`). Any SHA rewrite orphans the review-ledger rows written on those
branches — see "A stacked PR's row does not survive the merge" below.

**Merging a stack is atomic.** Merging entry *k* merges entries 1…*k* into **one**
merge commit, titled after entry *k*: in stack `#88`, PRs `#81`, `#84` and `#87`
all carry merge commit `281bc9333e8f84c8c5049aef808f438df0f335cd` ("Merge pull
request #87"), so merging the top would have landed all seven. Merge entry 1
unless you want the whole group.

**The merge recipe, and why `delete_branch_on_merge` stays off.** Auto-retarget is
a **stack** behaviour and has nothing to do with `delete_branch_on_merge`: inside a
native stack GitHub rebases the next entry itself, and **outside one nothing
retargets a PR, ever**. Check the setting anyway — `gh api repos/<owner>/<repo> -q
.delete_branch_on_merge` is `false` here and stays that way — because deleting a
base branch closes the PR above it. For a non-stacked PR, merging without an
explicit retarget lands the work on the *previous* branch, wherever that ref now
points: silent, not red, nothing in the UI flags it. That is exactly how `#198`
merged — its base still read `chore/08-capture-answers-and-sign-merges` 84 seconds
after `#194` merged that branch into `main`, so GitHub merged it into the stale
branch as `a6b5a7da` (first parent the pre-merge tip, not `main`) and rescue PR
`#199` had to drag it onto the trunk. CI passed, the API returned success, the UI
said "Merged"; the only signal was `baseRefName`, which nobody read. Full timeline
with SHAs: `skills/github-workflow/reference.md`. Either way the merge is a **merge
commit**, which preserves every SHA — each branch tip carries its own review row,
and the review gate's `WATCHED_PATHSPEC` excludes the ledger file (see "The review
gate: one commit carries its own row" below) — one PR at a time, bottom-up:

```bash
# Do all of this with the driver, which classifies first and refuses rather than
# guessing. Dry run is the DEFAULT — nothing merges without --execute.
.venv/bin/python skills/github-workflow/scripts/merge_stack.py <N> <N+1>

# By hand, TRACK A — a stack member (stackEntry != null), position 1:
gh api --method PUT repos/{owner}/{repo}/pulls/<N>/merge-async \
    -f merge_method=merge -f sha=<headRefOid>   # 202 + exit 0 is a RECEIPT
gh api repos/{owner}/{repo}/pulls/<N>/merge-async/<uuid>   # poll to merged/failed/enqueued
gh api repos/{owner}/{repo}/pulls/<N>/merge; echo "EXIT=$?"  # 0 = 204 = merged
# GitHub rebases the next entry itself — do NOT hand-edit a stack member's base.

# By hand, TRACK B — an ordinary PR (stackEntry == null):
gh pr view <N> --json baseRefName            # THE GUARD: must be `main`
gh pr merge <N> --merge --match-head-commit <headRefOid>
gh api repos/{owner}/{repo}/pulls/<N>/merge; echo "EXIT=$?"  # 0 = 204 = merged
gh pr edit <N+1> --base main                 # only AFTER <N> has merged
gh pr view <N+1> --json baseRefName          # READ IT BACK — must now say `main`
```

**The exit code is not the result.** The async PUT returns HTTP 202
`{"status":"pending",…}` and `gh` exits 0 with nothing merged; of its terminal
states, `enqueued` (a merge queue took it) is terminal *without* being merged. A
409 on the PUT means a request is already in flight — poll it, never re-fire.
`gh api …/pulls/<n>/merge` is the independent check that outlives the async
record: exit 0 (HTTP 204) merged, exit 1 (404) not.

For the **non-stacked** case, do the merge and the retarget in that order.
Retargeting `<N+1>` **before** `<N>` merges makes the child's diff include its
parent's commits, so the PR under review is no longer the change you wrote. And an
unverified retarget is the same bug as no retarget — read `baseRefName` back.
Long runbook, failure catalogue and the evidence: `skills/github-workflow/reference.md`.

Never `--squash`, never `--rebase`, never GitHub's "Update branch" button on such a
stack — each rewrites SHAs, and this repo's ledger rows are keyed to commit ranges,
so rewriting orphans every row above it (the recovery for when that already
happened is "A stacked PR's row does not survive the merge" below).

**And never `--delete-branch`.** Deleting the branch makes the rewritten commits
*unreachable*, so the orphaned rows degrade from `EXISTS here but is NOT an
ancestor` to `UNKNOWN OBJECT` in any fresh clone: the diff a row acknowledges is
simply gone, and the review it records stops being merely unverifiable and becomes
uninspectable. `--squash --delete-branch` on a stack is the likeliest single cause
of this repo's currently orphaned ledger rows. It also closes the PR above it —
deleting a base branch does **not** retarget the child, GitHub closes it, which is
what happened to `#136`; reopening it required restoring the deleted branch first.

**Rebasing the whole stack when the bottom changes.** The recipe above preserves
SHAs, so this trap belongs to a bottom PR that was squash- or rebase-merged anyway
(an older PR, or a merge you did not make). The trap: a plain
`git rebase <new-base>` replays every commit not already in the new base *by
SHA*. After the bottom PR is squash- or rebase-merged, its changes exist on `main`
under **different SHAs**, so git replays them a second time and each one conflicts
with itself. The correct form names the old base tip explicitly, so only the
commits above it are replayed:

```bash
git fetch origin
git worktree list --porcelain  # map each branch to its owning worktree
git -C <worktree-for-02> rebase --onto origin/main <old-base-tip>
git -C <worktree-for-03> rebase --onto feat/02-renderer <old-tip-of-02>
```

Record each branch's old tip (`git rev-parse feat/01-parser`) before it is lost, or recover it from `git reflog`. Create a dedicated
worktree for an unowned branch; never check out one owned elsewhere. Rebase and
force-push bottom-up, following the reviewed-branch guardrail below.

## 3. Gates, in the order you meet them

Everything here is enforced by tracked hooks (install once with
`.venv/bin/python automation/bootstrap_overlay.py`) plus CI. The order is the
pre-commit hook's; **Where** says which copies run, because a gate that runs in
both places is often invoked with different flags in each.

| # | Gate | Where | Fails when |
|---|------|-------|-----------|
| 1 | Staged `private/` paths | hook only | any `private/` path is staged — `git add -f private/` is silent, this is not |
| 2 | Leak guard over the **staged index** (`automation/publish/check_public.py --staged --allow-unarmed`) | hook; CI runs the whole-tree guard last | the blob being committed carries identity tokens, structural PII, or an absolute home path |
| 3 | Public review gate (`automation/publish/review_gate.py --staged`) | hook (`--staged`, bounded tail); CI adds `--verify-all`, and `--head <sha>` on a PR | the tree being committed changes the published tree without a row in `automation/publish/review_ledger.yaml` |
| 4 | Vendor drift (`automation/vendoring/sync_vendored.py --check`) | hook + CI | a `scripts/_vendor/` copy diverged from `automation/shared/` |
| 5 | Mail send-less policy (`automation/shared/mail/check_mail_safety.py`) | hook + CI | any mail path exposes send capability |
| 6 | Byte-compile (`compileall`) | hook + CI | a toolkit or skill script has a syntax error |
| 7 | Instruction budget (`automation/metrics/instruction_budget.py --strict`) | hook + CI | a `SKILL.md` passes 600 lines, a `LESSONS.md` 160, an `AGENTS.md` its tier's budget |
| 8 | Reconciler (`automation/reconcile/reconcile.py --check`) | hook + CI; the hook adds `--require-roots` **only when `private/` is mounted**, CI never does | a queue/task/memory item breaks its `templates/` schema, the memory index is stale, a session has no handover, `skill-manifests` drifted, the roadmap's `Last-updated` line is missing/unparseable/in the future (an OLD date does not gate — that is the gardener's `roadmap-staleness` report) |
| 9 | References + markdown links (`automation/gardener/verify_links.py`) | hook + CI; the hook adds `--require-roots --no-overlay` **only when `private/` is mounted**, CI never does | a backticked path or `[text](path)` in a must-resolve document does not resolve, a skill symlink dangles, or a vendored copy drifted |
| 10 | Leak guard over every outgoing tree, armed | `automation/hooks/pre-push` | each non-deletion ref's exact local OID is scanned, so a non-HEAD branch or another worktree cannot bypass the guard. It also refuses when the guard is UNARMED (no identity tokens) or a stored file cannot be OPENED; a file it opens but cannot text-extract is counted in the `content read: N of M` line, not a failure |
| 11 | Eval gate discharged in the PR body (`skills/github-workflow/scripts/check_pr_body.py --eval-gate-only`) | CI only — the `pr-body` job, blocking | the diff touches a skill's `SKILL.md`, `LESSONS.md`, or `reference.md` and the body carries none of the four discharge forms below |

`--require-roots` asserts that every root a checker names in a constant still
exists, so a rename breaks the check instead of silently disarming it. It is a
**maintainer-checkout** assertion — the published export ships fewer roots — which
is why both hook branches key on `private/` and CI never passes it. A link-check
failure is gate 9, not a reason to reach for `--no-verify`.

CI additionally runs what no hook does: every unit suite, the example render, the
example-store validation, and an independent `gitleaks` secret scan in its own
job — plus gate 11, which reads the PR description itself.

### Running the gates locally, in one command

`.venv/bin/python automation/gates/run_gates.py` runs the table above **plus** every
CI-only suite — no shell, **no pipe**, output redirected per gate, so the exit code
you read is the gate's own. Never shorten a gate with `| tail` and then read `$?`:
that is the pager's status, and it has read a red gate as green here before. SKIP is
never a PASS. **Before every PR**, run `--impact-from origin/main --jobs 8`; it
includes policy and expands uncertainty to the full suite. **Never substitute a
hand-picked `--lane` list — measured at 42% of a publish cycle when it goes wrong.**
The hook is a strict subset of CI. Full form, skips, CI drift, step costs, and the
rules that stop a red CI job costing extra cycles: `reference.md` §8.

### Gate 11 — discharging the eval gate in the body

A PR that edits `skills/*/SKILL.md`, `LESSONS.md`, or `reference.md` must
discharge the risk-based eval gate (`evals/README.md`) **in the PR body**. This is
no longer self-policed: CI's `pr-body` job runs the checker with
`--eval-gate-only` over the description and the diff, and fails the PR when the
body carries none of these four forms:

1. **Ran** — paste the canary results, or name the recorded run under
   `evals/results/`, or write `Eval gate: ran — <what ran, how it went>` with the
   detail filled in. Naming a real record file under `evals/results/` discharges
   the gate on its own, wherever it sits in the body.
2. **Skipped** — `Eval gate: skipped — <intention + size>` with the rationale
   **actually written**. The bare placeholder fails by design, and so do `N/A`
   and `TBD`; quoting the form is not discharging the gate.
3. **Stack** — `Eval gate: stack — <why this one is intermediate>; tip: <#PR or
   branch>`, for an **intermediate** PR of a stack whose canaries run once at the
   tip. The tip must be named on that same line (a PR number, a pull URL, or a
   branch name) — a bare "it's a stack" is a form every PR can type, and a file
   path is not a name. **This form verifies nothing**: the tip's run does not
   exist yet at this PR's CI time, and CI never reads another PR's body, so the
   obligation moves to the tip — which the gate binds only if the tip's OWN diff
   touches an instruction file. When it does not, file one `tasks/0_backlog/`
   item **per stack** for the tip run. A stack whose tip never ran is caught by
   auditing merged bodies for `Eval gate: stack`, not by any check
   (`evals/README.md` → "Stacked PRs").
4. **Debt** — `Eval gate: debt — <why not now>` **plus** the `tasks/0_backlog/`
   item you name in the body, added by the **same diff**. Debt that is not filed
   is a skip without a rationale, and the job says so. This form exists because
   pre-merge canary discharge is not always reachable at batch size — one measured
   canary run cost about a session's worth of turns and tokens, and roughly half
   the PRs in a recent batch touched a skill instruction file — so the gate takes
   tracked debt over a meaningless skip.

The job reads the whole body, fences included: a pasted canary table is evidence.
It checks only this property — the three format properties stay yours to run
locally. The workflow lists `edited` among its `pull_request` types, so fixing the
description after the job goes red re-runs it; no empty commit is needed.

### The review gate: one commit carries its own row

Every commit that changes the public tree needs a row in
`automation/publish/review_ledger.yaml`. The pre-commit hook runs the gate with
**`--staged`**, so what it judges is the **staged index** — the tree *this* commit
will have — not HEAD. The loop is one step:

```bash
git add <the paths this commit changes>   # explicit pathspecs; never -A or .
.venv/bin/python automation/publish/review_gate.py --staged   # prints the row
# read the diff it prints, append the row, then:
git add automation/publish/review_ledger.yaml && git commit
```

`git add -A` is wrong here for a reason beyond tidiness: it stages whatever the worktree
carries — scratch, a stray link, another agent's edits — under a row certifying your diff.

The row it prints carries **no `commit:`** — the commit has no SHA yet. That is a
**pending row**: `base:` + `digest:` pin the range, and the gate resolves its
endpoint later as *the commit that introduced it into the ledger*. Because the
ledger is excluded from `WATCHED_PATHSPEC`, staging the row cannot change the
digest the row records, so the change and its review ride in **one commit**. No
closing ledger-only commit, and one less edit to the file every parallel branch
also edits.

A row naming an already-landed commit (`commit:` + `base:`) is unchanged, still
verifies, and is still the **only** shape for history that is already in — a merge
commit you did not make, or a reconciliation row after a rebase orphaned one. A
default (non-`--staged`) run prints that shape.

The ledger is **append-only**: every row's `digest` is recomputed from the range
it claims, so rewriting a row is itself detected. A row is written after reading
the diff — the digest forecloses guessing, it does not prove reading.

**Still open:** GitHub's merge button appends nothing, so when `main` has moved
since your branch was cut, the merge commit itself is unreviewed and `main` lands
red until someone signs it. Merging **locally** (`git merge --no-ff`, then commit
with a pending row for the merge) avoids that; a button-merge still needs the
reconciliation row below.

### A stacked PR's row does not survive the merge

A row names a **branch tip**, and updating a stacked PR onto its newly merged base
**rebases it — every commit gets a new SHA**. So a row acknowledged before the
merge names a commit that never lands on `main`. The review was real; the commit
is not in the trunk's history.

The gate handles this rather than jamming: it builds the chain from the rows whose
commit **is** an ancestor of HEAD, skips the orphans, and reports them by name
(`EXISTS here but is NOT an ancestor` when the commit is still in your object
store, `UNKNOWN OBJECT` when it is not — a fresh CI clone carries only reachable
objects, so a deleted branch's commits are simply gone there).

**After merging a stack, on the trunk:**

1. Find trunk's worktree with `git worktree list --porcelain`; when it is clean,
   fetch and `merge --ff-only origin/main` there with `git -C`, then run the gate.
2. **Never edit or delete the orphaned rows.** Append a reconciliation row for the
   trunk tip using the range the gate prints, whose `finding:` says the content was
   already reviewed on the branches and names the twins that landed.
3. Commit it (ledger-only), push, and CI goes green — the recovery uses no orphaned
   commit as a base, so it works in a clone that does not have them.

### The PR body and commit messages are public text

They are written into this public repo's history and its GitHub page, and they are
**not** covered by the staged-index leak guard once they leave your machine.
Three mistakes the leak guard has caught exactly:

- **naming a company from the owner's private tree** — company names are not
  identity tokens, so this one is caught by the review gate's read, not the token
  scan; write `<company>`;
- **quoting a private file** — a recruiter email, an application note, a private
  design doc. Describe the shape, quote nothing;
- **pasting terminal output containing an absolute home path** — `/Users/<name>/…`
  in a verification transcript. Redact to `<repo-root>` before committing.

### Commit-message trailers

Every commit made by an agent in this repo ends with:

```
Co-Authored-By: <model name> <noreply@anthropic.com>
Claude-Session: <session url>
```

Subject line: imperative, ≤72 chars, saying *what* changed; body says *why*
(`CONTRIBUTING.md`). A ledger-only commit says so in its body — "Ledger-only
commit; changes no watched file."

### Never `--no-verify`

`AGENTS.md` forbids it outright, for commit and push alike. The gates above are
the repo's only defense against publishing personal data, and the one failure
they prevent is irreversible: once a blob is in a commit it is in the history.
Fix the finding, or let `reconcile.py --file-retries` queue it. Never weaken a
check to make a commit pass.

## 4. `gh` recipes

| Task | Command |
|------|---------|
| Create a PR with an explicit base | `gh pr create --base <prev-branch> --head <this-branch> --title '<t>' --body-file <path>` |
| List open PRs with base/head | `gh pr list --state open --json number,title,baseRefName,headRefName` |
| CI status for a PR | `gh pr checks <n>` (add `--watch` to block until it settles) |
| Find the failing run | `gh run list --branch <branch> --limit 5` |
| Read a failing run's log | `gh run view <id> --log-failed` |
| Merge state | `gh pr view <n> --json state,mergeable,mergeStateStatus,baseRefName` |
| **Is this PR in a stack?** (nothing else answers it) | `gh api graphql -f query='query { repository(owner:"<o>", name:"<r>") { pullRequest(number:<n>) { baseRefName stackEntry { position stack { number size } } } } }'` |
| List the repo's stacks | `gh api repos/{owner}/{repo}/stacks --jq '.[] \| {number, open, prs: [.pull_requests[].number]}'` — `?state=open` is ignored, filter on `.open` |
| Merge a **stacked** PR (`gh pr merge` = HTTP 403) | `gh api --method PUT repos/{owner}/{repo}/pulls/<n>/merge-async -f merge_method=merge -f sha=<headRefOid>`, then poll `…/merge-async/<uuid>` |
| Merge a **non-stacked** PR | `gh pr merge <n> --merge --match-head-commit <headRefOid>` — never `--squash`, `--rebase`, or `--delete-branch` |
| **Did it actually merge?** | `gh api repos/{owner}/{repo}/pulls/<n>/merge; echo "EXIT=$?"` — 0 (204) merged, 1 (404) not. Never through a pipe |
| Retarget (**non-stacked only**), after its base merged | `gh pr edit <n+1> --base main` then `gh pr view <n+1> --json baseRefName` to read it back |
| Do all of the above safely | `.venv/bin/python skills/github-workflow/scripts/merge_stack.py <n> …` (dry run by default) |

**`gh pr list` and `gh pr view` disagree with reality in a useful way.** Both keep
reporting `baseRefName: feat/01-parser` after that PR merged and its branch was
deleted — they report the stored ref, not a live branch. The disagreement surfaces
at creation time: `gh pr create --base feat/01-parser` fails with
`Base ref must be a branch`. That error means the base merged, not that you typed
it wrong. Fix it by rebasing onto `main` with `--onto` (above) and retargeting
with `gh pr edit <n> --base main`.

**Neither one surfaces stack membership at all** — there is no flag for it, which
is why the table's first row goes to GraphQL. And a **failing `gh pr view <n>` may
mean `<n>` is a stack**: stacks draw their numbers from the same sequence as pull
requests, so `gh pr view 190` answers "Could not resolve to a PullRequest" because
190 names a stack, not because a PR was deleted. Check `/stacks` before concluding
anything is missing.

## Guardrails (inviolable)

- **Never `--no-verify`** or weaken a gate. A refusal spells out the whole valid path: explicitly stage; run the staged gate; read its diff; append its exact row; stage the ledger; commit once.
- **Never force-push a reviewed branch silently** — comment with what changed and why. In deleted-base recovery, also identify `Base ref must be a branch` as the merged-base signal before `--onto` and retargeting.
- **Never merge a stack without classifying it first.** A stacked PR and an
  ordinary one need opposite commands and look identical in `gh` and the UI.
  Bottom-up, one at a time, and confirm each merge before the next: for a stack
  member the confirmation is a terminal `merged` from `…/merge-async/<uuid>`
  (`enqueued` is not merged); for an ordinary PR it is `baseRefName` read *before*
  and `gh api …/pulls/<n>/merge` → 204 read *after*. Never a green exit code alone.
- **Never `--squash`, `--rebase`, or `--delete-branch` a stacked PR** — a merge
  commit in both worlds; the retarget is yours to do only when the PR is *not* in
  a native stack, and inside one it is GitHub's (§2).
- **Never put an absolute tree-wide count in a PR body** — exit codes and this
  PR's deltas only; totals come from the post-merge canonical counts job (§1).
- **A PR whose CI is red is not ready, regardless of local results.** Do not ask
  for a merge, and do not explain the red away.
- **Verify in a config-less checkout before claiming CI will pass.** A detached
  worktree in the gitignored scratch tree reproduces CI's environment — no
  `config.yaml`, no `private/` overlay, no token secret. This has caught three
  real CI failures that passed locally:

  ```bash
  ci_probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/jobhunt-ci-check.XXXXXX")"
  git worktree add --detach "$ci_probe_dir" HEAD
  # After checks, require `git -C "$ci_probe_dir" status --short` to be empty:
  git worktree remove "$ci_probe_dir"
  ```

- **The PR body and commit messages are public.** No company from the private
  tree, no quoted private file, no absolute home path (see above).
- **Never delete owner data** to make a gate pass — propose it in
  `message-queue/needs-human/` and stop.

## Files

| Path | Purpose |
|------|---------|
| `skills/github-workflow/SKILL.md` | This router — format, stacking, gates, `gh` recipes |
| `skills/github-workflow/reference.md` | The long two-track merge runbook: classification, Track A, Track B, the failure catalogue, the verified evidence, and §9 — the `Closes #N` line every fix PR's body needs |
| `skills/github-workflow/scripts/merge_stack.py` | Classifies a PR (stack member vs ordinary) and merges it the way that world requires; dry run by default, refuses rather than guessing |
| `skills/github-workflow/scripts/check_pr_body.py` | Validates a PR body against the human-facing format (file or stdin; exit 1 with findings) |
| `skills/github-workflow/scripts/tests/` | `unittest` suite for the checker |
| `evals/canaries/github-workflow.yaml` | Canary set for this skill (`evals/README.md`) |
| `.github/pull_request_template.md` | The checklist half of a PR body; the human-facing section goes above it |
| `automation/publish/review_ledger.yaml` | The append-only review record the review gate reads |
| `CONTRIBUTING.md` | Contributor-facing rules: branch naming, the check list, the eval gate |
