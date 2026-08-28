# Worklog — 2026-08-26-issues-267-274-occupation-evidence

## 2026-08-26 — session 1 (occupation-evidence implementation agent)

- Validated both issues at the current branch base: the frozen 25-title matrix produced 24 main matches and only one review, including every reported lexical collision.
- Rejected a larger keyword blacklist and an inferred occupation taxonomy. Added an optional profile-owned `titles.primary` boundary that can only move an included title from the main lane to bounded review.
- Added fictional mobile, SDET, gameplay, robotics, technical-writing, compiler, database, and engineering-manager controls. The final matrix is 10 target matches, 15 reviews, and zero hard drops.
- Full job-search tests, the filter corpus, and the config-less impact gate passed. No skill instruction file changed, so no skill canary was required.
- Next: independent branch review, then publication as one PR closing #267 and #274.

## 2026-08-27 — session 2 (occupation-evidence repair)

- Independent review reproduced a missing #267 control: `primary: [ios, mobile]` still promoted Mobile Mechanic and Mobile Sales Representative. The expanded 29-title baseline at `4a1fdb2` was 14 main matches and 15 reviews, with those two false matches.
- Replaced broad primary tokens in the frozen profiles with occupation-bearing phrases, added Android and React Native recall controls, and moved both reported mobile-adjacent titles to bounded review. The repaired matrix is 12 target matches, 17 reviews, and zero hard drops.
- Added decisive primary rule/evidence to every main match and pinned absent/empty compatibility, include-miss behavior, explicit-exclude precedence, and the full pipeline's configured word-filter review rescue.
- Updated the profile guidance to state the real bounded/separator-insensitive matching semantics and the remaining risk: scripts cannot prove a phrase denotes an occupation without becoming a global taxonomy.
- Repaired verification is green: 8 focused occupation tests, 199 impacted focused tests, 827 full job-search tests, 185 corpus cases, and all 12 impact-selected policy/job-search gates.
- Recorded the repair review row and prepared the clean branch commit for fresh independent review; publication remains intentionally deferred.

## 2026-08-27 — session 3 (occupation-evidence precedence repair)

- Added paired iOS-only controls proving explicit Android and React Native exclusions remain
  hard `no_match` decisions, while the broad mobile profile keeps both titles as target matches.
- Recorded the exact dependency on `codex/issue-234-manager-product-corpus` at
  `67a0375f012e7ef579482de5b0272d4ec13bb0b2` (open PR #371): publish stacked on
  that branch while the PR is open, or rebase onto `main` only after it merges.
- Refreshed evidence is green: 9 focused occupation tests, 200 impacted focused tests,
  828 full job-search tests, 187 corpus cases, and all 12 impact-selected policy/job-search gates.

## 2026-08-27 — session 4 (Codex merge orchestrator)

- After PR #371 merged, refreshed the reviewed occupation branch from current `main` without a
  rebase or force-push. The append-only review ledger was the sole conflict, and the resolution
  preserved both histories plus the exact reconciliation row.
- Independent review approved final head `ebac6a99`; all 12 selected gates, all 828 job-search
  tests, and GitHub CI passed without changing the reviewed occupation feature bytes.
- The repaired explicit-prefix stack driver merged PR #374 behind independently confirmed PR #371.
  The merge landed as `71ec5b0a`, closed issues #267 and #274, and the local branch and worktree
  were later retired through recoverable cleanup.
