# Post-merge cutover — the routed fast path

NOTE: this is not automation/reconcile/reconcile.py (the process-layer schema
gate). This inspects git state and writes nothing.

That sentence is repeated verbatim in `plan_cutover.py --help` and pinned by a
test, because two things named "reconcile" in one repository is a guaranteed
misroute. **`automation/reconcile/reconcile.py` is the process-layer schema
referee wired into pre-commit and CI.** If you were told to "run the
reconciler", that is the command you want, and this document is not it. Nothing
under `automation/cutover/` is called reconcile, by design.

## What this page is for

One situation, and only this one: **the prerequisite PRs have already merged,
you are holding local work written against the OLD layout, and the job is to
bring that work onto the merged layout.** The expensive part of that session is
not the edit — it is reconstructing, by reasoning, which of your dirty paths the
merged branch moved, which it also edited, which are git-ignored and have to be
copied by hand, and which nothing in Git explains. All of that is one read-only
command.

Everything else — a new feature, a schema change, a policy change, a skill edit
— takes the broad read order in `AGENTS.md`. Escalating off this page is the
normal outcome for any session doing more than a cutover, and that is not a
failure.

## The commands

```bash
# The plan. Read-only. Always the FIRST thing you run — it decides whether this
# fast path applies at all.
.venv/bin/python automation/cutover/plan_cutover.py --fetch \
    --prereq public:<merged sha> --prereq private:<merged sha>

# One path's full evidence chain (blob ids, rename lookup, residual diff).
.venv/bin/python automation/cutover/plan_cutover.py --explain <repo-relative path>

# Public repository only (no overlay in scope).
.venv/bin/python automation/cutover/plan_cutover.py --repo public --fetch
```

`--fetch` is what authorises network access. It writes remote-tracking refs and
nothing else. **Without it every plan is stamped `stale` and can never be
executable** — the premise of this whole workflow is "the prerequisites just
merged", so the one fact that must be fresh is exactly the one that would
otherwise be guessed.

The plan JSON lands in `local/cutover/<run-id>/plan.json` (git-ignored). A
`--json-out` inside the public repo but outside `local/` is refused: the plan
names real overlay paths and application slugs.

### Exit codes

| Code | Meaning | What you do |
|---|---|---|
| `0` | Every proposed step is mechanical, nothing is blocking, the remote is fresh | Perform the steps in order |
| `1` | The plan is safe to read, but a step needs your judgement, or the remote is stale | Read the plan; run again with `--fetch` if that was the cause |
| `2` | argparse usage error | Fix the flags |
| `3` | **REFUSED** — a fail-closed condition; this state is not safe to describe as a plan | Escalate to the broad read order |

### There is no executor

**The mechanical steps in the plan are performed by the agent, guided by the
plan.** Nothing in this repository executes them. The plan's `argv` entries are
documentation of the exact command to run, not a call site, and `executable:
true` means "these steps are safe to perform as written", not "a program will
perform them".

A guarded executor is a filed follow-up, deliberately not shipped yet: a
read-only planner's worst failure mode is a wasted minute, and an executor's is
a `git rebase` in the owner's real job-hunt data at a moment the tool misread.
It lands after telemetry says the checkpoint/replay interval is worth that blast
radius.

Whatever else changes, these never do:

- **publication is never this tool's job.** Push, PR, retarget, merge and close
  all go through `skills/github-workflow/` and its `scripts/merge_stack.py`
  runbook. The plan emits publication as a `handoff` step naming exactly that;
- **nothing here deletes owner data.** No `rm`, no `git clean`, no
  `git worktree remove`, no `git branch -D`, no `git checkout --`. A retired
  source stays until the owner removes it;
- **an ignored file is copied, never moved, and never over an existing file.**
  A destination that already exists with different bytes is a refusal that only
  the owner can resolve;
- **no gate is ever bypassed.** No `--no-verify`, no `--skip-checks`.

## Arming condition (all three must hold)

1. the request states or implies the prerequisite PRs are **already merged** and
   the goal is to bring preserved local work onto the merged layout;
2. no new feature, schema, policy, or skill change is requested;
3. `plan_cutover.py --fetch` exits `0`, **or** exits `1` with `blocking == []`.

If (3) has not been run yet, running it is the fast path's own first action. The
planner is the arming gate — it is not a judgement call.

## Routed read order when armed

1. `automation/cutover/plan_cutover.py --fetch --prereq …` — the plan table,
   read **before any prose**, because it decides whether this page applies;
2. the prior task's `tasks/<status>/<id>/task.md` and the
   `history/conversations/<…>/handover.md` it names;
3. `skills/github-workflow/SKILL.md` — the push-gates section and the merge
   runbook section only;
4. this page.

### Deliberately NOT read on the fast path

`.agents/MEMORY.md`, `memory/index.md` and memory entries, `docs/designs/**`,
`docs/roadmap/**`, other handbook docs, other skills' `SKILL.md` /
`reference.md`, `docs/handbook/private-overlay.md` (the planner already resolved
the overlay), `docs/handbook/application-folders.md` (no application is being
authored).

### Still mandatory on the fast path

- the boot ritual's **step 1 filename listing** —
  `ls message-queue/needs-agent/requests/` and the private mirror. Filenames
  only; open only what the plan's repositories touch. The contract's valve
  applies: process what fits, name the remainder;
- every hard Guardrail, unchanged: never delete owner data, fail closed, never
  report a failed command as green, no `--skip-checks`, no `--no-verify`;
- the end-of-session handover and worklog. **This page shortens reading, never
  recording.**

## How a dirty path is classified

The evidence is `git diff -M100%` — an exact-blob rename, which is a proof
rather than a score.

| Verdict | What it means | Action |
|---|---|---|
| `unsafe` | a gitlink, a symlink escaping the repo, or a name with a line break | refusal |
| `ignored` | git-ignored; it never replays | copy (create-only), or reported and left alone |
| `unchanged` | the worktree blob equals the fork-point blob | none |
| `renamed-by-merged-layout` | moved upstream, contents untouched (`R100`) | replays by relocation alone |
| `content-divergent` | moved upstream **and** the contents differ | agent resolves |
| `unknown` | no rename evidence and no other explanation | **refusal** |

`unknown` is a refusal rather than a warning on purpose: an unrecognised file in
a tree about to be rebased is exactly the shape of "an ignored source someone
assumes is disposable", and the contract says never infer that.

### The link-rebase residual

For a `content-divergent` path the planner tries to prove the upstream delta was
**path-only**. It applies only the substitutions the exact-rename map itself
licenses — directory prefix pairs derived from `R100` moves, and relative link
targets that resolve into the rename map — and then requires the residual against
the merged text to be **exactly empty**. A target that does not resolve into the
map is never touched.

An empty residual **does not** make the step mechanical. The verdict stays
`content-divergent`; the proof is an input to your judgement, never a substitute
for it. A non-empty residual, or a binary blob, is escalation.

One consequence worth knowing: because `R100` compares identical blobs, a file
the merged branch both MOVED and EDITED is by construction absent from the exact
rename map. Its destination therefore comes from the prefix pairs those `R100`
moves imply — still derived only from proof-grade evidence, and still required to
survive the residual check.

## Escalation — abandon the fast path, take the broad read order

Any one of these:

- the planner exits `3`, or `blocking` is non-empty;
- any dirty path's verdict is `unknown`;
- a `content-divergent` path whose residual is `non-empty` or
  `not-attempted:binary`;
- the `cutover` validation profile is RED;
- a step would touch owner data under `config.applications_root()` in any way
  other than a rename Git itself already performed;
- `automation/reconcile/reconcile.py --check` is red for a finding the plan does
  not explain — that is the OTHER one, the process-layer gate, and a red result
  there means the process layer needs work, not the git layer;
- the request grows to include anything outside the plan's steps;
- `docs/roadmap/` truth changes, or an owner decision becomes necessary.

## Handling the output safely

The human table's first line warns that it names `private/` paths. **Never paste
it into a public PR description, a commit message, or any tracked file.** The
plan JSON carries real application slugs and overlay paths, which is why it
defaults under `local/`. Remote URLs are stored as a `sha256:` digest rather than
the URL. The leak guard catches a slip at the pre-commit/pre-push boundary if one
reaches a tracked file — but that is the backstop, not the plan.

## Notes and known costs

- listing the ignored files that have to be copied requires
  `git status --untracked-files=all --ignored=traditional`, which walks ignored
  directories. Against the real repositories that is ~120,000 dirty paths and
  ~12s. The human table caps how many dirty rows it prints (blocking rows sort
  first, and the separate BLOCKING section is never capped). The JSON emits
  every **actionable** path in full — anything blocking, anything whose verdict
  is not merely `ignored`, and every ignored path that HAS a merged-layout
  counterpart, which is the copy case. Ignored paths with no counterpart and no
  blocking are folded into `dirty_rolled_up` as per-zone counts, with
  `dirty_total` and `zones_omitted`/`paths_in_omitted_zones` so nothing is
  hidden. Without the rollup the plan measured 72 MB, which no agent can read;
  with it, 53 KB. `--full-json` restores one entry per path;
- recovery refs proposed under `refs/cutover/<run-id>/…` are owner recovery data
  and are never deleted by any tool;
- the planner refuses when another registered worktree is dirty or locked. A
  clean, unlocked sibling worktree is reported and does not block.
