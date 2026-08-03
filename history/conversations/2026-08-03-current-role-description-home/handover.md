# Handover — current-role-description-home

- **Date**: 2026-08-03
- **Task(s)**: none

## What happened

- Nothing in flight or broken; a mis-filed personal paste file was relocated.
- Current-job ATS-form copy now lives under `me/` with the other paste templates,
  not under `market/` (scans) or `applications/` (per-req).

## Where things stand

- Public and private branches opened as PRs for this session's local work.
- Public: folder-purpose wording in overlay handbook + design tree.
- Private: file home under `me/…/common-message-replies/` plus the other local
  overlay edits from this checkout.

## Decisions made for you

- Home = `me/interviews/common-message-replies/current-role-description.txt` —
  permanent candidate paste content; same bucket as outreach/targeting templates.
  Undo cost: another `git mv` plus pointer rewrites.
- Renamed off the employer-prefixed filename so the path stays stable when the
  blurb changes. Undo cost: rename only.

## If X then Y

- If you want a config accessor for this path later, add it then — today nothing
  in code reads the file.

## Dead ends

- None.

## Needs your attention

- Nothing new from this session. Pre-existing queue still open (see reply
  standing line).
