# Worklog — 2026-08-26-issues-267-274-occupation-evidence

## 2026-08-26 — session 1 (occupation-evidence implementation agent)

- Validated both issues at the current branch base: the frozen 25-title matrix produced 24 main matches and only one review, including every reported lexical collision.
- Rejected a larger keyword blacklist and an inferred occupation taxonomy. Added an optional profile-owned `titles.primary` boundary that can only move an included title from the main lane to bounded review.
- Added fictional mobile, SDET, gameplay, robotics, technical-writing, compiler, database, and engineering-manager controls. The final matrix is 10 target matches, 15 reviews, and zero hard drops.
- Full job-search tests, the filter corpus, and the config-less impact gate passed. No skill instruction file changed, so no skill canary was required.
- Next: independent branch review, then publication as one PR closing #267 and #274.
