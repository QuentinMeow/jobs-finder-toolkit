# status.py --check-metadata: rejection of a path argument needs a usage hint

- **Status**: todo
- **Priority**: P2
- **Area**: tracker
- **Source**: three independent subject-agent runs, 2026-07-21
  (`evals/results/stage-tailor-20260721.md`,
  `evals/results/confirmation-round-20260721.md`)

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
