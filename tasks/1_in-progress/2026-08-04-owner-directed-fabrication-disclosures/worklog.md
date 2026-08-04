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
