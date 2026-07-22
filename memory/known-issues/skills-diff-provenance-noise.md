# skills_diff.py queues non-skills from provenance notes and degree phrases

- **Status**: open
- **Severity**: low (queue noise; agents recognized and dismissed it, no wrong categorization)
- **Area**: resume-writer
- **Source**: tailor-stage run B2, 2026-07-21 (`evals/results/stage-tailor-20260721.md`)

## Symptom

On a JD file that begins with a fetch provenance note, `skills_diff.py`'s
extractor queues note vocabulary as uncategorized skills — observed:
`JavaScript-rendered`, `descriptionPlain` (from the fetch_jd provenance
explanation) and `BS/MS/PhD` (degree-requirement phrasing caught by the
slash+capitals heuristic).

## Reproduction

Run `skills_diff.py` on any folder whose `source/JD-*.md` carries the
documented non-verbatim provenance header (reference.md fallback
convention) and a "BS/MS/PhD in ..." education line.

## Impact

Three spurious Step-7 queue entries per affected JD. Subjects so far
recognized them as non-skills and recommended dismissal, so no gate or
profile damage — but the queue is meant to be presentable to the owner
verbatim, and noise erodes that.

## Root cause

The extractor scans the whole file including the provenance header, and the
slash+capitals heuristic has no education-phrase guard.

## Suggested fix

Reuse the provenance-header skip that `fetch_jd.build_digest` now has
(commit b68c909 on `feat/jd-digest`) — skip the header block before
extraction — and drop candidates matching a degree pattern
(`\b(BS|MS|BA|MA|PhD)(/(BS|MS|BA|MA|PhD))+\b` or "in Computer Science"
context). Add both as regression tests next to the existing 9.
