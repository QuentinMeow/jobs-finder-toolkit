# Handover — 2026-07-31 overnight harness hardening

- **Date**: 2026-07-31
- **Task(s)**: eleven task folders, all in `tasks/3_in-review/` except the two named below —
  see each PR's "What was filed" section for the mapping

An overnight session that hardened the harness rather than the job hunt: gates that
reported clean without inspecting anything, tooling pointed at paths the owner's data
left years ago, and a company-key model that three validators disagreed about. Nothing
about the pipeline's job-search or drafting behaviour changed.

## What happened

- **An 11-PR public stack, `#122`–`#132`**, built sequentially on top of each other and
  never rebased. Roughly: CI now runs the gates the documents promised; four gates that
  passed on an empty inspection now fail; the tooling reads the owner's real data paths;
  three company-key validators agree and the guard walks the call graph instead of one
  function body; the instruction surface says what the code does; company-research stops
  calling beta products shipped. The top PR is corrections found by an independent
  verification of the other ten, plus this record.
- **One private PR, `#63`** in the overlay repo, keys every application to the company
  index. It is independent of the public stack; the public stack was checked against the
  owner's real tree and does not break it.
- **The stack was verified adversarially by an agent that wrote nothing.** Both gate
  compositions green, seven planted failures caught by the gates that claim to catch them,
  the review ledger append-only across 42 new rows, vendored copies byte-identical, and a
  295-token cross-reference of the owner's real private data against every tracked public
  file with zero hits on name, email, account, or any of 243 application slugs. It found
  no code defect. It found six inaccurate transcripts in the stack's own records, one
  near-leak, and three costs nobody had flagged — all fixed or filed in `#132`.
- **A time bomb was defused before it shipped.** An earlier PR in this stack made the
  reconciler fail a commit when the roadmap's date was over 30 days old. That check runs
  in pre-commit and CI, so from 2026-08-31 every commit in the repo would have failed
  until somebody re-dated a planning document. Malformed roadmaps still gate; age is now
  a report-only gardener routine that blocks nothing.

## Where things stand

- **All eleven public PRs are open and green, none merged.** Merge them **bottom-up,
  `#122` first**, one at a time.
- **Expect `main`'s CI to go red after each merge.** A review-ledger row names a branch
  tip, and squash-merging plus re-targeting the next PR gives every commit a new SHA, so
  the rows are orphaned by construction. The recovery is documented step by step in
  `skills/github-workflow/SKILL.md` under "After merging a stack, on the trunk": never
  edit an orphaned row, append one reconciliation row using the range the gate prints.
  This is a known cost of stacking here, not a regression.
- **Deliberately not done: the `examples/` reshape** (workspace phase 8). It is fully
  measured and its instruction-only half has landed, but every remaining piece renames or
  deletes a published path in a public repo. Seven owner calls are filed as one queue item.
- **Deliberately descoped: phase 7c's durable/disposable machinery.** On the evidence it
  was built for a degradation nobody has observed, and it would rename 126 files. Only the
  one live defect is worth fixing; the queue item asks whether you agree.
- `skills/company-research/SKILL.md` is at **568 of its hard 600-line budget**. The budget
  gate now prints `NEAR` with the remaining count, so the next editor meets it. Treat the
  next substantive edit to that file as a consolidation pass.

## Needs your attention

- [`examples-reshape-seven-calls.md`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)
  — seven calls the `examples/` reshape cannot make on its own (a rename of published
  paths, a deleted directory, three new fixtures, one generator behaviour change). One
  item, each with a recommendation; answer all seven or none, because the first names the
  files the rest move. Default while pending: nothing moves.
- [`company-detector-over-the-skills-tree.md`](../../../message-queue/needs-human/decisions/company-detector-over-the-skills-tree.md)
  — a public skill file named a real company that is not in the public registry. Redacted.
  Should the review gate's company detector also read `skills/**`, not only diffs? Default:
  leave it diff-only.
- [`phase-7c-descope-to-the-one-live-defect.md`](../../../message-queue/needs-human/decisions/phase-7c-descope-to-the-one-live-defect.md)
  — build the durable-marker machinery, or fix only the live defect? Default: descope.
- [`process-weight-what-to-cut.md`](../../../message-queue/needs-human/decisions/process-weight-what-to-cut.md)
  — which process machinery earns its keep. One argument inside it is now stale and says so.
- Eight further items were already open before this session
  (`message-queue/needs-human/decisions/`, plus one in `reviews/`); none was answered here
  and none is blocking.
