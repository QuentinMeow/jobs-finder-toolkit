# Post-merge decision triage — an ordered worklist for `message-queue/needs-human/decisions/`

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: the 46-PR stack merge (`#135`–`#180`); `message-queue/needs-human/decisions/`
- **Claimed-by**:

## Goal

One ordered list the owner can work through top to bottom after the stack merge, instead of
re-deriving priority from 26 separate queue files. Answering a row means editing the queue file's
`**Your answer:**` line (or saying it in chat, which an agent then writes into the file per the
boot ritual) — this task is the index, not a replacement for the files themselves.

## Context

`message-queue/needs-human/decisions/` holds 26 items (27 files minus `README.md`), read in full
on 2026-08-01. Three are not live decisions and are called out separately below rather than ranked:

- `logs-as-store-projections.md` — **Status: parked-until-revisit**, waiting on raw-data-layer
  execution-plan stage 3 to ship and run for a few weeks.
- `private-scope-reconciler.md` — asked once (2026-07-29), the owner said "leave the other one
  undecided," and the file itself says **"do not re-ask it."**
- ~~`sponsorship-classifier-hedged-offer-shapes.md`~~ — **DELETED 2026-08-02**, per
  `message-queue/needs-human/decisions/README.md` ("resolved/handled items are deleted in the
  resolving commit — git history is the archive"). It was
  `resolved-by-implementation (2026-07-31)` and all three ADRs that record it were verified
  present first: `memory/decisions/sponsorship-offer-versus-denial.md` and its two successors
  `sponsorship-scope-limits-need-a-distributive-quantifier.md` and
  `sponsorship-an-unsettled-denial-is-review-not-a-silent-drop.md`. Its one optional residual
  (a `yes_conditional` label) was not lost — it survives in the first ADR's *Alternatives
  considered*: *"Still available if the owner wants hedged rows findable under
  `require_positive`."*

The remaining 23 are ordered below by **cost of leaving the default path running longer**, not by
filed date. Concretely: does the default path (a) silently do something a user would only notice
by accident — lost job matches, wrong tracked data, an agent moving something it should have
asked about — and (b) does that cost compound with every run/day it stays undecided, or is it a
one-time/reversible cost? Items where the default is itself the safe, recommended, already-applied
behaviour (most "confirm the obvious" and pure documentation-scope items) sort to the bottom
regardless of file size — a 26 KB file with seven sub-decisions (`process-weight-what-to-cut.md`)
is not urgent just because it is long; its default is full status quo on every sub-item.

Two items are recurring, silent, job-search-result losses and are ranked highest for that reason:
`title-prefilter-hardcoded-seniority-words.md` and `first-search-recency-window.md` both describe
real postings the pipeline would have kept, dropped with zero trace, on every run the condition
recurs (not a one-off). **2026-08-02: both are now answered and folded** — see rows 1 and 2; the
work each authorizes is in `tasks/0_backlog/`, not in this queue.

**If you disagree with the ordering**, the fix is cheap: each queue file is unaffected by this
table's position — reorder your own pass through them and this file goes stale, which is fine,
it is a worklist, not a record.

### Ordered worklist

| # | Decision file | Question | Default while pending | What changes when answered | Min. |
|---|---|---|---|---|---|
| 1 | ~~`title-prefilter-hardcoded-seniority-words.md`~~ **ANSWERED + FOLDED 2026-08-02** | Should the big-tech title prefilter keep its hardcoded seniority skip list, or defer to the profile's `titles.exclude`? | — | Owner rejected the binary: filter words become profile-owned in three classes (hard-exclude / soft-exclude / inclusion). Recorded in `memory/decisions/search-filter-vocabulary-is-profile-owned.md`; conformance checklist filed as `tasks/0_backlog/2026-08-02-profile-owned-search-filter-vocabulary/`. | 0 |
| 2 | ~~`first-search-recency-window.md`~~ **ANSWERED + FOLDED 2026-08-02** | Should a company's FIRST-ever automated search use a wider recency window? | — | Owner chose Option B. Recorded in `memory/decisions/first-search-finds-every-open-role.md`; implementation filed as `tasks/4_done/2026-08-02-first-search-widens-the-recency-window/`. | 0 |
| 3 | `may-a-mailbox-review-move-your-applications.md` | May a mailbox review move applications on its own, or must every status change be asked for? | The QUEUE FILE says "ask first," but the underlying `email-assistant/SKILL.md` text still says "automatically reconcile" — the two disagree, so the safe behavior depends on which doc an agent reads first, not on this file. | Fixes the underlying SKILL.md/tracker/AGENTS.md text so the safe behavior is guaranteed, not just documented as a default. | 5 |
| 4 | `2026-07-31-re-enrich-yoe-after-attribution-fix.md` | Should already-enriched applications be re-run now that third-party years no longer count as a requirement? | Nothing is rewritten — any `meta.yaml` enriched before the fix can carry a fabricated `required_yoe`/`job_level` (e.g. "senior_staff" inferred from a founder's 25-year bio line) that's already sitting in your tracker today. | Recommended Option C re-enriches only the folders whose `required_yoe.min` looks implausible for the role — a spot-check, not a blanket rewrite. | 10 |
| 5 | ~~`handoff-records-non-clean-scaffolds.md`~~ **ANSWERED + FOLDED 2026-08-02** | Should handoff record a posting whose scaffold came out incomplete? | — | Owner chose Option A, conditional on nothing but the owner ever deleting an application folder (both conditions verified before folding). Recorded in `memory/decisions/handoff-records-every-folder-it-creates.md`; the premise-pinning check is filed as `tasks/0_backlog/2026-08-02-pin-the-never-delete-an-application-folder-premise/`. | 0 |
| 6 | `company-plus-date-structural-screen.md` | Should the leak guard screen for a real company name next to a date? | No mechanical screen exists for this shape; the human review gate is the *only* thing that catches it today (and has caught a real leak before). | Recommended Option B adds an advisory hint (never a blocker) drawn from the existing company registry — no new allowlist to maintain. | 5 |
| 7 | `retired-applications-log-yaml.md` | Delete the old `applications-log.yaml`, now that nothing reads it? | Left in place — confirmed as of 2026-07-31 to be a stale, drifting duplicate of the authoritative JSONL log (369/367 counts verified to match). | One `rm` + commit in the private overlay; frees nothing else. | 2 |
| 8 | `store-tied-fold-sort-key-re-derives-the-whole-store.md` | Should breaking the fold's tied sort key re-derive the whole store once? | Tie stays unfixed — `--rebuild` (the verify/repair path) refuses on a store that contains one; incremental builds are unaffected. | Recommended Option A extends the sort key, accepting one full re-derive (150–219s at 15k entities) that should ride along with an already-planned full fold. | 5 |
| 9 | `builder-lock-stale-window-vs-liveness.md` | Should the builder lock heartbeat, so a live-but-slow build is never stolen from? | Left as-is (recommended) — a build over 5 minutes can still be joined by a second builder; the dangerous 3-writer variant is already fixed separately. | Only matters if you have evidence a real build/GC run exceeds 300s; otherwise no action needed. | 3 |
| 10 | `does-the-review-ledger-bind-fork-contributors.md` | Does a fork PR owe review-ledger rows, or does the gate need a contributor exemption? | Nothing today (no fork PR has happened); the first one that arrives goes red on a gate that asks them to vouch for your privacy, with zero documentation. | Recommended Option B exempts fork PRs in CI; the maintainer records the review on the next commit instead. | 5 |
| 11 | `company-detector-over-the-skills-tree.md` | Should the review gate's company detector also read `skills/**`, not just the diff? | Diff-only detector; the one real instance found is already redacted. | Recommended Option B adds an advisory whole-tree scan (measured: 0 false positives on today's tree), run by hand or from the gardener — not wired into any gate. | 3 |
| 12 | `process-weight-what-to-cut.md` (7 sub-decisions D1–D7) | Has the process machinery outgrown the work it tracks, and which parts get cut? | Status quo on every rule; nothing deleted or weakened. Recurring cost is ledger-row overhead, not correctness risk. | Per-sub-decision: batches ledger rows per PR (D1), executes an already-decided ADR to untrack `history/` (D2), adds a `Depends-on` field + staleness-based backlog pruning (D3), routes review findings by a four-way rule (D4), gives `known-issues/` a `Review-by:` drain (D7), etc. | 30–45 (largest single item — 7 sub-answers) |
| 13 | `examples-reshape-seven-calls.md` (D1–D7) | Seven calls the `examples/` reshape (workspace phase 8) cannot make on its own. | Nothing moves; phase 8 stays in the backlog. | Unblocks ~33 file moves across 42 files' worth of references; each sub-item has its own recommendation (mostly "yes, do it this way"). | 20–30 |
| 14 | ~~`subagent-budget-cap-conflicts-with-long-sessions.md`~~ **ANSWERED + FOLDED 2026-08-20** | Should repository instructions retain any fixed subagent-count ceiling? | — | Owner chose deletion without replacement notes or compatibility wording. Recorded in `memory/decisions/subagent-counts-are-unconstrained.md`. | 0 |
| 15 | `history-untracked-in-phase-5.md` | Should workspace phase 5 untrack the 48 session handovers? | `history/` stays tracked in both repos (default); an already-recorded ADR consequence stays unimplemented. | Executing it (Option B) untracks 48 files from both remotes — flagged as worth its own reviewable commit, not riding inside a 764-file migration. | 5 |
| 16 | `phase-7c-descope-to-the-one-live-defect.md` | Build the durable/disposable timeline-marker machinery, or fix the one live defect it was chasing? | Already descoped to the recommended path: fix the one real defect (two skills specify incompatible note templates), build no marker/parser/rename machinery. | Two embedded sub-questions remain the owner's call: rename the narrative file (default: no), and where two large hand-written writeups move (default: leave them, add a pointer). | 5 |
| 17 | `store-gc-execute-agent-runnable-or-owner-only.md` | May an agent run the store GC's `--execute`, or is deleting payloads owner-only? | Agents run dry-run only, never `--execute`/`--remove-orphans` — fully safe; store is nowhere near a size limit. | Recommended Option A carves `--execute` out of the "never delete owner data" guardrail (keeping `--remove-orphans` owner-only), so GC can actually run unattended. | 5 |
| 18 | `should-the-contract-documents-name-the-review-gate.md` | Should `AGENTS.md` name the public review gate the way it names the reconciler? | No document changes; the gate is documented in `skills/github-workflow/SKILL.md` and self-teaches on failure. | Recommended Option B adds ~3 lines to `AGENTS.md`'s Guardrails, pointing rather than restating. | 2 |
| 19 | `doc-style-scope-design-docs-or-every-human-read-doc.md` | Does `doc-style.md` bind only `docs/designs/`, or every human-read document? | Practice already matches the narrow reading (§§1-4/§7 → design docs; §§5-6 → wherever a two-way field appears) — this just isn't written down anywhere as one rule. | Recommended Option C adds one scope paragraph to `doc-style.md` itself; no other file changes. | 2 |
| 20 | `orientation-skill-names-an-overlay-only-skill.md` | The orientation skill names an overlay-only skill by name, contradicting two "never name it" policy lines — which side gives? | Left as-is; no gate fires on it either way. | Recommended Option C rewrites the sentence to keep the affordance (why your runtime shows more skills than the public tree) without the name. | 3 |
| 21 | `gitleaksignore-for-reviewed-false-positives.md` | Should this repo carry a `.gitleaksignore` for reviewed false positives? | Already implemented as the default (Option A) — two commit-pinned fingerprints exist; PR is green. | Mostly a confirmation; Option C (accept red PR-range scans) is the only real alternative and is not recommended. | 2 |
| 22 | `story-bank-keeps-its-leaf-name.md` | Confirm: the story bank lands at `me/interviews/story-bank/`, not `.../stories/`? | Already what the tree and both design docs do; zero pending work either way. | Pure ratification — record it in `memory/decisions/` so it stops being an open question. | 1 |
| 23 | `public-history-privacy-rewrite.md` | Should the public repo's git history be rewritten to remove old overlay-skill identifiers? | History unchanged (recommended) — the identifiers are already gone from the current tree and future commits. | Only Option B (a full history rewrite + force-push + mandatory re-clone for every collaborator) would change anything, and it is not recommended. | 1 |

## Known-open defects (filed but unfixed) — visible in the same place

Not decisions — these are already-filed, already-scoped bugs sitting in `tasks/0_backlog/`,
surfaced here so they aren't lost behind the 23 rows above. There are **42** backlog items dated
`2026-07-31-*`/`2026-08-01-*` (2 P0, 16 P1, 24 P2). The ones a user of the toolkit would actually
notice, not just an agent maintaining it:

- **P0 — `2026-08-01-job-search-docs-route-the-location-policy-to-the-wrong-file`**: the
  job-search quickstart tells you to edit a file the search never actually reads for its location
  policy.
- **P0 — `2026-07-31-pr-verification-blocks-are-measured-off-the-stack`**: a gate transcript
  pasted into a PR body can silently describe a different tree than the one that merges (recurred
  twice; raised from P1).
- **P1 — `2026-08-01-forget-log-tells-the-agent-to-delete-owner-data`**: the skip-log's own
  documented remedy currently tells an agent to do the one thing `AGENTS.md` forbids outright —
  delete an application folder.
- **P1 — `2026-07-31-word-anchor-the-remaining-substring-keyword-lists`**: several gate-deciding
  keyword lists still match inside a longer word, so a gate can fire (or fail to fire) on the
  wrong token.
- **P1 — `2026-08-01-behavioral-prep-hardcodes-an-overlay-path`**: `behavioral-interview-prep`
  writes to a hardcoded `private/me/interviews/` path instead of a `config.*()` accessor, so it
  writes to the wrong place in any overlay not mounted at the default location.
- **P1 — `2026-07-31-store-entity-that-changes-company-leaves-a-stale-derived-dir`**: an
  incremental build can leave a duplicate posting behind under the entity's old company partition.
- **P1 — `2026-08-01-resume-writer-docs-misstate-what-check-py-enforces`**: resume-writer's own
  docs are wrong, in both directions, about what the validation gate actually checks.
- **P2 but user-visible — `2026-08-01-two-skills-give-different-calendar-write-orders`**:
  `email-assistant` and `interview-calendar` can produce inconsistent local/Outlook state from the
  same confirmed interview email, depending which skill runs.

The rest (8 more P1, 24 P2) are harness/testing/doc-drift items an agent would feel before you
would — see `tasks/0_backlog/2026-07-31-*` and `tasks/0_backlog/2026-08-01-*` for the full set.

## Visa-policy safety note

**`--visa-policy require_positive` is still not safe at the stack tip.** Per
`memory/known-issues/visa-sponsorship-negation-phrase-gap.md` (Severity: **high**, restored
2026-08-01): a sponsorship denial whose negation cue falls outside the classifier's reach (a
mid-sentence parenthetical is the filed reproduction) still returns `verdict: likely`,
`confidence: high`, `decision: match`, `classify_visa: yes` — so a posting that refuses
sponsorship in writing can be shortlisted, unflagged, to the one candidate who needs sponsorship.
The file names two candidate repairs and says the choice between them is an owner call.

## Definition of done

- [ ] Owner has read the ordered worklist and either worked through it top to bottom, or recorded
      an explicit reprioritization (this file is a suggestion, not a lock).
- [ ] Each answered decision follows the boot ritual: claim (`Status: folding`), fold the answer
      into the affected docs, record it in `memory/decisions/`, delete the queue file — after
      which this task's table row is stale by construction and may be struck through or the row
      count in the Goal updated.
