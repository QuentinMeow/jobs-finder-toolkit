# Remaining adversarial-review findings on the cutover/telemetry tooling

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: Adversarial correctness review of
  [2026-08-07-reduce-agent-development-cycle-latency](../../1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/task.md),
  2026-08-07. A 134-mutation campaign plus manual attack. The CRITICAL and HIGH findings were fixed
  in that task; these are the remainder.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Close the medium-severity findings and the test-coverage gaps the mutation campaign exposed, so the
tooling's stated guarantees are pinned by tests rather than by comment.

## Context

**What was already fixed** (do not re-do): the `phase_summary` partition defect under concurrency;
the per-phase columns having the same defect; `--explain` bypassing every fail-closed condition;
an all-SKIP validation run reporting `ALL GREEN`; the copy-manifest path mismatch that made
`copy-checksum` unrunnable; `--root` combined with `--file-retries` deleting inside the inspected
tree; `--root` reporting "OK (9 checks clean)" for a tree with no process roots; `--root` leaking
into later in-process calls; `check_skill_manifests` importing from the inspected tree; signal exit
codes; the 72 MB plan JSON; and the bench's decorative destination-guard step.

**Mutation survival at the time of review** — the shape of the remaining risk:

| Module | mutations | survived |
|---|---:|---:|
| `plan_cutover.py` + `classify_dirty.py` | 28 | 4 |
| `phase_summary.py` + `phase_recorder.py` | 45 | 2 |
| `verify_copy.py` | 6 | 3 |
| `reconciliation_fixture.py` | 8 | 5 |
| `reconciliation_bench.py` | 14 | 12 |

The planner and recorder are well tested. The fixture and bench are not, and `verify_copy` — the
module that touches owner data — was thin (two of its three guards have since been pinned).

## Findings to close

**Correctness / contract**

- `reconciliation_bench.py` never calls `FIX.verify()` after `FIX.build()`, while every recorded row
  is stamped *"(pinned commit SHAs)"*. With `PINNED_SHAS` corrupted, `build` still exits 0. Call
  `verify()` in `run_stage` and raise on findings.
- `reconciliation_fixture.py` `verify()` asserts only `.is_file()` for the three uncommitted paths,
  so the dirty patch — the actual subject of the benchmark — can be rewritten to different bytes and
  still verify clean. Pin `git hash-object` for those three.
- `classify_dirty.py`: a similarity rename (git's default 50% threshold) sets `merged_path`, but
  `plan_cutover.py`, `classify_dirty.py`'s own comments, and `docs/handbook/post-merge-cutover.md`
  all say destinations come only from proof-grade evidence and never mention similarity. Either drop
  the grade or correct all four texts and add the score to the escalation rules.
- `phase_summary.py`: `KNOWN_FIXTURES` is a closed set with no `else`, so `recon-v2` becomes
  `fixture: null` — which reads as "no fixture", not "unknown fixture". Import `FIXTURE_VERSION`
  from the generator; add an `integrity["unknown_fixture"]` counter; give `--fixture` a `choices=`.
- `phase_summary.py`: a log whose `session_end` precedes `session_start` clamps to a zero span and
  reports every class as `0.0` with a clean integrity block. Flag the inversion.
- `phase_summary.py`: a backwards `mono` step is zeroed but the accumulator keeps climbing, so a
  500 s session can report 800 s with `missing_seq` still 0. Add a `non_monotonic_events` counter.
- `phase_summary.py`: `--unredacted` writes raw free text to any path outside the repo, while its
  own `--help` and `docs/handbook/metrics.md` promise it refuses anything not under `logs/` or
  `local/`. Fix the check or correct both texts.
- `phase_summary.py`: `--min-coverage` gates on `phase_coverage_pct`, the number the module's own
  docstring says proves nothing — a session that is 100% `long_gap` passes `--min-coverage 100`.
  Add `--min-attribution`.
- `classify_dirty.py`: `_looks_binary(None)` returns True, so an ordinary new untracked text file
  absent at the fork point reports `not-attempted:binary`, which the handbook makes an escalation
  trigger. Give "absent at fork point" its own residual value.
- `classify_dirty.py`: the link-rebase normalizer rewrites every literal `<old_dir>/` occurrence
  including prose, fenced shell commands, and JSON values, while the code comment and the handbook
  both claim only link-shaped targets are touched. Restrict the substitution or reword the claim —
  "residual EMPTY (proven path-only)" currently also covers changes to path strings that are
  configuration.
- `reconcile.py`: `--root` tracebacks exit 1, indistinguishable from "found findings", and the bench
  asserts `expect=1` — so a crash satisfies the benchmark's entry condition. Catch and exit 2.
- `reconcile.py`: `check_company_index` under `--root` reads the index from the root but the
  applications from the real `config.applications_root()`, printing the owner's real private
  application folder names into output the bench captures. Derive both from the root.
- `reconciliation_bench.py`: R4's boundary is satisfied by a reconciler that silently skipped 3 of
  its 9 checks (the fixture has no `skills/`, `private/market/`, or `companies.yaml` and the bench
  never passes `--require-roots`). Pass it, or assert the check count.
- `reconciliation_fixture.py`: `--force` `shutil.rmtree`s any directory whose `fixture.json` merely
  parses, and the bench always passes `force=True`. Require the manifest's `generator` to match.
- `reconciliation_fixture.py`: `core.fileMode` is absent from the pinned git config, and
  `Path.write_text` uses `newline=None` (CRLF under native Windows git) — both change every commit
  SHA. Add `-c core.fileMode=false` and use `write_bytes`.
- `reconciliation_fixture.py`: the destination guard mixes lexical `os.path.abspath` with physical
  `.resolve()`, so a symlinked path walks through containment. Resolve both sides.
- `reconciliation_fixture.py`: `verify()`'s git calls inherit the operator's environment unlike
  `_Git.run`, so an exported `GIT_DIR` makes a passing build fail all four pins. Route through
  `_Git.run`.

**Test-coverage gaps (shipped code correct, guard unverified)**

- `check_configured_paths.report()` is never driven through an UNCLASSIFIED or STALE row, so both
  `failures.append` calls can be deleted with the suite green.
- `run_gates.py`'s `tests-cutover` gate has `group="ci"` but no test pins it, so a one-word edit
  moves a 40-second suite into the pre-commit chain — the exact regression the parent task exists to
  prevent.
- `reconciliation_bench.py` stages R1, R2 and R4 are never executed by any test; only `--list-stages`
  and the unknown-stage path are covered. `--stage`, `--runs`, `--variant`, `--json`, `--out`, the
  `FixtureError` handler, and the exit code are untested.
- `reconciliation_fixture.py`'s `_structural_findings` and the FIXTURE_VERSION drift check are never
  exercised as findings, so the docstring's "editing the recipe without bumping `FIXTURE_VERSION`
  turns tests-evals red" is unproven.
- `validate_cutover.py`: `--only X --skip X` selecting nothing is untested (the shipped `return 1` is
  correct).
- `reconciliation_bench.py`: `median` → `min` survives, because the only assertions are
  `min <= median <= max` — tautological.
- Several `assertRaises(FixtureError)` calls check no message and pass for the wrong reason —
  `test_reconciliation_fixture.py:257`, `test_classify_dirty.py:408-476`, `test_verify_copy.py:251`.
- `classify_dirty.py`'s "partially-moved directory" test passes via the ambiguity dedupe rather than
  the consistency filter it names; a discriminating fixture separates them.
- `classify_dirty.py`: dropping the `evidence == "R100"` requirement from
  `renamed-by-merged-layout`, and dropping the `tracked` requirement from `unchanged`, both survive.
  Each flips a verdict toward "mechanical" on non-proof evidence.

## Definition of done

- [ ] Each correctness finding above is fixed or explicitly rejected in this file with a reason.
- [ ] Each coverage gap has a test that FAILS against the mutation described.
- [ ] `run_gates.py --lane maintenance` and `--lane policy` both exit 0.
- [ ] No claim in `docs/handbook/post-merge-cutover.md` or `docs/handbook/metrics.md` describes
  behaviour the code does not have.
