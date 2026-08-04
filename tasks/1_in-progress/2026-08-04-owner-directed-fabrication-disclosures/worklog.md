# Worklog — 2026-08-04-owner-directed-fabrication-disclosures

## 2026-08-04 — session 1 (Codex)

- Claimed the owner-directed policy reversal before editing the root or skill contracts.
- Replaced the absolute fabrication ban with a direct-human, claim-specific behavioral exception.
- Added a per-answer `fabrication_disclosures` schema for fabricated, unsupported, and
  source-conflicting claims plus a collapsed private/not-spoken renderer.
- Added validator coverage for the authorization marker, ISO date, evidence note, affected fields,
  duplicate claims, supported statuses, and unknown fields.
- Added a behavioral canary for the authorized path while retaining default adversarial rejection.
- Recorded the owner decision in an ADR and kept repository/PR/gate measurements factual.
- Passed 20 answer-bank unit tests, Python compilation, canary YAML parsing, and `git diff --check`.
- The fresh GPT-5.6 Sol high canary was rejected before execution because the checkout exposes a
  private overlay; filed an informed-consent decision for a temporary public-only run.
- Passed the full impact-aware gate bundle in both the working checkout and a detached config-less
  public checkout at `4243d59`; both worktrees were clean afterward.
- Opened draft PR #314; every GitHub check is green, but the PR remains intentionally unmergeable.

## 2026-08-04 — session 2 (Codex)

- Recovered the private interview branch after a laptop crash and assigned one GPT-5.6 Sol high
  subagent to each of eight answer topics.
- Applied the disclosure schema to every requested unsupported or source-conflicting claim.
- Marked each chosen story with `(Select)`, regenerated deterministic aliases, and passed full
  source validation, freshness, private content tests, and whitespace checks.
- Committed and pushed the private answer refresh at `c53804d`, then updated private PR #79.
- Kept exact-claim authorization as the active default; the broader category-level policy remains
  pending owner input.

## 2026-08-04 — session 3 (Codex)

- Corrected the selected-answer navigation after confirming the original `(Select)` markers were
  buried inside collapsed answer summaries.
- Added a singular/plural selected-answer index immediately below every rendered question title
  while retaining the marker on each selected collapsed summary.
- Regenerated all eight company-specific answers; Earn Trust lists both selected stories, while the other
  seven questions each identify one selected story.
- Added a regression test for exact title-to-index adjacency, singular/plural rendering, and the
  secondary collapsed-summary marker.
- Added optional validated `follow_up_questions` plus tagged Markdown bullets for both detailed
  reference styles, then populated them for every selected story.
- Tightened the selected quick answers into high-level 1:30-1:42 versions and kept implementation
  details in the short and long expansions.
- Passed the full private source validation, regeneration, freshness check, private content test,
  public unit tests, reconciler, instruction budget, impact-aware gates, and whitespace checks.
- Preserved the crash-recovered private commit on `interview/03-selected-answer-navigation` and
  restored the local private `main` pointer to `origin/main` without discarding content.
