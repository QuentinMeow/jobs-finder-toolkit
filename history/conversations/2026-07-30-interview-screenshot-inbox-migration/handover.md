# Handover — coding interview screenshot inbox migration

- **Date**: 2026-07-30
- **Task(s)**: 2026-07-28-workspace-phase-5-lifetime-taxonomy

## What happened

- The owner chose `private/me/interviews/practice/TODO/` as the coding interview
  screenshot inbox.
- The existing untracked inbox moved intact, and both private consumers plus all
  runtime adapters now resolve the new path.
- The pending choice was folded into the workspace design, roadmap, and
  `memory/decisions/interview-screenshot-inbox-moves-to-personal-practice.md`.

## Where things stand

- The private skill update is committed on a dedicated PR branch. The full link
  gate initially found nine unrelated overlay-reference failures; all nine were
  repaired, the queued retry was closed, and the mounted-overlay check now passes.
- Six of those findings exposed a public verifier bug: blank Markdown headings
  could be fused with the next real heading. The parser now restricts heading
  whitespace to spaces and tabs, with regression coverage.
- The former inbox path is absent; the screenshot's checksum is unchanged at the
  new location.
- Skill canaries were skipped because the edits only replace one literal path in
  each private `SKILL.md`; direct stale-reference and adapter checks cover the
  changed surface.

## Needs your attention

- [History tracking](../../../message-queue/needs-human/decisions/history-untracked-in-phase-5.md):
  decide whether the workspace history tree remains tracked.
- [Private reconciler scope](../../../message-queue/needs-human/decisions/private-scope-reconciler.md):
  decide how reconciliation should cover the overlay.
- [Public history privacy](../../../message-queue/needs-human/decisions/public-history-privacy-rewrite.md):
  choose the privacy treatment for public history records.
- [Retired applications log](../../../message-queue/needs-human/decisions/retired-applications-log-yaml.md):
  decide the old YAML log's final treatment.
- [Story-bank leaf name](../../../message-queue/needs-human/decisions/story-bank-keeps-its-leaf-name.md):
  confirm the already-implemented leaf-directory spelling.
- [Workspace restructure review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md):
  the existing plan review remains open.
