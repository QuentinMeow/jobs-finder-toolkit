# Add a schema-v3-rejection negative fixture to `at-validate-drafted-metadata`

- **Priority**: P2
- **Area**: tracker
- **Source**: `evals/results/application-tracker-389dfee-20260720-schema-v4-status-rollup.md:19`

## Goal

Give the `at-validate-drafted-metadata` canary a negative-case fixture — a
`meta.yaml` still on the legacy schema v3 shape (or carrying the retired
`total_compensation_range` key) — so the canary actually exercises the rejection
path it claims to cover, not just the all-valid-v4 happy path.

## Context

`at-validate-drafted-metadata` (`evals/application-tracker/canaries.yaml`)
already lists rejecting "a legacy v3 file or a `total_compensation_range` key" as
an expected behavior and a failure mode, but its `setup:` only points at the
shipped, already-valid v4 example
(`examples/applications/6_drafted/example-corp-senior-software-engineer/`). The
v4 status-rollup gate record noted this directly: "Narrowed with `--statuses
drafted` knowing the default is all folders; negative (v3-rejection) case not
exercised by fixture." Checked directly against the canary file as it stands
today — confirmed still true: no v3/legacy fixture exists anywhere under
`examples/applications/`, so `status.py --check-metadata`'s v3-rejection branch
(exercised in `.agents/skills/application-tracker/scripts/status.py`) has no
canary-level coverage of an agent actually encountering and correctly reporting
a rejected file.

Relevant files:
- `evals/application-tracker/canaries.yaml` (`at-validate-drafted-metadata`'s
  `setup:` field to extend, or a new canary id)
- `.agents/skills/application-tracker/scripts/status.py` (`check_metadata()`,
  where the v3/legacy-key rejection logic lives)
- `examples/applications/` (where a new negative fixture folder would live —
  a synthetic, non-real company/application, per the examples directory's
  existing leak-guard-safe convention)

## Definition of done

- A new fixture folder under `examples/applications/` (or a scoped canary setup
  step) ships a `meta.yaml` on schema v3 (or with a `total_compensation_range`
  key), alongside the existing valid v4 example.
- `at-validate-drafted-metadata`'s `setup:`/`expected_behavior` is updated so a
  run against the extended fixture set must report the legacy file as invalid,
  not just confirm the valid ones.
- Verification:
  ```bash
  .venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-metadata
  # must report the new legacy fixture as INVALID, alongside the existing valid rows
  ```
