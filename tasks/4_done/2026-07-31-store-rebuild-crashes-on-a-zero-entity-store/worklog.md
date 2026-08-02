# Worklog — 2026-07-31-store-rebuild-crashes-on-a-zero-entity-store

## 2026-07-31 — session 1 (agent)

- Picked up alongside the `--opinions-only` P0: same module, same invariant (a build
  path must not leave store data unreachable), and the two shapes meet on a checkout
  that holds only the committed index.
- Fix is two lines in `build_rebuild`: create `derived.building` / `index.building`
  up front instead of relying on the first entity write to create them. `_swap_dir`
  is unchanged — its two-rename window is correct; what was wrong was calling it with
  a directory that might not exist.
- Found a third reachable shape the filed task did not list: a raw-less,
  derived-less checkout (the durable floor's own scenario) also materializes zero
  entities, so `--rebuild` could not run there at all. Covered by a test.
- Next: review. Nothing pending on this task.
