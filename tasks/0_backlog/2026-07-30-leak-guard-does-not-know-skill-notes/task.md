# The leak guard and exporter still key on `references_private`, which no longer exists

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: found while repointing the instruction surface for workspace phase 5, 2026-07-30 —
  [the phase-5 record](../../3_in-review/2026-07-28-workspace-phase-5-lifetime-taxonomy/verification.md)
- **Claimed-by**:

## Goal

Teach the two publish-side guards the folder's new name, so the rule they enforce keeps
applying to the thing it was written about.

## Context

Per-skill private notes used to live in `skills/<skill>/references_private/`. The leak
guard fails on any *tracked* file under that name (`automation/publish/check_public.py:136`)
and the exporter prunes it (`export_public.py:147`). Phase 5 renamed the folder to
`skill-notes/` and moved it into the overlay at `private/skills/skill-notes/<skill>/`.

Nothing is leaking today, and the reason is worth being precise about: the notes live under
`private/`, which both tools deny wholesale, so the `references_private` rule is redundant
*for the current layout*. It is not redundant as a rule — it exists to catch the case where
per-skill private notes end up inside the public `skills/` tree, which is exactly the
mistake a contributor or a future refactor might make. Under the new name, that case walks
straight past both guards.

This is the same shape as the hazard the workspace plan names repeatedly: **renaming a
directory that a checker holds in a constant disarms the checker rather than breaking it.**
It is worth noting that this one was found by reading, not by any gate — the link checker's
`--require-roots` covers its own prefix constants, and nothing covers these two.

## Approach

Add `skill-notes` alongside `references_private` in both files rather than replacing it.
The old name should keep failing: a tracked `references_private/` appearing in the public
tree is still a defect, and an append-only deny list is the pattern
`check_public._DENY_TREES` already uses (`test_deny_trees_are_append_only` pins it).

Worth considering while in there: whether either guard should assert that the names it
keys on still correspond to something real, the way `verify_links.py --require-roots` now
does for its prefix constants. That would have surfaced this rename on the first commit
after it, instead of leaving it to be noticed.

## Definition of done

- [ ] Both guards deny `skill-notes` as well as `references_private`
- [ ] A test plants a tracked `skills/<skill>/skill-notes/x.md` and asserts the guard fails
- [ ] The exporter prunes it, with a test
- [ ] `docs/handbook/public-private-split.md` describes the rule by both names
