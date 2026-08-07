# Current state

- **Last-updated**: 2026-08-06

**2026-08-06 layout correction in progress.** The owner replaced the private overlay's
lifetime-first placement with a person-first one: applications move below `me/applications/`,
company interview preparation below `me/interviews/companies/`, and loose candidate sources
below `me/career/`. The cross-workflow company identity index moves to `market/`. The public
and private PRs are tracked in
[`2026-08-06-private-overlay-personal-taxonomy`](../../tasks/3_in-review/2026-08-06-private-overlay-personal-taxonomy/task.md);
the dated phase-5 paragraphs below remain the record of the layout they originally described.

*Groomed 2026-07-31 after an audit found this page four merges stale under a fresh
date. Every claim below was re-derived from the tree that day — task folders read
from `tasks/`, gate lists read from `.github/workflows/ci.yml` and
`automation/hooks/pre-commit`, the link count re-run. Where a claim was a count that
only re-measurement can keep true, it was replaced by the command that produces it.*

- **Process layer**: the AgentFold restructure is **done and closed**, not in
  flight — all four PRs (#56–#59) merged on 2026-07-22, and the task moved to
  `tasks/4_done/` on 2026-07-31. `message-queue/`, `tasks/`, `memory/`,
  `templates/`, `docs/roadmap/`, `history/` and the reconciler all ship, in both
  repositories, with `reconcile --check` wired into pre-commit and CI.
  `--require-roots` is **pre-commit only**, and only when `private/` is mounted:
  CI runs the reconciler deliberately without it (`.github/workflows/ci.yml`, the
  comment directly above the step), because the flag asserts that every process
  root exists and the published export ships fewer of them. The same split applies
  to the link checker. One item was reversed: top-level `handbook/` + `design/` became
  `docs/{handbook,designs}` under workspace phase 2's superseding ADR. *(This
  bullet described a PR train "in review" for nine days after it merged. No date
  check catches that: the reconciler's `roadmap-dated` gate proves only that the
  `Last-updated` line is a real, non-future date, and the gardener's
  `roadmap-staleness` routine only measures its age. A wrong bullet under a fresh
  date reads as current to both — re-dating means re-reading.)*
- **Email program**: design merged (PR #54: `docs/designs/application-progress-calendar/`,
  `docs/designs/raw-data-layer/03-provider-interfaces.md`, `04-email-download-categorization.md`).
  Stage 1 built on `email/stage-1-provider-contract` (PR #60): send-less
  `MailProvider` contract + audited transport + route allowlists
  (`automation/shared/mail/`), Outlook relocated behind it unchanged,
  folder-walking `check_mail_safety.py` in pre-commit, skill renamed
  `skills/email-assistant/` (no alias; the overlay's `references_private`
  folder is already renamed). Stage 2 (tracker schema v6 + the single
  calendar file) is merged; its owner-review UX revision makes events and
  todos scannable while retaining broad reporting phases. **Stages 3–5, re-checked
  against `tasks/` on 2026-07-31** — this page previously called them "not started",
  contradicting the census in `docs/roadmap/desired-state.md` item 1; the two files
  are read as a pair, so they must agree. Stage 3 is `tasks/3_in-review/2026-07-22-email-store-sync`
  and stage 1's own task is likewise still in `3_in-review`, both held for missing
  definition-of-done evidence; stage 4 is the one genuinely in flight
  (`tasks/1_in-progress/2026-07-22-email-progress-reconciliation`); and **stage 5 —
  the store-first review cutover — has no task file at all**, only the design's own
  section, with filing gated on stage 4 landing plus the dual criterion in
  `memory/decisions/raw-data-layer-decisions.md` row 14. Owner follow-up: the one
  read-only `--live` conformance run.
- **Job store**: raw-data-layer stages 0–4 shipped (PRs #49–#53) — library,
  capture boundary, builder, pipeline integration, retention/gardener. The
  skip-logs remain the sole search/draft skip authorities (store projection
  question parked).
- **Token-usage modes**: R1+R2 complete and merged (draft legs −29% tokens /
  −27% time at equal blind-graded quality); stage-benchmark fixtures v1 +
  harness live.
- **Tracker**: meta.yaml schema v6 (per-job status + folder rollup +
  structured `jobs[].progress` + ordered multi-occurrence `calendar_items` links
  into the single `calendar.md` via `config.calendar_path()`) is current; v5 is
  rejected after the preview-first migration cutover. Calendar rows lead with the time or action, link to role
  context, and keep machine metadata to one hidden compact line.
- **Quality gates**: pull-request CI classifies the cumulative `main`-to-head diff,
  runs policy and credential defenses unconditionally, and fans only affected
  long-running test families into isolated matrix jobs. Unknown inputs fail closed
  to the full matrix; every `main` and manual run is full. A stable final `build`
  result blocks on every selected job, while PR-description validation is a
  separate `pr-body` workflow so prose edits do not rerun product tests. **None of
  it is advisory** — the workflows contain no `continue-on-error:`. The tracked
  pre-commit hook runs nine gates. *Neither list is restated here on purpose*:
  `.github/workflows/`, `automation/gates/run_gates.py`, and
  `automation/hooks/pre-commit` are the lists. The two facts worth carrying: the
  reconciler and the link checker run in CI **without** `--require-roots` by design,
  and every public commit needs a row in
  `automation/publish/review_ledger.yaml` — the review gate blocks in both
  pre-commit and CI.
- **Workspace restructure**: phases 0 (leak guard/config-discovery/pre-push
  fail closed instead of open, `sync_skill_manifests.py` makes `SKILL.md`
  frontmatter the sole visibility SSOT, eleven config accessors, widened link
  checker + `--require-roots`), 3 (public-change review gate,
  `automation/publish/review_gate.py` + `review_ledger.yaml`), and 4 (the
  eight inbound public→private symlinks deleted; profiles/private-skill
  access now goes through config accessors and git-ignored `.claude/skills`
  /`.cursor/skills` links) are **merged** (PRs #81–#86, commits
  `72d45e2`…`7809b4b`). Phases 1 (both orphaned items refiled inside the
  overlay; the scratch tree classified, never emptied) and 2 are **merged and
  closed** — both task folders sit in `tasks/4_done/`
  (`2026-07-28-workspace-phase-1-orphans`, `2026-07-28-workspace-phase-2-public-cleanup`),
  and phase 2's five PRs (#99–#103) plus the ledger re-anchor (#105) are on `main`,
  which is why the root shape described next is the one you see in a fresh clone.
  Phase 2 gave the public tree its final root
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
  **Phase 6 shipped** — `automation/shared/skip_log.py` makes the applications
  skip-log authoritative rather than derived; its task is in `tasks/3_in-review/`,
  one ledger row behind. **Phase 7 is done** — `automation/shared/company_index.py`
  is the single company index every alias lookup resolves through, and its task is in
  `tasks/4_done/2026-07-28-workspace-phase-7-company-key`, with two follow-ups filed:
  7b (put `company_key` on every application `meta.yaml`) in `tasks/3_in-review/` and
  7c (durable vs disposable timeline) in `tasks/0_backlog/`. **Phase 8 is mostly
  landed, not unstarted** (`tasks/0_backlog/2026-07-28-workspace-phase-8-instruction-surface`)
  — this page said "only phase 8 is genuinely unstarted" on 2026-08-01 and that was
  wrong in both halves. Its instruction-surface column was re-measured to **zero
  work** (phase-2 and phase-5 tokens: 0 stale references across all 11 public
  `SKILL.md`), and its `examples/` reshape **landed 2026-08-02** (`261b4f0`,
  `8c8112a`): `examples/` now mirrors the private tree as `applications fixtures
  market me screenshots store`, and `.github/workflows/ci.yml:252` pins
  `validate_store.py examples/store`. What is left is the ratification of the seven
  calls the reshape was built on — `message-queue/needs-human/decisions/examples-reshape-seven-calls.md`,
  now ratify-or-revert — plus D7, the one call that was **not** built (no `companies/`
  counterpart was added under `examples/`, so `config.companies_root()` still resolves to
  nothing under the example config), and the inherited accessor item.
  The task stays in `0_backlog/` because those are open, not because the work is.
  See `docs/designs/workspace-restructure/execution-plan.md`.
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
  contain a newline. **Do not quote a break count from this page** — it moves with
  every commit and has an authoritative source: run
  `.venv/bin/python automation/gardener/verify_links.py`, the same routine CI and
  pre-commit gate on, which prints broken / advisory / permitted and exits non-zero
  only on `broken`. Re-run 2026-07-31 in a config-less checkout with no overlay
  mounted: **0 broken, exit 0.** The verified/advisory/permitted totals are omitted
  deliberately: the verified total moved on every single document this grooming pass
  touched, including this one, which is the whole reason the command belongs here
  instead of a number.
  Two further owner decisions landed 2026-07-29: phase 5 moves
  company-specific interview material into company folders and reorganises
  nothing else (`memory/decisions/interview-material-moves-by-company-only.md`,
  which withdraws the plan's "four dozen judgment calls" item; its one open
  clarification, covering 55 non-company files, was answered 2026-07-29 —
  relocated to `me/interviews/…`, not reorganised — so every one of the 552
  interview files now has a named destination), and config discovery keeps
  Option A (`memory/decisions/config-discovery-example-fallback.md`, a
  record-and-close — the behaviour was already live). The coding interview
  screenshot inbox now lives at `private/me/interviews/practice/TODO/`; both
  private consumers poll that path, and the existing screenshot was moved there
  byte-for-byte
  (`memory/decisions/interview-screenshot-inbox-moves-to-personal-practice.md`).
  The scratch-tree classification is deferred by the owner; it blocks nothing,
  which was checked rather than assumed. Still awaiting an answer:
  `message-queue/needs-human/decisions/private-scope-reconciler.md`, deliberately
  left open, plus two filed 2026-07-30 alongside phase 5: whether `history/`
  should be untracked and confirmation that the story bank keeps its leaf
  directory name (already implemented).
