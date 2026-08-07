# Verification — reduce agent development-cycle latency

- **Date**: 2026-08-07
- **Runtime**: macOS (Darwin 25.5.0), `.venv/bin/python`, git 2.23.0

## What shipped

| Component | Path | State |
|---|---|---|
| Phase recorder + redacted summary | `automation/metrics/phase_recorder.py`, `phase_summary.py` | shipped |
| Read-only two-repository planner | `automation/cutover/plan_cutover.py`, `classify_dirty.py` | shipped |
| Validation profile + two new checkers | `automation/cutover/validate_cutover.py`, `check_configured_paths.py`, `verify_copy.py` | shipped |
| Pinned fixture + stage harness | `automation/evals/reconciliation_fixture.py`, `reconciliation_bench.py` | shipped |
| Routed continuation fast path | `docs/handbook/post-merge-cutover.md` | shipped |
| Guarded executor | — | **deferred**, see the decision item below |

## Gate block, re-run on the INTEGRATED branch

Parallel agents' per-branch numbers do not survive stacking, so every gate was re-run after
integration. Exit codes read from redirects, never a pipe.

```
.venv/bin/python automation/gates/run_gates.py --lane maintenance --jobs 4   # EXIT=0
.venv/bin/python automation/gates/run_gates.py --lane policy --jobs 4        # EXIT=0
```

- **maintenance — 9/9 PASS**: tests-reconcile, tests-metrics, tests-gates, tests-ci-classifier,
  tests-hooks, tests-github-workflow, tests-evals, tests-cutover, tests-gardener.
- **policy — 8/8 PASS**: review-gate-verify-all, instruction-budget, vendor-drift, compileall,
  mail-send-less, reconciler, verify-links, leak-guard-tree.

`classifier.LANES == LONG_CI_LANES` still holds — `tests-cutover` was added as a GATE in the
existing `maintenance` lane, never as a new lane, so `--impact-from` does not silently fall back to
the full suite.

## Defects found by adversarial review, and fixed

An adversarial safety pass was run against the integrated tree after the gates were already green.
Green gates were the floor, not the evidence: it confirmed four defects, all now fixed with
regression tests.

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | `--explain` discarded the blocking list and exited **0** for conditions that exit 3 without it — exit 0 asserts `blocking` is empty | 4 codes reproduced (`remote-missing`, `fetch-failed`, `json-out-tracked-destination`, `prereq-unreachable`), each 3 → 0 | `plan_cutover.py` returns 3 when blocking is non-empty; `test_explain_still_refuses_when_the_inventory_is_blocked` |
| 2 | An all-SKIP selection printed `ALL GREEN` and exited 0 — inverting `verify_copy.py`'s exit 3, which exists so an unrun check can never read green | `--only copy-checksum --manifest /nonexistent` → EXIT=0 | `summarise(require_pass=True)` (additive; repo lanes unchanged) + `rollup()`; two tests |
| 3 | The default copy manifest derived from a per-invocation run id, so `copy-checksum` could **never** find one — the documented command always skipped the gate proving the owner's ignored payloads survived | `--list` showed `SKIP HERE` on the default path | manifest defaults to the stable `local/cutover/copied.txt`; `test_the_manifest_default_is_stable_not_per_invocation` |
| 4 | `JOBHUNT_OVERLAY_RECONCILE=0` **armed** the branch it disables (`-n` is "non-empty"); armed, it points the public reconciler at the overlay and blocks every private commit | measured under `/bin/sh`: `0`, `false`, `off`, `no` all ARMED | `= "1"`; `test_only_the_literal_one_arms_the_toolkit_reconciler` covers 5 spellings |
| 5 | A worker crash in the planner's thread pool exited **1** ("readable plan, needs judgement") instead of 3 | `--public-root /nonexistent` → EXIT=1 | fail-closed wrapper returning 3; `test_an_unexpected_crash_refuses_rather_than_exiting_one` |

### Second pass — adversarial correctness review (134-mutation campaign)

A second reviewer ran a mutation campaign and a manual attack. It **withdrew two of its own
findings** after I disproved them against the current tree (`check_configured_paths` does append
UNCLASSIFIED/STALE rows to `failures` and returns 1; `--only X --skip X` already returned 1). The
rest were verified before acting.

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | **The partition invariant was false under concurrency.** Class totals were read from the raw sum of each wrapped child's duration, discarding the de-overlapped tiling already computed. `active` is the residual, so overlap drove it to **0**. | 3 concurrent children in a 6.3s session: `subproc 18.0s` under `TOTAL 6.3s`; classes summed to 18.1s against a 6.3s reference | totals AND per-phase rows now read the tiling; `wrapped_*` stays as the declared overlay; 2 tests incl. the concurrency case |
| 8 | Same defect via an approval window containing a wrapped run — `active 70.0` where the truth was 80.0, `accounting_error` False | reproduced | closed by the same fix; verified `active 80.0` |
| — | The clamp path was only reachable via that bug, so a child declaring more time than the session existed became undetectable once tiled | — | new `integrity.overlong_runs` counter + note; the anomaly is reported, not absorbed |
| 3 | **`copy-checksum` still could not run.** My first fix moved the mismatch rather than closing it: the planner writes `local/cutover/<run-id>/copied.txt`, the validate step passed no `--manifest`. | read | one hoisted `manifest` shared by both steps |
| 5 | **`--root` + `--file-retries` deletes queue items inside the inspected tree** — a flag documented as read-only inspection. Violates "agents never delete owner data". | victim tree lost a file | combination refused (exit 2); test asserts the victim survives |
| 7 | `--root <any directory>` reported **"OK (9 checks clean)"** — verified green for an empty dir, `/private/tmp`, and `$HOME`. Every check no-ops when its root is absent. | reproduced | refuses a tree carrying no process root; 2 tests |
| 4 | `check_skill_manifests` imported `sync_skill_manifests` from `<--root>/automation/publish`, so an inspected tree could **certify itself** | read | resolved from `__file__`, tree under test passed as an argument |
| 6 | `main()` rebound module globals with no restore, so a later in-process call with no `--root` kept inspecting the previous root while printing OK | read | `try/finally` restore; test proves no leak between calls |
| 16 | A signalled child returned Python's negative code, so `sys.exit(-15)` became **241** where an unwrapped shell reports 143 — the wrapper changed the code it promises to pass through | measured | `128 - code`; verified wrapped == unwrapped == 143 |
| — | `_inproc_ignored_destination_protected` returned 0 on **every** branch, including the one whose message read "a copy must refuse" | read | asserts the destination still holds its own bytes; green on R3's designed variant, red on an overwrite |

The compound finding worth naming: `verify_copy`'s never-overwrite guarantee had three layers, and
all three were compromised at once — `plan_copy`'s symlink refusal and `create_only`'s `O_CREAT|O_EXCL`
were **correct but untested** (both mutated cleanly through the whole suite), and the `copy-checksum`
gate that would have caught a regression was the one that never ran. Both guards now have tests; the
gate now runs.

Remaining medium findings and coverage gaps are filed:
[2026-08-07-cutover-tooling-review-remainder](../../0_backlog/2026-08-07-cutover-tooling-review-remainder/task.md).

Attacked and **held**, no finding: the never-delete-owner-data rule (every delete path in
`verify_copy`, `reconciliation_fixture --force`, and the planner refused, including through a
symlinked destination and a planted manifest); the planner's read-only claim (`hash-object` without
`-w` is enforced by an allowlist, `--no-optional-locks` on every call so `git status` cannot rewrite
the index); and the summary's structural redaction (a session poisoned with a real name, email,
employer, and home path produced a clean summary in all three render modes).

## Measured: the plan JSON was unusable as a handoff

The planner's JSON is the mechanism by which "later steps do not rediscover the state". Measured
against both real repositories, one entry per dirty path produced a plan no agent could read.

| | before | after |
|---|---|---|
| plan JSON | **72,046,928 B** | **53,363 B** (1350× smaller) |
| peak RSS | 342 MB | 133 MB |
| wall clock | 12.5 s | 11.6 s |
| blocking conditions reported | 45 | **45** (identical codes) |
| dirty paths seen | 110,955 private + 9,727 public | unchanged — every one still counted |

Only git-ignored paths with **no** merged-layout counterpart and no blocking condition are folded,
into per-zone counts carrying `dirty_total`, `zones_omitted`, and `paths_in_omitted_zones` so a cap
can never read as "that was everything". Every ignored path that DOES have a counterpart — the
non-overwriting copy case the tool exists to catch — keeps its full entry, pinned by
`test_the_rollup_never_folds_a_path_that_needs_copying`. `--full-json` restores one entry per path.

## Fixture determinism

Two `build` runs into different destinations produced byte-identical commit SHAs, and reproduced
again under a hostile `HOME`/`~/.gitconfig` (`init.defaultBranch=trunk`, `core.autocrlf=true`,
`commit.gpgsign=true`, `diff.renames=false`) and hostile `GIT_AUTHOR_*`/`TZ`/`LC_ALL`:

```
public/seed             49590fcd9e48601c6326d3a2617be3a3e0a380c0
public/layout-refactor  3ea4a2a7acc2109fa87b3841d0c6eb7afc3c2ba0
overlay/seed            9722a50523a437c77ad0d0df57e39a3e0a83d753
overlay/layout-refactor 3d5dd531c052509cf613d3c4895829e4eec195db
```

Only object SHAs are pinned; packfile bytes are not, because they differ across git versions.

## `reconcile.py --root` is inert without the flag

That file gates every commit in the repo, so the additive `--root` was proved inert three ways: a
21-case A/B (3 tree shapes × 7 argv sets) of the pre- and post-change module with 0 mismatches;
committed tests that the globals are not rebound and that no automated caller passes the flag; and
the whole delta being one `if args.root is not None:` block placed before the first read of either
global. `reconcile.py --check` with no flag: `OK (9 checks clean)`.

## Definition of done — honest status

| DoD item | Status |
|---|---|
| Codex-compatible recorder, ≥95% attribution, active/subprocess/approval/external separated | **Shipped, with a caveat.** The four numbers are separated and the partition invariant is asserted. The "95%" is only a real claim against an externally supplied total (`--external-total-s`), because coverage against the recorder's own span is ~100% by construction. The summary therefore always names `reference_source`. |
| Pinned fixture + baseline, ≥3 current-path runs, median and range per phase | **Partial.** Fixture, harness, and stage protocol (R1–R4) shipped and green. The ≥3-run baseline has not been collected. |
| One read-only command produces the full plan and fails closed | **Done.** 18 fail-closed conditions, all exit 3; 17 have direct tests (`unsafe-path-name` is tested at the parser level — git cannot portably emit such a path in a fixture). |
| Guarded executor with a recovery ref per mutation | **Deferred by decision** — [queue item](../../../message-queue/needs-human/decisions/cutover-executor-deferred-until-telemetry.md), [task](../../0_backlog/2026-08-07-guarded-cutover-executor/task.md). |
| Tests prove no owner-file deletion, no ignored overwrite, no bypassed gate, no failed-as-green | **Done**, and independently attacked — see the defect table. |
| Fast path + closeout policy documented; schema changes matched by reconciler tests | **Partial.** The fast path is documented (`docs/handbook/post-merge-cutover.md`); the closeout-tax policy (solution step 5) was not attempted. |
| ≥3 optimized runs, median non-external time ≥50% below baseline and ≤10 min | **Not met, and not reachable from this scope.** Steps 2–4 touch under ~5 minutes of the 27m33s. Meeting it needs the telemetry to locate the unattributed 8m17s and the step-5 closeout work (7m03s). |
| Final real-session comparison | **Not done** — requires a future real post-merge session, which is what the recorder now exists to measure. |
