# Worklog — 2026-07-28-workspace-phase-6-skip-log-authority

## 2026-07-30 — session 1 (agent)

- Confirmed the blocking precondition: phase 5 merged (#111), `market/logs/` exists, and
  `search_jobs.profile_dir()` is gone rather than repointed — so this task inherited a
  working accessor and could go straight at the file format, as the task file predicted.
- Measured the starting corpus twice, independently: 369 posting rows, 243 folders, 369
  `jobs:` entries, 367 with a URL and 2 without, and **zero** divergence between log and
  folders in all four directions. The log was a perfect projection, so this phase buys
  nothing retroactively and everything forward. (The task file's "242 folders" was stale;
  the live count is 243.)
- Wrote the design, then had it attacked before implementing. The review returned three
  blockers, and all three were real:
  - the url-else-pair identity used as a *reader* key would drop the `(company, role)`
    skip for 367 of 369 rows, invisibly — `test_skip_identity.py`'s fixture writes
    `url: ''` on every row, so the entire suite takes the pair branch and could not see it;
  - append-only removes the only repair mechanism the log ever had, with nothing proposed
    to replace it;
  - ordering the fold by `recorded` can only ever disagree with file order in an
    append-only file.
  The first blocker forced the shape that made the whole cutover safe: `read_postings()`
  returns rows in the old YAML shape, so each reader's diff is one line and behaviour is
  preserved by construction rather than by argument.
- Implemented in two PRs: the shared module + config accessor + vendoring first (pure
  addition, zero behaviour change), then the cutover.
- **Both implementation agents found errors in my design and were right.**
  - The in-loop `fold[key] = row` I specified as the ping-pong fix makes it *worse*: it
    appends both colliding rows every run instead of one. Convergence needs the collision
    collapsed before the loop.
  - Two coercions I had not specified are load-bearing: `None → ""` (or an unset `url:`
    reads as a difference on every run, appending a line per posting per sync forever) and
    non-str scalar → `str()` (an unquoted `research_date:` loads as `datetime.date`, which
    `json.dumps` refuses — `--sync-log` would have crashed rather than written; the old
    YAML writer never hit it because `yaml.safe_dump` serializes dates natively).
- Found while cutting over: `store_refilter.py`'s log branch had been reading
  `log["applications"]`/`log["entries"]` — keys this log has never carried — since the file
  was written, so "covered" silently meant "still has a live folder". It also crashed on a
  `NameError` (`prof_label`) after writing its first output file. Both fixed.
  `automation/search-recall-audit/` had no test suite and no CI step; both added.
- Filed three follow-ups rather than growing this task: handoff creation-time recording
  (needs `build_log`'s flattening extracted to a shared module first, plus an owner
  decision about exit-3 scaffolds), a gardener test that reads the owner's real profile
  when run unpinned, and the vendor gate's missing reverse audit of `_vendor/` dirs.
- Filed the retired-YAML deletion as a decision — agents never delete owner data.

Next: the owner runs `--backfill-log` against the live overlay (or approves an agent run),
then merges the stack. Until the backfill runs, the JSONL is empty and job-search skips
nothing.
