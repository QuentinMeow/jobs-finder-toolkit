# Worklog — 2026-08-01-routed-design-and-eval-docs-describe-a-repo-that-does-not-exist

## 2026-08-02 — session 1 (agent)

- All seven items re-verified before editing; all seven were true. Details and the numbers I
  re-derived are in `verification.md`.
- **Design families are records** (`docs/designs/AGENTS.md`: "Historical families are records
  — never rewrite their conclusions"), so each superseded claim is struck and dated in place
  with the current fact beside it — the same treatment `execution-plan.md` already gives its
  own false claims — rather than deleted.
  1. `workspace-restructure/README.md`: "Not implemented" struck; the status now points at
     the execution plan and `current-state.md` as the status board and names `review_gate.py`
     as the shipped Layer 2. "10 public skills" → 11, with `github-workflow/` added to the
     tree (it was the missing one).
  2. `tree-instructions/README.md`: the status line and §5 both said the validator was
     queued and §5 pointed at a task folder in no status directory. Both now say **dropped**,
     with the ADR and the roadmap line that dropped it, and the spec is explicitly kept as a
     design record rather than as work.
  3. `review-gate.md`: the "no ancestor row" bullet described one outcome; the shipped gate
     has six, two of which exit 0. Added the outcome table and named `--staged`,
     `--verify-all` and `--head`, including in the "Where it runs" table.
- Item 4 ended in **"delete the requirement"**, which the task explicitly allows. There is no
  transcript miner in `automation/` and building one was not in scope; the requirement is
  struck from `stage-benchmarks.md` and `evals/results/TEMPLATE.md`, with the intent kept as
  a reviewer judgement and an explicit "re-open this only by building the miner".
- Item 5: three surfaces now say the metrics hooks are opt-in and link
  `docs/handbook/metrics.md`. `ab-protocol.md` additionally says to wire them BEFORE the A
  runs, because an A/B whose A half has no numbers is not a matched pair.
- Item 6: one artifact path everywhere (`private/evals/runs/artifacts/<row-id>/`, inside the
  overlay's sanctioned `evals/{canaries,fixtures,runs}/`), and `protocol.md` replaced with
  `docs/designs/token-usage-modes/benchmark-scenario.md`.
- Item 7: re-measured the size table myself rather than trusting the task's figures (the tree
  had moved again since it was filed). Relabelled it as a measurement at a named commit, kept
  the old claim in a `was claimed` column, and split the overlay rows out as unverifiable
  from the public tree.
- Also corrected one stale path found while working: `docs/roadmap/desired-state.md` pointed
  at `tasks/0_backlog/2026-07-31-leak-guard-silently-skips-an-unreadable-file`, which is in
  `4_done/`.
