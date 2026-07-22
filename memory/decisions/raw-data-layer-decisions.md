# Raw-data-layer design family: owner decisions

- **Status**: decided; follow-up git-policy decisions were resolved on 2026-07-22
- **Date**: 2026-07-21
- **Decided by**: owner, answering the self-contained decision blocks in
  `design/raw-data-layer/` (v2, post-review)

## Context

The raw-data-layer family (store core, job postings, provider interfaces,
email download) reached owner review with 18 decision blocks. The owner
answered them inline in the docs; this ADR is the durable record. The design
docs fold every answer into their text and keep only compact
"Decisions (resolved)" tables; the full original option analyses live in
git history of those docs.

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Overlay git tracking (jobs store) | Originally tracked `derived/`, `index/`, `annotations/`, and `state/`; gitignored `raw/`. Real-store size later changed the derived-zone decision: [keep `derived/` out of git](derived-zone-git-tracking.md). Missing raw remains a normal `not-synced-here` state |
| 2 | Raw retention | A **GC expression config**, not fixed day-counts: independent filters on posting/reposting date and last-observed date, combined with AND by default, OR or single-filter supported (e.g. "posting date > 90 d AND last observed > 30 d") |
| 3 | Builder lock contention | Fail fast |
| 4 | Public fixture-store size | 100 KB **soft threshold**: exceeding warns a human; human approval can raise the (configurable) threshold |
| 5 | Neutral identifier slugs | Yes — with mechanical safeguards so AI can't err: library-allocated slugs only, strict write-time pattern validation, leak-guard coverage of mapped real values |
| 6 | Materialize gate-suppressed sweep rows | No — record each in a **review queue** (partial info + raw manifest path) for optional manual review; never blocks the pipeline |
| 7 | Search/application logs as store projections | Defer — open item at `message-queue/needs-human/decisions/logs-as-store-projections.md`. Same answer ordered the **process-folder restructure**: open decisions live under `message-queue/` (see `memory/decisions/process-folders-v2-todo-queue.md`) |
| 8 | Scheduled board polling | No — on-demand polling; timelines are gap-tolerant; closure inference is not built at all |
| 9 | Skill rename | `outlook-email-assistant` → `email-assistant` at refactor time, no alias |
| 10 | Multi-account | Partition every store zone by account from day one; implement single-account first |
| 11 | Live conformance runs | Allowed, read-only, behind explicit `--live`, never CI |
| 12 | Gmail permission posture | Read-only (`gmail.readonly`); revisit only if Gmail drafting becomes a real daily need |
| 13 | Email sync folder scope | Inbox + Sent + Drafts |
| 14 | Store-first cutover criterion | **Dual**: 5 consecutive zero-mismatch comparison runs AND ≥300 job-related messages processed through both paths |
| 15 | Raw of `unrelated`-classified mail | Keep |
| 16 | At-rest encryption | None built. Documented assumption: private machines, user is responsible for protecting raw data (owner's clarifying question answered in the doc: FileVault already covers the one relevant scenario) |
| 17 | Email attachments | Content never captured; **metadata captured** (filename, size, content type, provider attachment ID) |

## Follow-up decisions

- **Email git policy (resolved 2026-07-22):** track only content-free index
  headers and safe annotations; keep raw, derived, message index rows, and
  the evidence sidecar out of git. See
  [email-git-policy.md](email-git-policy.md).
- **Jobs derived-zone policy (resolved 2026-07-22):** the real build showed
  that `derived/` is large and churn-heavy, so it is no longer tracked. See
  [derived-zone-git-tracking.md](derived-zone-git-tracking.md).

## Consequences

- Jobs stages 0–4 shipped. The remaining email work is split into focused
  tasks linked from `design/application-progress-calendar/execution-plan.md`;
  no part is decision-blocked.
- The lifecycle/closure-inference spec was pruned from doc 02 (recoverable
  from git history); reviving it requires a new `message-queue/needs-human/decisions/` item.
- Decisions 1, 2, 4, 5, 6, 7, 8, 14, 16, 17 changed the design beyond the
  recommended options (the rest accepted recommendations as-is); the docs' "Decisions (resolved)" tables link each
  answer to the section that implements it.
