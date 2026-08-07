# Worklog — 2026-08-06-private-overlay-personal-taxonomy

## 2026-08-06 — session 1 (Codex `/root`)

- Claimed the refactor, read the previous workspace-taxonomy decisions, and split read-only investigation across private-content inventory, path-impact tracing, and Git/PR design.
- Found unrelated uncommitted changes in the mounted private checkout; the private migration will use a separate worktree so those edits remain untouched.
- Next: settle the destination map, implement both repository changes, verify move fidelity, and open both PRs.

- Settled the person-first target: `me/{career,applications,interviews}`, with the company
  identity index under `market/` and outreach copy under career communications.
- Public code, fictional examples, active documentation, tests, and path canaries now use the
  target shape. The isolated private worktree has 3,201 mapped moves plus live-reference edits.
- Exact private Git mode/blob comparison passed for all mapped files; the mounted dirty private
  checkout's unrelated work remains untouched.
- Preserved the divergent legacy `data/` root and filed a store-aware reconciliation task after
  proving it contains unique newer state.
- Committed the private migration in eleven guard-approved batches; no batch exceeded 500 files
  or 128 MiB. The largest was 369 files / 115,835,881 bytes.
- The first config-less run found five missed hardcoded test paths. Fixed them in a focused public
  follow-up commit, then reran the complete suite outside the sandbox for LibreOffice access.
- Final public result: 29/29 gates green. Public PR #321 and dependent private PR #93 are open;
  every reported public GitHub check passed, while the private repository reports no CI checks.
- The mounted private checkout's unrelated tracked patch and untracked handover retained their
  exact starting hashes. The ignored local config remains deliberately unchanged until merge.
