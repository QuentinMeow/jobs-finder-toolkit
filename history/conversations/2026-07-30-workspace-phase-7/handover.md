# Handover — workspace phase 7

- **Date**: 2026-07-30
- **Task(s)**: [2026-07-28-workspace-phase-7-company-key](../../../tasks/3_in-review/2026-07-28-workspace-phase-7-company-key/task.md) · [2026-07-28-company-key-assignment-approach](../../../tasks/4_done/2026-07-28-company-key-assignment-approach/task.md) (closed)

## What happened

- **Every company string an application carries now resolves to exactly one employer** — 214 of
  214, against the public resolver's 119. That gap was the whole reason phase 7 exists.
- **The plan's premise was wrong, and that changed the work.** It reads as though the 44% the
  resolver misses is spelling drift a better alias table would fix. It is not: ~85% of it is
  employers structurally absent from a *polling* registry that only holds companies with a
  supported ATS token. So "retire the other three alias registries" was never implementable, and
  none were retired — each is kept for a recorded reason. Four of the plan's five headline counts
  were also stale.
- **A leak detector that had never once run is now running.** The review gate has always read
  `companies/_index.yaml`; the file never existed, so it printed `NOT INSPECTED` and checked
  nothing. It now loads 265 names, at a measured 0.2–0.6s per commit.
- **It immediately caught me.** The verification file in the public PR originally pasted a linter
  run verbatim, naming seven of your employers in a public file. The detector fired on exactly
  those seven and forced human review. The commit was reset rather than fixed forward, so the
  leaking version never entered pushed history. Recorded in the file rather than quietly repaired:
  the leak was written by the agent that had spent the session calling this the highest-leak-risk
  phase, into the file whose own opening line promises no company names appear in it. The
  staged-index leak guard would not have caught it — company names are not identity tokens.
- **A second leak vector was found and closed without being asked for.** `--file-retries` writes
  *tracked* files whose bodies repeat a finding's subject; the new check's subjects are application
  paths and company keys, and `AGENTS.md` tells agents to let it queue findings. One run would have
  committed an application slug into the public tree.
- Three separate versions of one small lint rule were wrong and each was killed by measuring rather
  than arguing — including a stop-list that would have *blinded* the new detector to 149 names.

## Where things stand

- **Three PRs open, none merged.** Public #117 (the contract, the reconciler check, the record) and
  #118 stacked on it (schema validation, the readers, a `--company-keys` coverage report), plus the
  overlay's PR holding the index itself. Merge the public pair bottom-up, #117 then #118. The public
  half is designed to merge alone — every new path no-ops without the overlay — and merging it first
  is what arms the tooling that validates the private half.
- **Two defects in existing code were found on the way and filed, not fixed here.** The shared test
  suite has been importing *vendored copies* rather than the modules it claims to test (harmless
  only because a different gate keeps them byte-identical), and `job_metadata.py` still holds a
  `_company_key` helper meaning something else entirely — the same collision the mail rename just
  removed, now sitting in the file that defines the validator.
- **No company folder was renamed.** One slug rule reproduced all 25 existing names exactly.
- **Phase 7 is deliberately not finished.** Two pieces were split out rather than rushed:
  [7b](../../../tasks/0_backlog/2026-07-31-workspace-phase-7b-company-key-on-meta/task.md), the
  `company_key` pass over 243 `meta.yaml` files, and
  [7c](../../../tasks/0_backlog/2026-07-31-workspace-phase-7c-durable-timeline/task.md), the email
  assistant's `durable:`/`promote` work and the 126 `notes.md` renames.
- Branch cleanup at the start of the session removed four merged branches across both repos;
  nothing else was stale.

## Needs your attention

- **[Seven judgement calls on the company index](../../../private/message-queue/needs-human/decisions/company-key-index-seven-calls.md)**
  (in the overlay) — an interview vendor that is not an employer, a joint venture sharing a brand,
  an acquired product applied to on the acquirer's board, two rebrands, three legal suffixes with
  no second spelling to compare against, and four company folders with no application behind them.
  **Every default is already applied**, so saying nothing is a valid answer — but 7b is held until
  you answer, because settling keys before 243 files point at them is far cheaper than re-pointing
  them afterwards.
- **[The retired `applications-log.yaml`](../../../message-queue/needs-human/decisions/retired-applications-log-yaml.md)**
  from phase 6 is still unanswered — the old skip-log is read by nothing now; delete it or keep it.
  While it exists it stays a resurrection source for rows you later un-skip.
- The four decisions open before this session are unchanged: `history/` untracking, the story-bank
  leaf name, the coding-interview screenshot inbox, and the two parked ones
  (`private-scope-reconciler`, `logs-as-store-projections`).
- **Task-tracker drift I did not sweep**: five folders in `tasks/3_in-review/` have merged PRs, but
  at least one (`2026-07-28-workspace-phase-5-lifetime-taxonomy`) still has every definition-of-done
  box unticked, so moving it would assert evidence nobody gathered. I closed only the one I could
  verify in a single command. Your call whether to sweep the rest.
- **Eight broken anchors** in a private story-bank file imported from a Google Doc (`#bookmark=id.*`
  and anchors containing `/` and `:`). Overlay-only — the CI form of the link checker is clean.
  Your document, so not mine to rewrite.
