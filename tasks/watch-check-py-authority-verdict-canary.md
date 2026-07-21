# Watch the `rw-layout-budget-verdict` check.py-authority statement for one more gate cycle

- **Status**: todo
- **Priority**: P2
- **Area**: resume-writer
- **Source**: `evals/results/stage3-combined-regate-8d4c06c-20260720.md:38-40`;
  also failed in `evals/results/stage2-canary-gate-19c3ff8-20260720.md:19` and
  `evals/results/stage3-canary-gate-446a954-20260720.md:19`

## Goal

Confirm, over one more independent gate cycle, that the `rw-layout-budget-verdict`
canary's "check.py's post-render page count is the authoritative gate" statement
reliably survives now that it's been restructured into the verdict definition,
rather than being a trailing bullet an agent can drop.

## Context

The `rw-layout-budget-verdict` canary requires the agent's user-facing verdict to
explicitly state that `check.py`'s post-render page count — not the pre-render
`estimate_layout.py` prediction — is the authoritative pass/fail gate. This
statement was a recurring flake: it failed as a trailing bullet in 2 of 4 prior
gate samples (`stage2-canary-gate-19c3ff8:19`, `stage3-canary-gate-446a954:19`,
plus one FAIL recorded directly in the combined-regate source). At commit
`8d4c06c`, the fix folded the authority statement into part (2) of a two-part
verdict definition (rather than leaving it as an easy-to-drop trailing bullet),
and the very next run bound on the first sample: PASS.

One passing re-run after a structural fix is not enough to call this closed — the
same statement flaked in roughly half of prior samples before the fix, so it
warrants one more independent gate cycle's confirmation before treating it as
durably fixed.

Relevant files:
- `.agents/skills/resume-writer/SKILL.md` (or wherever the Step 5.5 verdict
  protocol / two-part verdict definition lives — the `8d4c06c` restructure)
- `evals/resume-writer/canaries.yaml` (`rw-layout-budget-verdict` canary
  definition)

## Definition of done

- The next independent gate run (any future `evals/results/*.md` record that
  includes the `resume-writer` suite) reports `rw-layout-budget-verdict` PASS
  with the check.py-authority statement present, without needing a re-run.
- If it flakes again, the finding is recorded as a still-open known issue rather
  than assumed fixed.
