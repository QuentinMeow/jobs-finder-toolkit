# Worklog — 2026-07-28-workspace-phase-2-public-cleanup

## 2026-07-29 — session 1 (agent)

- Landed the phase as five stacked PRs: the three-way split of `automation/maintenance/` (38
  files), the `docs/` consolidation (135), the `evals/` absorption (30), the `tmp/` → `local/`
  rename (45), and this record. Each PR is one move commit, one literal-sweep commit, and a
  ledger-only commit to close the branch green.
- The plan's rule 3 — every `git mv` in its own commit — turned out to be unexecutable for the
  `roadmap/` move. The pre-commit hook runs the reconciler with `--require-roots`, which asserts
  the root exists, so a move-only commit could not be created at all. The move and the constants
  naming it had to land together; `--follow` survives that anyway. Rule 3 now carries the
  correction.
- The plan's constants table was incomplete in a way a regex could not catch: a test fixture
  carried a bare `"roadmap"` with no trailing slash inside a `make_roots(skip=…)` tuple. Left
  alone it would have kept the test green while silently changing what it tested.
- Two other spelling traps, same shape: four files name `automation/maintenance` as a bare word
  in prose (one of them the handbook, citing it as an example of a *good* folder name), and every
  runtime scratch write path spells the root as a bare quoted `"tmp"` segment rather than `tmp/`.
  Nine of those. A `tmp/` sweep finds none of them, and the scripts would have kept recreating
  `tmp/` beside `local/`.
- Proved the silent-disarm case rather than trusting the green gate — and the proof turned up the
  real find of the phase. `verify_links.py` reports a planted broken ref under `docs/handbook/`
  and stays silent on the identical ref under `handbook/`, because a ref matching no strict root
  prefix is dropped without being counted. 76 such refs now exist across 24 record files. The
  same checker has never looked at `[text](path)` links at all; 31 are broken right now.
- **What surprised me:** the gate said "references: all resolve" through the entire phase, while
  a checker written in ten minutes found 36 broken markdown links at the base and 31 at the tip —
  with zero overlap between the sets. Two of the phase's four plan corrections were only findable
  by grepping for a *spelling* of a path rather than the path, and the biggest defect was only
  findable by not believing a green run.
- Next: the stack merges bottom-up; this task moves to `4_done` when it does.
