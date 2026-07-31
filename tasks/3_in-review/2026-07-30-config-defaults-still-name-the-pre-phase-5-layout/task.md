# Four config defaults still derive the pre-phase-5 layout, and only the live config hides it

- **Priority**: P2 (someday) — but it must land **with** phase 8, not after it
- **Area**: repo
- **Source**: found while repointing the instruction surface for workspace phase 5, 2026-07-30 —
  [the phase-5 record](../../3_in-review/2026-07-28-workspace-phase-5-lifetime-taxonomy/verification.md)
- **Claimed-by**: agent, 2026-07-31 (branch `fix/03-owner-data-paths`; work complete, in review)

## Goal

Make the four accessors whose *defaults* still describe the retired tree agree with the
layout the documentation now asserts — without breaking the example checkout.

## Context

Phase 5 moved the private tree and updated every document that names it. Four accessor
defaults in `automation/shared/config.py` (and its four vendored copies) were left alone:

| accessor | default derivation | where the file actually is |
|---|---|---|
| `blacklist_path()` | `overlay_root()/job-search/blacklist.yaml` | `market/blacklist.yaml` |
| `story_bank_path()` | `overlay_root()/interviews/behavioral/story-bank` | `me/interviews/story-bank` |
| `search_profiles_dir()` | `overlay_root()/job-search-profiles` | `market/searches` |
| `skill_references_dir()` | `overlay_root()/skills/references_private` | `skills/skill-notes` |

The live `config.yaml` sets all four explicitly, so nothing is broken today. **That is
precisely the problem**: the code and the docs now disagree, and the only thing holding
the disagreement harmless is a git-ignored file that no test, no CI run and no fresh
clone has. `config.story_bank_path()` under the example config resolves to
`examples/interviews/behavioral/story-bank` — a directory that does not exist and, after
phase 8, never will. Every one of these four fails soft: `story_bank_path()`'s callers
"degrade gracefully", `blacklist_path()` prints a notice, `search_profiles_dir()` resolves
to nothing at all.

**Why this was not fixed in phase 5.** The defaults are relative to `overlay_root()`, and
under the example config that is the `examples/` tree — whose shape phase 8 reshapes. Point
`story_bank_dir`'s default at `me/interviews/story-bank` today and it resolves to
`examples/me/interviews/story-bank`, which does not exist either. The default cannot be made
correct in both trees until `examples/` mirrors the private tree, and that is phase 8's job.

Three more sites name the retired blacklist path and move with this change, because they
are consistent with the *default* rather than with the live file:
`skills/job-search/companies.yaml:387`, `skills/job-search/scripts/registry.py:423`,
`skills/job-search/scripts/tests/test_overlay_blacklist.py:3`. Likewise
`skills/resume-writer/scripts/build_tailoring_card.py` docstrings and
`scripts/tests/test_tailoring_card.py` fixtures still use `interviews/behavioral/story-bank/`.

## Definition of done

- [ ] The four defaults derive the lifetime layout, and `examples/` has the shape that
      makes them resolve — one change, or neither
- [ ] `automation/shared/tests/test_config_accessors.py` pins each new default, since it
      is the file that pins every default this family has
- [ ] Re-vendored; `sync_vendored.py --check` clean
- [ ] The three job-search sites and the resume-writer docstrings/fixtures move with them
- [ ] A smoke assertion that every `config.*()` path exists **under the example config**,
      not only under the maintainer's — the gap this task exists to close is exactly the
      one a maintainer-only check cannot see
