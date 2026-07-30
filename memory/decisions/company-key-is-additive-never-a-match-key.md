# The company key files and navigates; it never matches

- **Status**: decided
- **Date**: 2026-07-30
- **Decided by**: agent (within standing policy)

## Context

Workspace phase 7 gives every employer one owner-owned key in `companies/_index.yaml`, and lets an
application's `meta.yaml` carry `company_key`. The open question was how far that key is allowed to
travel: it is the first identity primitive in this repo that spans both trees, and there are at
least six places that already compare company strings — the skip-log readers, the recently-searched
check, the coverage builders, the level-lookup enrichment, the email-to-application binding, and
the tracker's company-view grouping. Each of those re-derives identity from free text with its own
normalizer, and every one of them looks like an obvious candidate for "just use the key".

Two facts decide it.

**The key is the least-verified data in the repo.** The public resolver resolves 119 of the 214
distinct company strings the applications carry. The other 95 are not spelling drift — roughly 85%
of them are employers structurally absent from a registry that only holds companies with a
supported ATS token. So ~44% of key assignments are a human judgement made in a single review
pass, with no independent source to check them against.

**The blast radius is asymmetric.** On a filing path a wrong key costs a mislabelled report, and
the owner sees it. On a match path a wrong key is silent: an alias *split* re-drafts an application
to an employer that already declined, and an alias *merge* suppresses a genuinely new posting. The
design README had already stated this for the skip check specifically — it is deliberately
URL-first and key-independent, and sharding it by key "would turn every alias split into a
re-drafted application".

Phase 6 met the same shape one layer down and nearly shipped the bug: using the skip-log's internal
dedup identity as a *reader's* match key would have silently dropped the `(company, role)` skip for
367 of 369 rows, and the existing test suite could not have caught it.

## Decision

**`company_key` is additive. It never enters a comparison that decides whether a posting is
skipped, deduplicated, filtered, or counted as covered.** Those paths keep reading the free-text
`company` string and the posting URL exactly as they did before the key existed.

The key exists for filing (`companies/<key>/`), navigation, and validation by the reconciler.

The invariant is enforced at **source level** — a test asserts the literal `company_key` does not
appear in the source of the named match-path functions — rather than behaviourally, so violating it
requires deleting a named guard rather than merely writing plausible code.

Two consequences follow immediately:

- The reconciler verifies `meta.yaml → index` only, never the reverse. A key with zero applications
  is legitimate (14 exist today: researched, or interviewed with, but never applied to), and
  checking the reverse direction would turn the reconciler red the moment the owner deletes an
  application folder — the exact fragility phase 6 removed.
- `mail/reconciliation.py` already emitted an in-memory field literally named `company_key` that
  **is** a match key, binding email threads to applications. It was renamed `company_match_key`
  so a future reader cannot substitute the persisted owner key by accident.

## Alternatives considered

- **Key as the universal match primitive, replacing the six normalizers.** Genuinely tempting: it
  would fix the "two folders, same employer, different spelling" split by construction and collapse
  six disagreeing normalizers into one. Lost because it puts 44%-hand-judged data on the paths
  whose failures are silent and expensive, and because the six normalizers disagreeing is a much
  cheaper problem than a suppressed posting.
- **Key on match paths, but only where it resolves; free text otherwise.** Lost because a rule that
  applies to 56% of strings and not the other 44% produces behaviour nobody can predict from
  reading the code, and the fallback boundary moves whenever the index changes.
- **Behavioural enforcement only** (a test that skip sets are identical with and without the key).
  Kept, but not alone: it proves today's code is clean and says nothing about the next reader who
  adds a comparison. The source-level assertion is what makes the invariant survive contact with a
  future agent.

## Consequences

- Any future work wanting key-based matching must revisit this file first, and must bring evidence
  that key assignment has become verifiable — not merely that it looks correct.
- The tracker's company-view grouping (`status.py`, currently a `casefold()` of the free-text
  string) stays as it is for now. It is a *display* grouping, so it is the one borderline case that
  could adopt the key without touching a skip decision; deliberately deferred rather than decided
  here, so that it is a separate, arguable change.
- Revisit if key assignment ever gains an independent check — for example if the public registry
  stops being polling-only and can carry identity-only rows for employers with custom career sites,
  which would let the private index be cross-checked against something rather than trusted.
