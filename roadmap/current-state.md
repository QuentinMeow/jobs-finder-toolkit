# Current state

- **Last-updated**: 2026-07-22

- **Process layer**: AgentFold restructure in flight as a stacked PR train —
  `message-queue/` + `tasks/` + `memory/` merged (#56); `handbook/` +
  `design/` (#57) and `skills/` + `automation/` (#58) in review; this PR
  adds `templates/`, `roadmap/`, `history/`, and the reconciler.
- **Email program**: design merged (PR #54: `design/application-progress-calendar/`,
  `design/raw-data-layer/03-provider-interfaces.md`, `04-email-download-categorization.md`).
  Stage 1 built on `email/stage-1-provider-contract` (PR #60): send-less
  `MailProvider` contract + audited transport + route allowlists
  (`automation/shared/mail/`), Outlook relocated behind it unchanged,
  folder-walking `check_mail_safety.py` in pre-commit, skill renamed
  `skills/email-assistant/` (no alias; the overlay's `references_private`
  folder is already renamed). Stage 2 (tracker schema v5 + the single
  calendar file) is implemented on `email/stage-2-progress-calendar`,
  stacked on Stage 1. Stages 3–5 not started. Owner follow-up: the one
  read-only `--live` conformance run.
- **Job store**: raw-data-layer stages 0–4 shipped (PRs #49–#53) — library,
  capture boundary, builder, pipeline integration, retention/gardener. The
  skip-logs remain the sole search/draft skip authorities (store projection
  question parked).
- **Token-usage modes**: R1+R2 complete and merged (draft legs −29% tokens /
  −27% time at equal blind-graded quality); stage-benchmark fixtures v1 +
  harness live.
- **Tracker**: meta.yaml schema v5 (per-job status + folder rollup +
  structured `jobs[].progress` + the single `calendar.md` via
  `config.calendar_path()`) is current on the stage-2 branch; v4 is rejected
  after the preview-first `migrate_to_v5.py` cutover. The OWNER must run the
  migration on `private/` applications before their next tracker run.
- **Quality gates**: CI runs vendor drift, compileall, example render +
  validate, four unit suites, store fixture validation, leak guard, and
  gitleaks; pre-commit mirrors the fast checks + instruction budgets + the
  reconciler.
