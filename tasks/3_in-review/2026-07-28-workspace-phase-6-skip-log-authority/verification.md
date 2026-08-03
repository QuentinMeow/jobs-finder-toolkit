# Verification — 2026-07-28-workspace-phase-6-skip-log-authority

Every command below was run on 2026-07-30 against the branch
`feat/02-skip-log-authoritative`. No command in this file resolved a path under
`private/` — the acceptance proof ran against a `cp -R` copy in the gitignored
scratchpad with `JOBHUNT_CONFIG` pinned, and the isolation was proved by printing
every resolved accessor before anything ran.

## Unit suites

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 365 tests in 14.611s
OK

$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 68 tests in 14.479s
OK

$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
Ran 326 tests in 11.469s
OK

$ .venv/bin/python -m unittest discover -s automation/search-recall-audit/tests
Ran 9 tests in 0.022s
OK

$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python -m unittest discover -s automation/gardener/tests
Ran 83 tests in 19.693s
OK (expected failures=1)
```

`automation/search-recall-audit/` had no suite and no CI step before this change; the 9
tests and the CI step are new. The gardener's one expected failure predates this work and
is untouched — flagged in `tasks/4_done/2026-07-30-skill-drift-test-reads-the-real-profile`
(it was in `3_in-review` when this was written; pointer re-pointed 2026-08-02).

## The full CI-equivalent gate

8 gates, 11 unit suites, strict export dry-run:

```
PASS  vendor-drift        PASS  tests:reconcile     PASS  tests:job-search
PASS  byte-compile        PASS  tests:gardener      PASS  filter-variants
PASS  reconcile           PASS  tests:hooks         PASS  tests:app-tracker
PASS  leak-guard          PASS  tests:shared        PASS  tests:github-wf
PASS  review-gate         PASS  tests:publish       PASS  export-strict
PASS  instruction-budget  PASS  tests:store-example
PASS  verify-links        PASS  tests:resume-writer
PASS  mail-safety

ALL GREEN
```

Two gates caught real defects during this work rather than passing them through:

- **`tests:publish`** failed on `CIPathsExistInExportTests`: the new CI step invoked
  `automation/search-recall-audit/tests`, a path the public export did not ship, so the
  *exported* repo's CI would have gone red. (Cause: the new test files were untracked and
  the exporter ships tracked files only.)
- **`reconcile`** refused `3_in-review` without this verification file.

## Mutation checks — the tests fail when the code is wrong

Green tests prove nothing unless they can go red. Two deliberate defects were planted and
each turned the intended test red:

- Reverting `handoff._applications_jsonl`'s `--applications-root` override branch to
  `APPLICATIONS_LOG_FILENAME` → the two new end-to-end override tests fail
  (`duplicate: 0 != 1`). This is the fail-open the design flagged: the override would read
  a non-existent file and the duplicate preflight would silently degrade to
  live-folders-only.
- Making `load_considered` derive a URL key *else* a pair key (instead of both) → both new
  `PairKey` tests fail. Before this change the whole `test_skip_identity.py` suite was
  blind to that regression, because its fixture wrote `url: ''` on every row.

## Acceptance proof — the green gate

Run against a `cp -R` copy of the owner's applications and market logs in the scratchpad,
with `JOBHUNT_CONFIG` pinned to a scratch config. Recorded separately below by the agent
that ran it; see the worklog for the sequence. The proof has two halves, and the second is
the one that matters:

1. Seed the copy, confirm a rejected application's posting is skipped, **delete that
   application folder**, re-run `--sync-log`, confirm the posting is **still** skipped.
2. Reconstruct the OLD writer's behaviour on the same post-deletion copy (regenerate a
   YAML log from the folders the way `sync_log()` used to) and confirm the same check now
   returns **False**. A proof that passes under both the old and the new code proves
   nothing.

### Isolation, proved before anything ran

All **19** zero-argument `Path`-returning accessors `config.py` exposes were enumerated
and every one resolved inside the scratchpad — not the nine the task named.
`find private -newermt '-2 hours'` afterwards returned nothing; no `applications-log.jsonl`
was created there; the three log files kept their original sizes and mtimes; all 243
application folders still present.

### Backfill arithmetic

| | |
|---|---|
| YAML rows on the copy | 369 (367 with a URL, 2 without) |
| Folders / `jobs:` entries | 243 / 369 |
| Events appended by `--backfill-log` | **369** |
| Resulting fold | **369** — matches |

The folded rows are identical field-by-field to the YAML rows across all six posting keys,
so the format switch changes nothing any reader sees.

### The acceptance proof

Victim: a `3_rejected` folder with one URL-bearing posting.

| Step | Result |
|---|---|
| `already_considered()` before deletion | **True** |
| folder deleted (243 → 242), `--sync-log` re-run | exit 0, **0 events appended**, fold still **369** |
| `already_considered()` after deletion + sync | **True** — the row survived |

**Non-vacuity, on the same post-deletion copy.** The old `sync_log()` was reconstructed
(`build_log(collect_apps())` → `yaml.safe_dump`) and the real reader pointed at it by
swapping only the row source — the exact one-line diff, reverted. The regenerated YAML
held **368** rows, having lost exactly the victim's row, and `already_considered()`
returned **False**. The proof fails under the old code and passes under the new.

### Round trip

`--sync-log` twice with no changes appends 0 both times. `--update <slug> in_progress`
appends exactly 1 event (`source: "update"`), moves the folder, leaves the fold size
unchanged, and a follow-up `--sync-log` appends 0 — the two writers agree on the row
shape. `--forget-log` on a folded posting shrinks the fold by one and flips
`already_considered()` to False; on an unfolded key it exits 1 without appending.
`--backfill-log` refuses a second seed and accepts `--force`.

### Two silent-revert bugs the proof found, both fixed here

The proof ran one assertion that did **not** hold, and isolating it on four independent
copies surfaced a second, worse case. Neither is a defect in the append-only mechanism;
both are commands quietly undoing a decision the owner made by hand.

1. **`--backfill-log --force` resurrected every `--forget-log`.** The re-seed reads the
   retired YAML, which still contains every tombstoned row and is never updated again, so
   a later line won the fold and the un-skip was reversed — reported only as "seeded N
   events". Fixed: `skip_log.forgotten_keys()` reports keys whose last event is a
   tombstone (`fold()` drops them, so it cannot tell "forgotten" from "never seen"), and
   the re-seed skips them and says how many it kept.
2. **`--sync-log` reverted a tombstone whose folder still existed.** `--forget-log`
   printed success and the very next sync rebuilt the row from the folder. Fixed:
   `--forget-log` now **refuses** while a live folder backs the key, naming the slug and
   its status — a live folder is live evidence the posting was handled, so the thing to
   fix is the folder. Same principle as the existing refusal on an unfolded key: an
   un-skip that quietly does nothing is worse than an error.

Both fixes carry tests (`test_a_forgotten_posting_is_not_resurrected_by_a_force_reseed`,
`test_forget_log_refuses_while_a_live_folder_still_backs_the_key`). Two pre-existing tests
forgot a posting whose folder was still live; they were rewritten to delete the folder
first, which is the real shape of an un-skip.

### Reader sweep

Against a copy holding a tombstone and a deleted folder — fold 368, **371 raw lines**, so
a reader that counted lines instead of folding would be visibly wrong:

| Reader | Result |
|---|---|
| `self_measure._discovered_count` | 368 — folds, does not count lines |
| `audit.build_coverage` | 368 log entries, one per folded key, no triplication |
| `store_refilter.build_covered` | 366 URLs / 368 pairs — **non-empty**; it was empty on every run before the fix |
| `handoff._posting_keys` | 366 URLs / 368 pairs; the `--applications-root` override composes the `.jsonl` name, not the old YAML |

### Size and growth

The seeded JSONL is 117,073 bytes against the YAML's 89,831 (1.30x, ~317 bytes/event).
At the corpus's observed status mix (~1.8 events per posting over its lifetime), ordinary
use — ~120 new postings/yr — adds **240–360 lines/yr, ~75–110 KiB/yr**. A sustained heavy
month like the one in the corpus would reach ~7,900 lines/yr (~2.4 MB/yr), which is still
trivial for a git-tracked plaintext file but is an order of magnitude above the "a few
thousand lines over the toolkit's life" the plan assumed. No compaction is needed at
either rate — and building one would restore the truncation this phase removes.
