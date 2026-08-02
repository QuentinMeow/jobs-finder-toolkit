# Worklog — 2026-08-01-memory-still-reports-fixed-bugs-as-open

## 2026-08-02 — session 1 (agent)

- Re-verified all six entries against the code before touching any status. Every claim of
  "already fixed" in the task turned out to be true, and each is now recorded with the
  commit that fixed it plus the current code that disproves the entry's symptom
  (`verification.md`).
- Entries 1-3 (`location-title-only-foreign-leak`, `rw-tailor-single-posting-canary-fixture-conflict`,
  `render-py-pdf-skipped-libreoffice-flake`) now carry `Status: fixed <date> by <commit>` and
  a `## Resolution` section. Kept, not deleted: `memory/known-issues/README.md` says keep for
  one PR cycle, and `docs/roadmap/desired-state.md` cited two of them, so a reader arriving
  from that citation must land on the record rather than a 404.
- Entry 3's `Source:` line pointed at `LESSONS.md:87-88`, which now holds text saying the
  opposite of what the entry quotes. Re-pointed at the section instead of the line numbers.
- Entry 4 (`skills-diff-provenance-noise`) stays `open` — correctly, the provenance-header
  half is still unfixed. Its Suggested fix now leads with the outstanding half and strikes
  the degree-pattern half, quoting the `_DEGREE_CHAIN_RE` that already ships, so nobody
  re-implements it.
- Entry 5: added a dated forward-link block to the workspace-layout ADR's header rather than
  editing its Consequences text — ADRs are immutable, and the convention already exists in
  `memory/decisions/process-folders-layout.md`. **Re-measured the handover count: 35, not the
  33 the task states** (`git ls-files 'history/conversations/*/handover.md' | wc -l`).
- Entry 6: the first sponsorship ADR now carries a `Superseded-by` header naming both
  successors in reading order and stating the concrete correction (bare `all` is no longer a
  scope-limit cue), which is what the adjacent index rows could not convey.
- `docs/roadmap/desired-state.md` no longer lists the two fixed defects as live; the count
  moved from 7 open known-issues to 4 and says so.
- `reconcile.py --check --fix-index` left `memory/index.md` byte-identical, so the titles
  the index carries were not disturbed by the header edits.
