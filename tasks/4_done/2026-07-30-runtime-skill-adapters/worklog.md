# Worklog — 2026-07-30-runtime-skill-adapters

## 2026-07-30 — session 1 (Codex)

- Confirmed Codex currently sees only the tracked public `skills/` tree while
  Claude Code and Cursor use per-skill adapters.
- Chose one per-skill adapter model for all three runtimes, with overlay names
  held only in local Git exclusion metadata.
- Began implementation and current-tree privacy cleanup.
- Implemented and exercised the three runtime adapter trees: each resolves 11
  tracked public adapters plus the mounted overlay set, and local Git status does
  not expose the overlay adapters.
- Added dynamic leak-token derivation from mounted overlay skill directories and
  scrubbed their identifiers from the current tracked public snapshot.
- Eval gate: skipped — the `ask-me-anything` edit is a small privacy-only wording
  change with no workflow or routing behavior change.
- Full gates found one empty obsolete history directory after a privacy rename;
  removed that empty directory and re-ran the reconciler.
- History rewrite is intentionally out of scope and filed as an owner decision;
  default is the non-destructive current-tree and future-commit cleanup.
- Closing review added removal coverage: when an overlay skill disappears,
  bootstrap removes only its generated adapters and prunes their local excludes,
  while preserving foreign runtime entries.

## 2026-07-31 — session 2 (agent, bookkeeping)

- Recorded the missing PR reference. The definition of done's last bullet asks for an open public
  pull request, and no file in this folder named one. It is **PR #121, "Make overlay skills private
  across all runtimes"**, confirmed `MERGED`. Without that line the folder's final box could not be
  checked by anyone reading it.
- Moved `3_in-review` -> `4_done` on that evidence. Nothing else in the folder changed.
