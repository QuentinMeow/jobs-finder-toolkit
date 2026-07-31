# Worklog — 2026-07-28-workspace-phase-5-lifetime-taxonomy

## 2026-07-30 — session 1 (agent)

- Reconnaissance first, and it changed the phase. Three findings would each have
  produced a migration that looked finished and was not:
  1. **The link checker could never have verified this phase's own repair step.** It
     enumerates with `git ls-files` in the *public* repo, so no file inside the overlay
     had ever been opened; `SKIP_PREFIXES` filters tokens named in public docs, not
     which files are read. Fixed in the preceding PR, which is why that one was made a
     blocking precondition.
  2. **33 `source_stories` references would have hard-failed the answer bank**, and the
     obvious repair is a content edit inside files the owner's ruling said not to alter.
     Resolved by keeping the leaf directory name instead of the plan's spelling — zero
     content edits, all 33 resolve.
  3. **Splitting the card/log accessors could have corrupted live data.** The benchmark
     config isolates every derived write solely by redirecting `applications_root`;
     re-deriving the three new keys from a `me`/`market` root would have pointed a
     benchmark run at the real tailoring card and the real skip-log. The new keys
     default to the OLD derivation for exactly this reason.
- The migration script was **generated from a validated path map, not hand-written**,
  and a third script replayed it as virtual index renames and diffed the result against
  the map before anything ran. 747 moves, 103 `git mv`, 32 commits.
- **Per-company commits turned out to be load-bearing, not stylistic.** The overlay's
  pre-commit hook refuses a commit over 128 MiB of staged blobs and a rename stages the
  whole blob; the 25 company folders together come to ~128.6 MiB.
- Two counts in the task file were wrong and are corrected: 825 → **747** (825 counted
  `history/` plus 55 files whose paths do not change), and the ~244 interview links →
  261.
- `--require-roots`, added the previous PR, caught a stale constant in this one on its
  first real use. That is the disarm class this whole design exists to close, and it
  fired unprompted.
- One near-miss worth recording: an early command ran without `git -C` while the shell's
  working directory had persisted from an earlier call, and put two empty commits in the
  private repo. Recovered in one command from the `pre-phase-5-snapshot` tag taken ten
  minutes earlier. **Tag before a migration; use `git -C` always.**
- Next: phase 6 (the skip-log stops being derived), then 7 and 8. Phase 5 makes deletion
  *look* safe while phase 6 is outstanding, so 6 should not wait long.

## 2026-07-30 — session 2 (agent)

- The owner resolved the last untracked interview-tree exception: the coding
  interview screenshot inbox moved into `private/me/interviews/practice/TODO/`.
- The inbox contained one screenshot. Its SHA-256 matched before and after the
  directory move, and the former inbox path no longer exists.
- Both private consumers now poll the new path. The `.agents`, `.claude`, and
  `.cursor` runtime adapters all expose those updated canonical skill files; no
  copied instruction file needed a separate edit.
- The pending queue item was folded into a permanent decision record, the phase-5
  move table, and the current-state roadmap, then removed.
- Canary suites were skipped because both `SKILL.md` edits are mechanical
  one-line path substitutions with no behavioral, prompt, or control-flow change;
  stale-reference and adapter sweeps cover the risk directly.
- The mounted-overlay link gate surfaced nine unrelated findings. The private
  references were repaired, and a public parser fix prevents blank Markdown
  headings from changing the following heading's anchor. All 69 verifier tests
  and the full mounted-overlay check now pass.
