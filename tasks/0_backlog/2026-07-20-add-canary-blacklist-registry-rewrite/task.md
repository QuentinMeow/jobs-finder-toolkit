# Add a canary that exercises the merged-registry blacklist rewrite against a real blacklisted company

- **Priority**: P2
- **Area**: resume-writer
- **Source**: `evals/results/instruction-clarity-gate-32fb3ef-20260720.md:66`

## Goal

Add a resume-writer canary that drives an actual blacklisted-company scenario
through the pre-flight check, so the merged-registry blacklist rewrite
(`registry.is_blacklisted`) has real behavioral coverage instead of being
adjacent-only to `rw-duplicate-preflight`.

## Context

The `fix/instruction-clarity-adversarial-20260720` diff (landed at commit
`32fb3ef`) reworded the pre-flight blacklist bullet in
`.agents/skills/resume-writer/SKILL.md` to route through the merged registry's
`registry.is_blacklisted()` (confirmed present today in
`.agents/skills/job-search/scripts/registry.py`). The gate record's diff-coverage
map explicitly lists this change as `UNGATED (no canary drives a blacklisted
company)` — `rw-duplicate-preflight` covers the adjacent already-drafted-folder
stop, but no canary actually supplies a company that
`registry.is_blacklisted()` would flag. Checked directly against
`evals/resume-writer/canaries.yaml` as it stands today: no canary id or setup
references a blacklisted company or `companies.yaml`'s blacklist entries; this
gap is still open.

Relevant files:
- `evals/resume-writer/canaries.yaml` (where the new canary belongs, alongside
  `rw-duplicate-preflight`)
- `.agents/skills/job-search/scripts/registry.py` (`is_blacklisted()`, the
  behavior to exercise)
- `.agents/skills/resume-writer/SKILL.md` (the pre-flight blacklist-check bullet
  that should route through the registry)
- `examples/` (wherever a safe-to-ship example blacklist entry could live, so the
  canary doesn't need a real, personally-identifying blacklisted company —
  leak-guard applies to the fixture too)

## Definition of done

- A new canary in `evals/resume-writer/canaries.yaml` (e.g.
  `rw-blacklist-preflight`) prompts a tailoring request against a company that a
  fixture-level `companies.yaml`/registry entry marks blacklisted, and asserts the
  agent stops before creating anything, citing the blacklist.
- The canary passes under a live run and is added to the diff-coverage
  expectations the next time the resume-writer suite is gated.
