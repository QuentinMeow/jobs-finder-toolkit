# Current state

- **Last-updated**: 2026-07-30

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
  trusted green. **Phase 5 is now also complete and in review** (2026-07-30): 747
  tracked private files relocated across 32 commits into `me/` · `companies/` ·
  `market/` · `store/` · `evals/`, with `applications/<status>/<slug>/` untouched,
  the tracked total unchanged at 3,186, and every relocation recorded by git as a
  rename. `history/` was dropped from the phase and filed as its own decision — it
  is the only row in the move table that would remove files from a tracked history
  rather than relocate within one. The three checks that fail *open* were each
  re-proved on a planted defect: the search skips load 367 URLs from the new
  location, the tailoring card rebuilds with its 7 stories and its staleness check
  goes fresh → STALE → fresh, and `--require-roots` refused the first commit after
  the move because a checker constant still named `benchmark/fixtures/`.
  **Phases 6–8 are not started**; their preconditions are now met and their task
  files carry re-measured scope. See
  `docs/designs/workspace-restructure/execution-plan.md`.
- **The link-checker repair merged ahead of phase 5** — owner decision, 2026-07-29,
  and it was the right order for a reason nobody had seen yet. `verify_links.py`
  enumerated with `git ls-files` in the **public** repo, so it had never opened a
  single file inside the overlay; removing `interviews/` from `SKIP_PREFIXES` would
  have changed which public docs may name those paths and nothing else. It now reads
  markdown links, heading anchors, refs at unrecognised roots, and the overlay's
  1,019 tracked `.md`; it sorts a break by what its source document is FOR (a
  handbook page fails, a plan is advisory, a dated record is permitted); it follows
  renames across both repositories so a move cannot report a regression that did not
  happen; and it runs in CI and pre-commit, where it previously ran nowhere. The
  "31–36 broken, no two checkers agree" mystery was one omission: a code span may
  contain a newline. The real count is **23, every one in a dated record**.
  Two further owner decisions landed 2026-07-29: phase 5 moves
  company-specific interview material into company folders and reorganises
  nothing else (`memory/decisions/interview-material-moves-by-company-only.md`,
  which withdraws the plan's "four dozen judgment calls" item; its one open
  clarification, covering 55 non-company files, was answered 2026-07-29 —
  relocated to `me/interviews/…`, not reorganised — so every one of the 552
  interview files now has a named destination), and config discovery keeps
  Option A (`memory/decisions/config-discovery-example-fallback.md`, a
  record-and-close — the behaviour was already live). The scratch-tree
  classification is deferred by the owner; it blocks nothing, which was checked
  rather than assumed. Still awaiting an answer:
  `message-queue/needs-human/decisions/private-scope-reconciler.md`, deliberately
  left open, plus three filed 2026-07-30 alongside phase 5: whether `history/`
  should be untracked, confirmation that the story bank keeps its leaf directory
  name (already implemented), and where the coding-interview screenshot inbox
  lives (left where it is on purpose).
