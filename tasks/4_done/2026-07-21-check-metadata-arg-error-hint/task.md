# status.py --check-metadata: rejection of a path argument needs a usage hint

- **Priority**: P2
- **Area**: tracker
- **Source**: three independent subject-agent runs, 2026-07-21
  (`evals/results/stage-tailor-20260721.md`,
  `evals/results/confirmation-round-20260721.md`)
- **Claimed-by**: agent (fix/10-company-research-correctness, 2026-07-31)

## Goal

Stop the most common agent stumble observed in this round's measured runs:
`status.py --check-metadata <folder-path>` exits 2 with a bare
"unrecognized arguments", and agents burn a retry discovering the flag scans
the whole pipeline and takes no path.

## Context

Three separate measured subjects made the identical slip and each needed one
adaptive retry. The fix is an error-message affordance, not a behavior
change: when extra positional args accompany `--check-metadata` (or other
no-arg scan flags), print one line — "`--check-metadata` scans every
application under the active config's applications root and takes no path;
to target one application pass its slug to `--enrich-metadata <slug>`" —
then exit 2 as today. Alternatively (bigger, optional): accept an optional
slug to scope the scan.

## Definition of done

- The misuse form prints the hint; correct forms unchanged (tracker suite
  green, one new test for the hint path).
- Next measured round shows zero retries on this stumble.

## Source check (2026-07-31, during implementation)

The two cited eval records were re-read before implementing. Only one of them
supports the claim, and it supports a weaker version of it:

- `evals/results/confirmation-round-20260721.md` line 67-71 records "4 single-shot
  adaptive retries in D1 (arg-form/interpreter fixes, each resolved on first
  correction) + 1 in D2 (same `--check-metadata` arg-form slip — a recurring stumble
  worth a usage-line fix in the script's error message)". That establishes **two**
  measured runs hitting it, not three, and D1's four retries are a mix of arg-form
  and interpreter fixes rather than four instances of this one slip.
- `evals/results/stage-tailor-20260721.md` does **not** mention `--check-metadata`,
  an arg-form slip, or any retry. It does not support the claim at all.

The defect and the requested fix are both real and unchanged — the misuse form did
exit 2 with a bare "unrecognized arguments" and no hint, reproduced before the fix —
so the task is implemented as written. Only the "three independent runs" count is
overstated by its own sources.
