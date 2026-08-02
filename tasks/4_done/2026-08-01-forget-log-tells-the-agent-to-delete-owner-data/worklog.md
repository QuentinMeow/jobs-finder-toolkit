# Worklog — 2026-08-01-forget-log-tells-the-agent-to-delete-owner-data

## 2026-08-02 — session 1 (agent)

- Re-located the message by content before touching it: the filed coordinate
  (`status.py:2647`) had rotted; the live text was at `status.py:2867`.
- Chose the **message-routing** option over the opt-in flag, and recorded the reason in the
  code: a tombstone appended over a live folder is rebuilt by the very next `--sync-log`, so
  a `--forget-log --even-if-live` flag would buy precisely the silent no-op un-skip that
  branch exists to refuse. The remedy that *works* is that the application already exists.
- Dropped "Move" from the remedy for the reason the task gives — `LIVE_STATUS_DIRS` covers
  all five status folders, so a move between them clears nothing.
- **A second offender surfaced on the near-variant sweep** and is fixed in the same branch:
  `handoff.py`'s location-mismatch remedy opened `delete the folder (<path>)`. That folder is
  left on disk *for review*, and the message was reading as a deletion cue. It now names the
  path for inspection and states the guardrail.
- Two prose references in `handoff.py` that quoted the old remedy (`_report_explicit_duplicate`
  and `_record_created_postings` docstrings) were brought in line so the file does not describe
  a behaviour it no longer has.
- Both messages are now pinned by tests, so neither can regress silently:
  `test_the_live_folder_refusal_never_tells_an_agent_to_delete_the_folder` (new) and
  `test_location_mismatch_blocks_and_leaves_folder` (tightened — it used to *require* the
  string "delete the folder").
- Checked the pending decision `is-never-delete-owner-data-scoped-to-repo-local-products.md`
  before finishing: both of its options keep application folders absolutely off-limits to an
  agent, so this change is correct under either. Nothing here depends on its default path.
