# Seven applications fail meta.yaml validation

- **Priority**: P2 (someday)
- **Area**: tracker
- **Source**: Observed 2026-08-07 while building the `cutover` validation profile — the profile's
  `app-metadata` gate was red before that work started and is unrelated to it.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Every application's `meta.yaml` validates against schema v6, so
`status.py --check-metadata` is green and the `cutover` validation profile's `app-metadata` gate
reports a real result instead of a pre-existing failure.

## Context

`status.py --check-metadata` reports **7 of 274 applications invalid**. This is a red gate OUTSIDE
the scope of the task that found it (`2026-08-07-reduce-agent-development-cycle-latency`, which
added `automation/cutover/validate_cutover.py`). Recorded per the AGENTS.md red-gate rule: the
finding cannot change that task's result, because the cutover profile only *invokes* the existing
checker and asserts its exit code survives parallel execution — a red `app-metadata` exercises the
failure path correctly, and the profile's own tests use synthetic gates rather than real
applications.

Reproduce:

```bash
.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
```

Requires judgement rather than a mechanical repair — the fix depends on WHY each row is invalid
(a schema-v6 field added after those applications were drafted, a hand edit, or a real data
problem), and **agents never delete or rewrite owner application data without asking**. Expect to
propose the per-application change and let the owner decide, or use
`status.py --enrich-metadata <folder>` where the gap is a derivable field.

## Definition of done

- [ ] `.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata` exits 0.
- [ ] Each of the 7 applications is accounted for: repaired, or the owner explicitly decided to
  leave it and the checker was taught the legitimate shape.
- [ ] No application folder was deleted and no owner-authored field was overwritten without asking.
