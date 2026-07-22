# memory/known-issues/

One file per bug. Each file is **self-contained**: symptom, reproduction,
impact, and current best understanding all live in the file — a reader should
not need the original session or result file to act on it.

## Rules

- Filename: `<kebab-slug>.md`.
- **Public tree ⇒ leak-guard rules apply**: no real names, employers,
  applied-to companies, or dated personal facts. A bug only reproducible with
  the owner's real data goes in `private/memory/known-issues/` (same format) with a
  sanitized public stub only if the code defect itself is public.
- Relationship to GitHub issues: the file is the canonical detailed record;
  if a GH issue exists, link it under **Source** and mirror status both ways.
- When fixed, set `Status: fixed` + note the fixing commit/PR, keep the file
  for one PR cycle, then delete it in a later PR (git history is the archive).

## File format

```markdown
# <Title>

- **Status**: open | fixed | wontfix
- **Severity**: high (wrong output / data loss) | medium (wasted cost or
  manual workaround) | low (cosmetic)
- **Area**: job-search | resume-writer | tracker | harness | benchmarks | repo
- **Source**: first-seen evidence (result file, GH issue #, session date)

## Symptom
What goes wrong, observably.

## Reproduction
Exact command(s) / inputs that show it. If not deterministic, the conditions.

## Impact
Who/what it costs (tokens, time, correctness) and how often.

## Root cause
If known; otherwise current best hypothesis, marked as such.

## Suggested fix
Concrete enough that an agent could implement from this file alone.
```
