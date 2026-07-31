# job_metadata still has a `_company_key` helper that means something else

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: workspace phase 7 PR-D, 2026-07-30 (assessed and deliberately deferred)
- **Claimed-by**:

## Goal

Remove the last name collision between the owner's persisted company key and an internal
match-normalizer, so no reader can substitute one for the other by accident.

## Context

Phase 7 established that `company_key` is the owner's **filing** key and never a matching
primitive, and enforced it at source level. Part of that work renamed
`automation/shared/mail/reconciliation.py`'s in-memory `company_key` field to `company_match_key`,
because it *is* a match key — it binds email threads to applications — and a future reader who saw
`app["company_key"]` there could reasonably substitute the persisted key and silently change which
emails match which applications.

**The same collision still exists one file away, and now in a worse place.**
`automation/shared/job_metadata.py` has:

- `_company_key()` at ~`:495` — a normalizer that strips seven legal suffixes *anywhere* in the
  string via `\b`, disagreeing with both `registry.comparable_base` (14 suffixes, trailing-only)
  and the mail module's version (no stripping at all);
- a `company_key` local at ~`:749` inside `lookup_company_level`, holding the output of that
  normalizer.

That is the same shape the mail rename just fixed — and it now lives in **the very file that
defines `_validate_company_key`**, the validator for the owner's persisted key. Two things called
`company_key` in one module, meaning different things, one of which the phase's whole invariant is
about.

**Why phase 7 left it.** `lookup_company_level` is an **enrichment** path, not a
skip/dedup/filter/coverage path, so it is deliberately outside the source guard's list — the guard
is scoped to the paths whose failures are silent and expensive. And `job_metadata.py` is vendored
into three skills, so the rename touches four files and must be re-vendored byte-identically.
Neither is a reason not to do it; they are the reason it was not done in a change that was already
carrying a rename, a schema addition and an invariant suite.

**Do this as a pure rename.** `_company_key` → `_company_match_key`, and the local likewise. No
behaviour change, and prove that: the enrichment output must be identical before and after.

While there: the file now hosts two normalizers with different suffix rules. Consider whether a
comment naming the three disagreeing normalizers (this one, `registry.comparable_base`,
`mail/_company_match_key`) is worth more than trying to unify them — unifying them would change
which companies match which level rows, which is a behaviour change and needs its own task.

## Definition of done

- [ ] `job_metadata.py` has no symbol named `company_key` that is not the owner's persisted field
- [ ] Level-lookup output is proved identical before and after on a fixture corpus
- [ ] All three vendored copies re-synced; `sync_vendored.py --check` clean
- [ ] The additive-invariant suite still passes; full gate green
