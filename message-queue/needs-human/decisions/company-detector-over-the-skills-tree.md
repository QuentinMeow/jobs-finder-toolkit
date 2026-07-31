# Should the review gate's company detector also read `skills/**`, not just the diff?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [company-research LESSONS.md](../../../skills/company-research/LESSONS.md)
- **Blocking**: nothing — the one live instance is already redacted
- **Default path**: leave the detector diff-only. Editors are told the rule in the
  redacted section itself, and the sweep below is re-runnable by hand.

## Background

**What was redacted, and why you are hearing about it.** One bullet in
`skills/company-research/LESSONS.md` cited two real companies by name as examples of
engineering blogs worth reading in full. One of the two is in the public ATS registry
(`skills/job-search/companies.yaml`), which publishes company identity by design. The
other is not in the registry anywhere in the public tree, and it has a research folder
in your private overlay — so the public repo was saying, to anyone who reads it, that
you are researching that company. The line carried no date, no posting, no application
and no identity token; it was a neutral citation. It has been in the public tree since
2026-07-18 and is byte-identical on `main`, so it has been shipping for two weeks.

Both armed gates accepted it, correctly, because **a company name is not an identity
token**: `check_public.py` derives its tokens from your identity and finds nothing to
match, and the review gate's company detector never looked, for the reason below.

The bullet is now rewritten to teach the same lesson by SHAPE — what a usable exemplar
post contains — plus an explicit rule that companies are named in the per-company
research folders and never in public skill text.

**The sweep.** I checked `SKILL.md` and `LESSONS.md` across all 11 public skills
against 310 registry display names and your 25 overlay company folders (dropping 13
registry names that are also ordinary English or technical words, each hit checked by
eye). Before the redaction: **26 lines named a real company; exactly 1 named a company
absent from the public registry** — the one above. After: 24 lines, none outside the
registry. So this is a single instance, not a pattern; the public skills otherwise name
only companies the registry already publishes.

**Why the detector missed it.** `review_gate.company_hints()` is narrowed on four axes,
all deliberate: it runs on the **diff** `a..b`, subtracts every name already present in
the public tree at `a`, matches full display names, and skips `examples/` and the ATS
registry. A name added two weeks ago and never touched since is invisible on all four
counts. That is not a bug — it is what keeps the hint list short enough to read — but it
means the detector can only ever catch a company on the commit that introduces it. Miss
it once and it is permanent.

## Options

### Option A — leave the detector diff-only (default path)
No code change. The rule now lives in the redacted section, where the next editor of
that file meets it, and the sweep above can be re-run on demand.
*Pros:* zero cost, zero new noise, no new gate on every commit. *Cons:* the same class
of line can land again in a skill nobody edits for months, and nothing mechanical will
ever notice; today's clean sweep is a snapshot, not an invariant.

### Option B — add a whole-tree `--scan-skills` mode, advisory, run on demand
Same detector, whole-tree instead of diff-scoped, restricted to `skills/*/SKILL.md` and
`skills/*/LESSONS.md`, subtracting every name in `skills/job-search/companies.yaml`.
The sweep above IS that scan, run by hand from a throwaway script: it reports
**0 findings** against today's tree and exactly **1** against the pre-redaction tree —
the real signal, no noise. Shipping it means turning that script into a mode of the
gate. It would be wired into no gate; run it when a skill's instruction files change,
or from the gardener's weekly sweep.
*Pros:* mechanical, and the measured false-positive rate is zero. *Cons:* it stays
green only while the registry stays a superset of what the skills mention; a company you
research but never register would be flagged even in a legitimate mention, and someone
has to actually run it.

### Option C — wire Option B into pre-commit and CI as a hard gate
Same scan, blocking.
*Pros:* cannot be forgotten. *Cons:* it reads your PRIVATE company index, so it only
works on your machine — in CI, `company_display_names()` returns "NOT INSPECTED" and the
gate has nothing to enforce. A gate that is armed on exactly one machine is the shape the
leak guard's own `--allow-unarmed` handling exists to avoid, and it would block commits
on a judgment call ("is this mention legitimate?") that no code can make.

## Recommendation

**Option B.** The measurement is what decides it: whole-tree over the two instruction
files, minus the public registry, produced exactly one finding — the real one — and zero
noise. That is a detector worth having. It should stay advisory and out of the commit
path, because the private index makes it unarmable in CI and the judgment it informs
("this company is legitimately public / this one is not") belongs to a human. If you
would rather not carry more tooling for a one-instance problem, Option A is defensible
and costs nothing.

**Your answer:** ______
