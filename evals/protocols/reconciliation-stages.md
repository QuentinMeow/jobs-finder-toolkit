# Reconciliation stages (R-leg) — post-merge two-repository reconciliation

The stage decomposition for the "the prerequisite PRs merged; reconcile preserved local work and
publish the remainder" workflow, under the existing protocol in
[`stage-benchmarks.md`](stage-benchmarks.md). That file is the procedure (fixtures, subject-agent
prompt rules, A/B rules) and nothing here replaces it; this file supplies the R-leg's stage
boundaries, its isolating fixture variant per stage, and its pinned prompts — the same three things
[`stage-map.md`](stage-map.md) §D supplies for the search and draft legs.

Stage rows are comparable only against other rows of the **same stage + fixture version + model
id**, and **stage rows do not sum to a leg total** (an isolated stage re-pays boot and loses
cross-stage carryover). Both rules are inherited unchanged.

## Fixture

One generator, one version, three variants:

```bash
.venv/bin/python automation/evals/reconciliation_fixture.py list-variants
.venv/bin/python automation/evals/reconciliation_fixture.py build \
    --out local/reconciliation-bench/fixture-1
.venv/bin/python automation/evals/reconciliation_fixture.py verify \
    --out local/reconciliation-bench/fixture-1
```

`automation/evals/reconciliation_fixture.py` builds two git repositories — a public toolkit repo
whose `me/` → `person/` layout refactor is **already merged**, and a nested private overlay at
`private/` whose local branch still sits on the pre-refactor commit carrying **a small uncommitted
patch authored against the old paths**. It carries the generated-file path-only conflict, the
git-ignored file that must be copied non-overwriting and retained at the source, and public closeout
records that the real reconciler grades. `FIXTURE_VERSION` is `recon-v1`; the commit SHAs are pinned
in `PINNED_SHAS` and asserted by `automation/evals/tests/test_reconciliation_fixture.py`, so a recipe
edit without a version bump turns the `tests-evals` gate red. **A fixture version bump invalidates
every row recorded against the previous version** — state the version on every row.

| Variant | What it adds | Isolates |
|---|---|---|
| `base` | the scenario as written; the ignored file's copy destination is FREE | R1, R2, R4 |
| `destination-exists` | a DIFFERENT ignored file already at the destination, so a non-overwriting copy has something to refuse | R3 |
| `closeout-done` | the closeout records already written — the control arm on which the reconciler starts green | R4 (control) |

This fixture lives in the **public** tree, which is the narrow exception the "Fixtures" section of
[`stage-benchmarks.md`](stage-benchmarks.md)
records: it is synthetic by construction, generated rather than captured, and carries no identity
(the persona is the repository's fictional "Jordan Rivers" example). The private rule still governs
every fixture that is a snapshot of a real intermediate.

## Stages

Four stages. Each is a distinct agent activity with one observable boundary.

| # | Stage | Recorder phase | Fixture variant | Observable boundary |
|---|---|---|---|---|
| `R1` | Two-repository inventory (read-only) | `inventory` | `base` | the complete inventory of BOTH repositories is stated: branch, upstream, worktrees, dirty paths, ahead/behind, remotes |
| `R2` | Dirty-path classification and plan | `plan` | `base` | every dirty path carries a classification (unchanged / renamed by the merged layout / content-divergent / ignored / unknown) and the proposed step sequence exists |
| `R3` | Validation profile | `validation` | `destination-exists` | every validation in the profile has reported an exit code and none was silently skipped |
| `R4` | Closeout records | `closeout` | `base` | `automation/reconcile/reconcile.py --root <fixture>/public --check` exits 0 |

### Deliberately NOT benchmarked

- **Mutation / execution.** The guarded executor of the parent task's solution step 3 is
  **deferred and does not exist**, so no stage measures one. `automation/evals/reconciliation_bench.py`
  runs no `git rebase`, `reset`, `checkout`, `merge`, `push`, `rm` or `clean` against the fixture,
  and a test asserts that. When the executor ships, it gets its own stage in this file, its own
  entry variant, and its own pinned prompt — added, never retrofitted onto R1–R4, whose rows would
  otherwise silently change meaning.
- **Publication (PR open → merge).** External wait by definition. The completed
  `2026-08-03-reduce-pr-ci-and-stack-latency` measurements cover hosted checks and stack merging;
  this leg reuses them and reports publication time *beside* its result, never inside it.
- **Retry / failure classification.** Struck from [`stage-benchmarks.md`](stage-benchmarks.md) on
  2026-08-02 because the tool it named was never built. **Do not re-add it here.** Record
  `tool_calls`, and in prose whatever failures you actually observed, with "not measured" where you
  did not.

## Each row has two halves

**The subject-agent half** is the row. A fresh, model-pinned agent gets the stage's pinned prompt
below, with the fixture instantiated and `JOBHUNT_CONFIG` unset (examples fallback), and the row
records `total_tokens`, `tool_calls` and `wall_clock_s` at the boundary. This is where the cost is,
and it is measured exactly as [`stage-benchmarks.md`](stage-benchmarks.md) prescribes.

**The deterministic half** is the floor: the commands that stage cannot avoid, timed with no model
in the loop.

```bash
.venv/bin/python automation/evals/reconciliation_bench.py --list-stages
.venv/bin/python automation/evals/reconciliation_bench.py --stage R1 --runs 3
```

It builds a fresh fixture per run, executes the stage's pinned step list, and prints median + range
per step plus a `evals/results/TEMPLATE.md` stage-row fragment. **At least three runs** — the parent
task's definition of done requires median *and* range for every stage, not only end to end. The
harness exits 1 if any step returned an exit code other than the one the stage expects (R4's first
reconciler call expects **1** — a red entry condition is the stage's premise, and a harness that
accepted anything there would report a green row for a fixture that had stopped reproducing the
scenario).

Reading the two halves together is the point: a stage that costs the agent four minutes over a
0.4-second floor has located 3.6 minutes of agent time, and that subtraction is why the floor is
measured separately. `total_tokens` and `tool_calls` are `not_measured` in the deterministic half —
no model runs in it, and an estimate there would be a fabricated number.

## Phase telemetry (optional)

When the opt-in phase recorder is armed, pass `--phase-session ID` (and `--phase-log-dir` when it is
not the default) and the harness embeds `automation/metrics/phase_summary.py --json` output under
`phase_summary`. The recorder phase to bracket each stage with is in the table above. When the
recorder is absent the field reads `recorder absent` and **every other number is unchanged** — the
harness's own `time.monotonic()` is always the authoritative timing, so a row never depends on the
recorder existing.

## Pinned prompts

Give these verbatim to a fresh subject agent, with `<FIXTURE>` replaced by the built fixture root.
They tell the agent to do the stage's job per the normal repository instructions; they do **not**
inline shortcuts, because the point is to measure the instruction surface as agents actually
experience it. Do not edit a prompt mid-comparison — a prompt edit invalidates the pair exactly as a
fixture edit does.

### R1 — inventory

> Two git repositories are mounted: a public toolkit repo at `<FIXTURE>/public` and its private
> overlay at `<FIXTURE>/public/private`. Prerequisite work has merged upstream. Before changing
> anything, report the complete current state of BOTH repositories: current branch, its upstream and
> ahead/behind counts, every worktree, every dirty or untracked path, every ignored file that is not
> regenerable, and each remote. Do not mutate either repository. Stop when the inventory is complete.

### R2 — classification and plan

> Using the inventory of `<FIXTURE>/public` and `<FIXTURE>/public/private`, classify every dirty path
> in the overlay as unchanged, renamed by the merged layout refactor, content-divergent, ignored, or
> unknown — using git object ids and `-M100%` rename evidence, not filename similarity. Then write
> the exact checkpoint, replay and validation steps you would run, in order, with the recovery ref
> each mutation would leave. Do not run any of them. Fail closed: if any path is unknown, any
> content genuinely diverges, a remote is missing, or a worktree owns a branch you would move, say so
> and stop instead of proposing a step.

### R3 — validation profile

> In `<FIXTURE>/public` and `<FIXTURE>/public/private`, run the validations this reconciliation
> requires and report one set of exit codes: the application metadata is well formed, the generated
> calendar points at the post-refactor layout, the configured paths resolve to tracked files, and the
> git-ignored cache file is intact. The ignored file must be copied to the new layout **without
> overwriting anything already there** and **without being removed from its old path** — check
> whether a copy is safe and say what you would do; do not perform it. Report every check's real
> exit code, including the ones that passed.

### R4 — closeout

> The functional reconciliation in `<FIXTURE>/public` is finished. Produce the closeout records the
> repository's process layer requires, then prove it with
> `automation/reconcile/reconcile.py --root <FIXTURE>/public --check`. Report the reconciler's exit
> code before and after your changes. Do not weaken, skip or work around any check to make it pass.

## Recording a row

Use the **Stage row** section of [`../results/TEMPLATE.md`](../results/TEMPLATE.md), with `Stage id`
set to `R1`–`R4` and `Fixture` set to `recon-v1` plus the variant. Paste the harness's row fragment
beneath it as the deterministic half. State the model id, the fixture version and the SHA pair on
every row — all three bound its validity.
