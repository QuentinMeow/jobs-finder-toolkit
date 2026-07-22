# Canary fixture conflict: `rw-tailor-single-posting` is unsatisfiable against the shipped complete example folder

- **Status**: open
- **Severity**: medium (wasted cost or manual workaround)
- **Area**: benchmarks
- **Source**: GH issue #16; worked around under the "issue #16 protocol" in
  `evals/results/stage2-canary-gate-19c3ff8-20260720.md`,
  `evals/results/stage3-canary-gate-446a954-20260720.md`,
  `evals/results/stage3-combined-regate-8d4c06c-20260720.md`, and
  `evals/results/instruction-clarity-gate-32fb3ef-20260720.md`

## Symptom

The `rw-tailor-single-posting` canary (`evals/resume-writer/canaries.yaml`) expects
a *fresh* tailoring run: it should start `tailored.yaml` from the baseline, produce
all default deliverables, and end with the Step 7 skill-categorization queue. But
the shipped fixture folder,
`examples/applications/6_drafted/example-corp-senior-software-engineer/`, already
contains a complete application (`meta.yaml`, `source/tailored.yaml`, rendered
resume DOCX/PDF, cover letter PDF, and the bundled `..._Application_<job
title>.txt`). A skill-faithful agent hits the resume-writer's pre-flight
duplicate-detection rule against this folder and stops (per
`rw-duplicate-preflight`'s own contract: "stop — point the user at that folder...
offer to refresh") instead of exercising any of `rw-tailor-single-posting`'s
fresh-tailoring bullets. The two canaries end up testing the same stop behavior,
and the fresh-tailoring path stays unexercised.

## Reproduction

```bash
cat evals/resume-writer/canaries.yaml   # see the rw-tailor-single-posting entry (id, prompt, setup, expected_behavior)
ls examples/applications/6_drafted/example-corp-senior-software-engineer/
# -> already has source/tailored.yaml (baseline-derived), rendered resume PDF,
#    cover letter PDF, and the bundled Application_<job title>.txt
```

Run the canary's prompt against an agent with only the `setup:` field's "Default
setup. Uses the shipped example JD." applied (no fixture stripping) — the agent
finds the folder already complete and stops at the duplicate-preflight check
instead of producing a fresh application.

## Impact

Every gate run that includes this canary needs a manual, undocumented workaround
(strip the fixture down to `meta.yaml` + `source/JD-*.md` before running, or
substitute a second fixture) to get a valid, scoreable run. Without the
workaround the run is either invalid (agent correctly stops, but no
fresh-tailoring bullets are exercised) or double-counts `rw-duplicate-preflight`'s
coverage. This has recurred across at least four separate gate records.

## Root cause

The canary's `setup:` field ("Default setup. Uses the shipped example JD...") does
not account for the fixture folder shipping a fully-completed application rather
than a JD-only scaffold. `rw-duplicate-preflight` legitimately owns the
already-complete-folder case, but `rw-tailor-single-posting` was authored assuming
a fresh scaffold and was never given its own setup step to guarantee one.

## Suggested fix

Give `rw-tailor-single-posting` an explicit setup step in
`evals/resume-writer/canaries.yaml`: before each run, strip the fixture folder to
just `meta.yaml` + `source/JD-*.md` (mirroring the `handoff.py` scaffold state), or
point the canary at a second, JD-only fixture folder instead of the shipped
complete example. Either way, keep `rw-duplicate-preflight` as the sole owner of
the already-complete-folder stop behavior so the two canaries stop overlapping.
