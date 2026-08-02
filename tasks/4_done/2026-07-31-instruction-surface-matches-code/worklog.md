# Worklog — 2026-07-31-instruction-surface-matches-code

## 2026-07-31 — session 1 (agent)

- Re-verified all six items against the branch before touching anything. Two of the source
  audit's claims had moved under it: the gate table's omission is still real, but four of the
  gates it describes as hook-only now also run in CI (PR 03 of this stack), so the table needed
  a hook/CI column rather than one extra row. And the config-defaults PR earlier in this stack
  already made `skills/job-search/profiles/README.md`'s "default `private/market/searches/`"
  claim true — `config.search_profiles_dir()` now derives `<overlay_root>/market/searches`, so
  that finding was already fixed and is not re-fixed here.
- **Did not touch `examples/`** (out of scope by instruction) and did not touch any
  `config.py` default.
- Three findings from the plan's PR-1 list turned out to be **correct as written** and were
  left alone: `docs/handbook/architecture.md`'s applications tree already labels `0_profile/`
  and `1_discoveries/` "(not an application)"; `docs/handbook/application-folders.md`'s status
  TABLE already lists only the five status folders (only its numeric-prefix paragraph needed a
  clause); and `skills/github-workflow/SKILL.md` §2 already stated that CONTRIBUTING's
  no-stacking rule is contributor-facing, so only the CONTRIBUTING side was missing an audience.
- The manifest-sync "gap" is not a gap. `_managed_links()` skips non-symlinks by design and
  says so, with a test; the same rule is what stops a sync from deleting the git-ignored
  runtime links into `private/skills/`. No check added — the test fixture was renamed instead,
  because it used this repo's own retired skill name as its "third-party" stand-in.
- Filed `tasks/0_backlog/2026-07-31-answer-bank-renders-company-answers-into-the-question-bank/`
  for the one live code defect this touched but must not fix here: `answer_bank.py --render`
  still writes company answers into the question bank. The skill now states the gap instead of
  claiming a location that is only half true.
- Re-checked `message-queue/needs-human/decisions/story-bank-keeps-its-leaf-name.md` before
  committing the design-doc edit that relies on its default path. Still `awaiting-owner-input`,
  default path unchanged, and the item itself costs the edit as "one word changed in three
  places". Flagged in the PR body.
- Next: nothing outstanding in this task. The behavioural half (the `answer_bank.py` routing)
  is the filed backlog item and needs an owner OK before it lands.
