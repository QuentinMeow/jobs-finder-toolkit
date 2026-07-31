# Worklog — 2026-07-30-ci-runs-the-promised-gates

## 2026-07-30 — session 1 (agent)

- Reproduced CI's shape with `git worktree add --detach <scratch>/ci_wt HEAD`:
  no `config.yaml`, no `private/` overlay, only `config.example.yaml`. Ran every
  candidate step there before adding it to `ci.yml`. Nothing failed, so no step
  had to be dropped or reshaped.
- Only `skills/application-tracker/scripts/tests` reads config (applications
  root, location policy, skip-log paths); the other three suites do not. Pinned
  `JOBHUNT_CONFIG` on that line only, the way steps 3/4/6 already do.
- Finding 4 decided in favour of extending the measurement rather than shrinking
  the docstring: `AGENTS.md` leaves are exactly the file class the anti-bloat
  gate exists to bound, and the tree-instructions design already specifies the
  tier (≤100 lines AND ≤4 KiB). Only one leaf exists today
  (`docs/designs/AGENTS.md`, 8 lines / 514 bytes), so nothing newly fails.
- Left the router-table discovery and the 32 KiB chain budget with
  `tasks/0_backlog/2026-07-21-tree-instructions-validator/`, and appended a note
  there recording what landed early.
- Cost of the change, measured on the PR's own run rather than guessed from the
  laptop: the four suites take 15 s on the runner and the two gates 1 s, against
  73 s for the same four suites locally. The local number over-estimated by ~4x;
  the PR description carries the CI one.
