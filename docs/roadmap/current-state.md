# Current state

- **Last-updated**: 2026-07-29

- **Process layer**: AgentFold restructure in flight as a stacked PR train —
  `message-queue/` + `tasks/` + `memory/` merged (#56); `docs/handbook/` +
  `docs/designs/` (#57) and `skills/` + `automation/` (#58) in review; this PR
  adds `templates/`, `docs/roadmap/`, `history/`, and the reconciler.
- **Email program**: design merged (PR #54: `docs/designs/application-progress-calendar/`,
  `docs/designs/raw-data-layer/03-provider-interfaces.md`, `04-email-download-categorization.md`).
  Stage 1 built on `email/stage-1-provider-contract` (PR #60): send-less
  `MailProvider` contract + audited transport + route allowlists
  (`automation/shared/mail/`), Outlook relocated behind it unchanged,
  folder-walking `check_mail_safety.py` in pre-commit, skill renamed
  `skills/email-assistant/` (no alias; the overlay's `references_private`
  folder is already renamed). Stage 2 (tracker schema v5 + the single
  calendar file) is merged; its owner-review UX revision makes events and
  todos scannable while retaining broad reporting phases. Stages 3–5 not started. Owner follow-up: the one
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
  `config.calendar_path()`) is current; v4 is rejected after the preview-first
  migration cutover. Calendar rows lead with the time or action, link to role
  context, and keep machine metadata to one hidden compact line.
- **Quality gates**: CI runs vendor drift, compileall, example render +
  validate, four unit suites, store fixture validation, the public-change
  review gate (`review_gate.py --verify-all`), leak guard, and gitleaks;
  pre-commit mirrors the fast checks + the staged-index leak guard + the
  review gate + instruction budgets + the reconciler with `--require-roots`.
  Every public commit now needs a row in
  `automation/publish/review_ledger.yaml`.
- **Workspace restructure**: phases 0 (leak guard/config-discovery/pre-push
  fail closed instead of open, `sync_skill_manifests.py` makes `SKILL.md`
  frontmatter the sole visibility SSOT, eleven config accessors, widened link
  checker + `--require-roots`), 3 (public-change review gate,
  `automation/publish/review_gate.py` + `review_ledger.yaml`), and 4 (the
  eight inbound public→private symlinks deleted; profiles/private-skill
  access now goes through config accessors and git-ignored `.claude/skills`
  /`.cursor/skills` links) are **merged** (PRs #81–#86, commits
  `72d45e2`…`7809b4b`). Phases 1 (both orphaned items refiled inside the
  overlay; the scratch tree classified, never emptied) and 2 are **complete and
  in review** as open stacked PRs. Phase 2 gave the public tree its final root
  shape: the former generic maintenance bucket is split into
  `automation/gardener/`, `automation/search-recall-audit/` and
  `automation/company-levels/` with six of nine depth constants replaced by an
  upward `.git` walk; the three human-doc roots sit under one parent as
  `docs/handbook/`, `docs/designs/` and `docs/roadmap/` (superseding ADR:
  `memory/decisions/docs-parent-for-the-human-read-trees.md`) with the published
  file set unchanged at 566 files; `evals/` absorbed all measurement into
  `protocols/` + `canaries/<skill>.yaml` beside the existing `rubrics/` and
  `results/` with all nine canary sets byte-identical across the move; and the
  gitignored scratch root is renamed `tmp/` → `local/` (one filesystem rename of
  an untracked tree — 102 files in, the same 102 paths out; the `.gitignore`
  rule, both link-checker skip lists, and every default write path move with
  it). Each moved check was re-proved against a planted defect rather than
  trusted green. Two gaps the phase exposed are filed and open:
  `verify_links.py` checks no `[text](path)` links at all (31–36 broken today, depending on
  the checker — no two agree, which is itself the finding) and
  silently drops backticked refs at unrecognised roots, and phase 8's per-skill
  path counts are now obsolete. Phases 5–8 not started; their task files carry
  the re-measured preconditions. See
  `docs/designs/workspace-restructure/execution-plan.md`.
