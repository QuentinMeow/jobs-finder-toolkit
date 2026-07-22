# Tree-instructions validator + budget/exporter integration

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: design/tree-instructions/README.md (2026-07-21, respecced
  after adversarial review)

## Goal

Machine-enforce the tree-instructions convention (per-folder `AGENTS.md`
leaves + `CLAUDE.md` shims + root router), and close the two exporter gaps
the review found. Wired into pre-commit next to the existing checks.

## Context

The adversarial review showed the v1 spec was unimplementable as written;
this is the corrected spec.

Validator checks:

1. **Path existence** — every path mentioned in a leaf `AGENTS.md` or
   `agents-references/*.md` exists. Paths in leaves are declared
   **repo-root-relative** (the convention the seeds now follow); the
   checker resolves them from repo root only, no heuristics.
2. **No orphan references** — every `agents-references/*.md` is pointed at
   by **at least one** (≥1, not exactly one) task-conditioned line in its
   folder's `AGENTS.md`.
3. **Shims + router** — every leaf `AGENTS.md` has a sibling `CLAUDE.md`
   symlink to it, and a router line in root `AGENTS.md` → "Folder-Scoped
   Context" (machine-parseable format defined there). Routed folders absent
   from the checkout (e.g. `message-queue/` in public exports) are skipped, not
   failed.
4. **Budgets** — leaf ≤100 lines AND ≤4 KiB; the **AGENTS.md chain only**
   (root + every AGENTS.md on the path to the deepest leaf) ≤32 KiB —
   pointer targets are agent-initiated reads and never count.
5. **Symlink integrity** — every tracked `CLAUDE.md` symlink resolves
   inside the repo; a broken or outside-repo symlink is a hard failure
   (today `check_public.py` fails OPEN on broken symlinks — close that).

`instruction_budget.py` integration is a real schema change, not a two-line
edit: budgets become keyed by (role, path-pattern) instead of bare
filename (root `AGENTS.md` ≠ leaf `AGENTS.md` budgets), a bytes column is
added, and leaf discovery derives from the root router table (single source
of truth) instead of a tree walk.

Exporter (`scripts/publish/export_public.py`) gaps:

- `_copy_tree` follows symlinks, so an exported `design/CLAUDE.md`
  becomes a duplicated regular file (a drift bomb). Extend
  `_regenerate_symlinks` to recreate leaf shims from the router table.
- Decide/implement `message-queue/` handling in exports: either allowlist the queue
  READMEs (leak-clean) so the exported AGENTS.md router/ritual lines point
  at something real, or keep the existing skip-if-absent gating as the
  answer (the ritual and router lines are already existence-gated).

Gardener: stale-leaf report via **git commit-churn ratio** (leaf commits vs
folder commits since leaf's last change), with a whitelist for deliberately
stable leaves (e.g. `design/` churns weekly by design while its style
leaf should not).

## Definition of done

- [ ] Validator green in pre-commit and CI on the current tree.
- [ ] Each planted defect fails with a message naming the fix: orphaned
      reference file, missing shim, missing router line, over-budget leaf,
      broken symlink.
- [ ] `instruction_budget.py` reports leaf files under their own budgets
      (roles keyed by path-pattern, bytes column present).
- [ ] Export of a tree with a leaf shim contains a working symlink (or
      regenerated equivalent), not a duplicated file.
- [ ] Gardener stale-leaf report runs dry-run on the real tree.
