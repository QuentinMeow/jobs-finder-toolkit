# Worklog — 2026-07-31-four-gates-that-inspected-nothing

## 2026-07-31 — session 1 (agent)

- Read `check_symlinks()` first and copied its shape rather than inventing four
  different ones: "verified nothing" is a finding, phrased in the finding text.
- **What surprised me (1):** the review gate could not be fixed with a flag. The
  exported mirror runs the same tracked hook and CI workflow this repo does, so
  `--allow-not-applicable` in those invocations would have disarmed the maintainer
  checkout too. The discriminator had to be the tree's SHAPE — which is the idiom
  `reconcile.CHECK_ROOTS` and `verify_links._present_strict_prefixes` already use.
- **What surprised me (2):** widening the link checker looked free and was not.
  The four roots phase 2 retired account for ~72 of the 729 invisible refs and all
  but one sit in plan or record documents. The exception, `docs/roadmap/current-state.md`,
  names `tmp/` inside the sentence explaining that `tmp/` was renamed to `local/`.
  A reference doc naming a retired root is usually naming it BECAUSE it is retired,
  so the widening buys one false positive and no true ones. Rejected with numbers.
- **Real failure the stricter gates surfaced:** two fixtures in
  `TestRootDisappearance` modelled a tree whose only reference was the unresolvable
  one, so they verified nothing and the new coverage finding fired. Each gained a
  second, resolving ref — they are about a missing root, not a corpus with no
  coverage. Nothing was weakened.
- Next: nothing outstanding on this task. `--allow-not-applicable` has no caller;
  it exists for a mirror that ships the process roots.
