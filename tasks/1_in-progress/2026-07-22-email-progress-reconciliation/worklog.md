# Worklog — 2026-07-22-email-progress-reconciliation

## 2026-07-22 — session 1 (Codex root + Terra agents)

- Migrated the private application fleet to schema v5, then implemented deterministic categories, derivation-aware links, reply/deadline projections, exact-message re-verification, and neutral email provenance for progress/calendar updates.
- Reviewed all 615 locally stored messages. Applied only exact evidence, cleaned stale tracker actions, synchronized logs, and routed ambiguous associations to the private owner queue.
- Live review exposed and fixed reply false positives and stale calendar labels; all application metadata and calendar links validate.
- Keep the task in progress: automatic linking is intentionally fail-closed without curated company-domain evidence, and the five-run zero-mismatch cutover gate has not been met.

## 2026-07-22 — session 2 (Codex root)

- Folded the owner's answer for ambiguous positive company-level signals into the private decision and email-assistant reference layers.
- Applied the confirmed policy to the one affected applied application; no physical merge was needed because the company had only one applied folder.
- Future ambiguous positive signals remain confirmation-first; negative evidence keeps its separate fail-closed scope.
