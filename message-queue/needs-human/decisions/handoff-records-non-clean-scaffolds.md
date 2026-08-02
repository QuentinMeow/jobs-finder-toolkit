# Should handoff record a posting whose scaffold came out incomplete?

- **Status**: folding
- **Filed**: 2026-07-31
- **Source**: [handoff.py creates application folders without recording the posting in the skip-log](../../../tasks/3_in-review/2026-07-30-handoff-does-not-record-created-postings/task.md)
- **Blocks**: nothing
- **Default path**: `handoff.py` records **every** posting whose folder it actually
  created, whatever exit code the run returns — including the location-mismatch exit (3)
  and the incomplete-scaffold exit (1, a failed or skipped JD fetch, or metadata gaps). On
  a non-zero exit it prints the `--forget-log` command, with the URL already filled in, so
  the un-skip is one copy-paste away. Nothing is recorded when no folder was created.
- **Cost if wrong**: data
- **Safe to merge because**: it is NOT cheaply reversible — the default appends permanent rows to
  the append-only, authoritative `applications-log.jsonl`, and the only undo is the owner running
  `status.py --forget-log <url>` per row, which `handoff.py` prints on every non-zero exit. This
  is the weakest default in the queue.

## Background

`handoff.py` now appends each posting it scaffolds to the append-only skip-log
(`applications-log.jsonl`) as the last step of building the folder. Before that, only
status *transitions* were recorded, so a folder created and deleted before any
`--sync-log` left no trace and the next search re-surfaced the posting as fresh.

That fix has one edge the code cannot decide on its own. `_run_group` returns three
things:

- **0** — clean scaffold.
- **3** — the posting's location is outside `config.location_policy()`. The folder is
  left on disk on purpose, and the tool prints "delete the folder, or rerun with
  `--allow-location-mismatch`".
- **1** — the folder exists but is not draftable: `--skip-jd-fetch` was passed, the JD
  fetch failed, or `meta.yaml` still has gaps.

In both non-zero cases **the folder exists**. So: is that posting "considered"?

What makes this the owner's call rather than an agent's: the skip-log is append-only and
authoritative. Recording a posting is permanent. If a `--skip-jd-fetch` scaffold is
deleted five minutes later, the posting stays skipped forever unless the owner runs
`status.py --forget-log` by hand. There is no self-healing path, by design — that is the
same property that makes the log worth having.

## Options

### Option A — record every created folder (the default path)

One rule, no exceptions: a folder on disk means the posting was considered.

- Matches what the rest of the pipeline already does with these folders. `_run_groups`
  calls `_register_row` for every created folder regardless of exit code, and the
  live-folder half of `_posting_keys` reads `6_drafted` without looking at how the run
  exited. Under Option B the log would be the only component in the pipeline that treats
  a mismatch folder as if it were not there.
- Covers the folders **most** likely to be deleted. A clean scaffold usually becomes an
  application; a folder the tool just told you not to draft is the one you delete. Under
  Option B, the exact subset that motivated this whole fix keeps losing its skip.
- Cost: a scaffold you abandon becomes a permanent skip. Mitigated, not removed, by the
  `--forget-log` line the tool now prints on every non-zero exit.

### Option B — record only a clean scaffold (exit 0)

Treat "not draftable" as "not yet considered", and let the tracker's `--sync-log` /
`--update` writers pick the posting up later if it becomes real.

- Nothing is skipped that you never actually worked on.
- Cost: reopens this task's bug for the non-clean subset, and makes "is this posting
  skipped?" depend on an exit code that nothing on disk records. Reading the folder
  tells you nothing about whether its posting is in the log.
- Also splits the rule in two: the live-folder check would skip the posting while the
  folder exists, and stop skipping it the moment the folder is deleted — the exact
  disappearing-skip behaviour the append-only format was adopted to end.

### Option C — record it, and re-surface it on the next search with a marker

Keep the row but flag it (a `provisional` field, or a distinct `source`) so job-search
can show it with a note instead of dropping it.

- Best of both in principle.
- Cost: a new field in an authoritative file, a new branch in every reader, and a
  "surface it anyway" path that the skip-log exists to not have. Not worth it for a case
  whose remedy is already a single documented command.

## Recommendation

**Option A** — the default path, already implemented. The pipeline has one existing
answer to "does this folder count?" (`_register_row` and `_posting_keys`: yes, if it is on
disk), and the log should not be the one place that answers differently. The real cost of
Option A is a permanent skip on an abandoned scaffold; that cost is bounded by a printed,
argument-filled `--forget-log` command, and it is much smaller than Option B's cost, which
is that the bug this task fixed survives for precisely the folders it was reported about.

If you disagree, the change is small and local: gate the
`_record_created_postings(...)` call in `handoff._run_group` on `code == 0`. The tests
that pin the current behaviour are
`CreationTimeSkipLogTests.test_a_location_mismatch_folder_is_recorded_with_the_un_skip_command`
and `..._a_scaffold_with_no_fresh_jd_is_recorded_with_the_un_skip_command`.

**Your answer:** (2026-08-02, in chat) Option A — conditional on two things being true:
if the code and agent behaviour never delete an application folder, and if a deleted folder
therefore means *I* deleted it, then Option A is right, because my deleting a folder truly
means I don't want to consider that posting any more.

Both conditions were verified on 2026-08-02 before folding this answer:

- **No production code deletes an application folder.** Every `rmtree`/`unlink` in
  `automation/` and `skills/` that is not a test targets the postings cache
  (`build_postings.py`, `postings_fold_state.py`), store debris (`retention.py`, which
  explicitly skips `state/` and `_blobs/`), vendored copies, generated symlinks, or the
  reconciler's own queue file. No file that imports `config.applications_root()` deletes
  anything under it. The only `rmtree` of an application folder is in tests
  (`test_skip_log_writers.py`, `test_handoff.py`) against temp fixtures.
- **Agents are forbidden from deleting one**, by `AGENTS.md:233-236`: application folders
  "are removed by the **user only** — never by an agent, under any condition".

So a missing folder is always an owner decision, which is exactly the premise this answer
rests on.
