# Worklog — 2026-07-31-field-fidelity-unconfigured-store

## 2026-08-02 — session 1 (agent)

- Reproduced first, under the shipped example config, before touching anything:
  `check --key anything` died with a `TypeError` seven frames deep in `pathlib`,
  exit 1. Same for `corpus` and `todo`. `sample` did **not** — it never reads
  `config.data_root()` at all, and already refused cleanly with "run `corpus`
  first", so it needed no guard and gating it would have claimed a dependency it
  does not have. That is the one deviation from the task's definition of done,
  and it is recorded in `verification.md`.
- Checked the sibling store tools before inventing a message, as the task asked:
  `automation/store/{store_show,gc_store,validate_store}.py` and
  `skills/job-search/scripts/{query_postings,build_postings}.py` all print
  "store not configured (set paths.data_root or JOBHUNT_DATA_ROOT)". Reused the
  wording; **did not** reuse their exit 0. Those tools have nothing to do when the
  store is absent, while an audit that was asked for a verdict and cannot read the
  store has not passed — exit 0 there is a green gate over an audit that never
  ran. The refusal exits 2.
- One guard in `main()` before dispatch, keyed off a `needs_store=True` default
  that each store-reading subparser declares beside its `func`. A per-command
  guard would have been three copies of the same check and a fourth thing to
  forget when a command is added.
- Surprise: the guard broke `OutputContainmentTests`. It calls `main()` and
  expects the `--out` containment refusal, which is now unreachable for
  `corpus`/`todo` when no store is configured — and no store IS configured in a
  worktree without a `config.yaml`. The test was silently asserting different
  things on a maintainer machine and in CI; it now pins `JOBHUNT_DATA_ROOT` at a
  throwaway path so it asserts the same thing in both.
