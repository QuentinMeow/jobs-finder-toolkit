# Verification — 2026-08-01-forget-log-tells-the-agent-to-delete-owner-data

Branch `fix/never-delete-application-folder`. Every command below was run from the branch's
own worktree, with output redirected (never piped) so the exit code read is the gate's own.

## 1. The duplicate chain, end to end, against a scratch applications tree

A live application folder for `https://jobs.example.com/backend-engineer`, then the exact
documented invocation an agent would use.

```
$ JOBHUNT_CONFIG=<scratch>/config.yaml handoff.py --json rows.json --select 'rank 1'
handoff: REFUSING to scaffold Example Corp / Backend Engineer — skipped as a duplicate
  (same URL already exists in the log or a live application folder). Nothing was created.
handoff: if this posting really is new (a stale or wrong log row, or a different requisition
  that happens to share a title), append a tombstone first:
  status.py --forget-log "https://jobs.example.com/backend-engineer"
HANDOFF_EXIT=2
```

Following that instruction — the step that used to dead-end in "delete the application
folder" — now terminates in an action an agent may perform:

```
$ JOBHUNT_CONFIG=<scratch>/config.yaml status.py --forget-log 'https://jobs.example.com/backend-engineer'
Error: url 'https://jobs.example.com/backend-engineer' is still backed by a live application
  folder ('example-corp-backend-engineer-20260801', status 'drafted'). A tombstone would be
  undone by the next --sync-log, which rebuilds that row from the folder — the folder IS the
  record that this posting was handled, so there is nothing to un-skip.
  Work with the application that already exists: <scratch>/apps/6_drafted/example-corp-backend-engineer-20260801
  Removing that folder is NOT the remedy and is not an agent's to make: application folders
  are removed by the USER only, never by an agent, under any condition (AGENTS.md, "Agents
  never delete owner data"). If it truly should go, propose the removal in
  message-queue/needs-human/ and stop; --forget-log repairs the row afterwards, once the
  owner has acted.
  (--forget-log is for a row whose folder is already gone — a typo, or an application the
  owner removed.)
FORGET_EXIT=1
```

The refusal is unchanged in kind (still exit 1, still appends nothing); only the remedy moved.

## 2. Before / after of the offending message

Before (`skills/application-tracker/scripts/status.py`, one line of a longer message):

```
  Move or delete the application folder first, then re-run --forget-log.
```

After: the three lines quoted in section 1 — refuse, name the existing application, route a
real removal to `message-queue/needs-human/`.

Second offender, `skills/job-search/scripts/handoff.py` (location-mismatch remedy):

```
- handoff: remedy — delete the folder ({folder}), re-run the selection without the offending
-   posting(s), or rerun with --allow-location-mismatch if these locations are intentional.
+ handoff: remedy — the folder is left on disk at {folder} for review; re-run the selection
+   without the offending posting(s), or rerun with --allow-location-mismatch if these
+   locations are intentional. Do NOT remove the folder: application folders are removed by
+   the USER only, never by an agent (AGENTS.md, "Agents never delete owner data") — propose
+   the removal in message-queue/needs-human/ if it should go.
```

## 3. Acceptance grep

```
$ grep -rn 'delete the application folder' skills/ automation/
skills/application-tracker/scripts/status.py:2862:    # read "Move or delete the application folder first" and it was the ONLY exit from
skills/application-tracker/scripts/tests/test_skip_log_writers.py:383:        "Move or delete the application folder", which is the one act AGENTS.md
skills/application-tracker/scripts/tests/test_skip_log_writers.py:397:        for banned in ("delete the application folder", "delete the folder",
```

Three hits, none addressed to an agent: a code comment quoting what the message *used to*
say, a test docstring doing the same, and the banned-strings list of the test that now
forbids it. Near-variants (`remove the folder`, `delete the folder`, `rm -rf`) were swept
too — the only remaining non-test hit is `docs/designs/workspace-restructure/README.md:210`,
which already reads "…`rm -rf` safe, not to let an agent perform it."

## 4. Suites

```
$ python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 120 tests in 50.982s
OK
EXIT=0

$ python -m unittest discover -s skills/job-search/scripts/tests
Ran 557 tests in 129.034s
OK
EXIT=0
```

Both new/tightened assertions live in those suites:
`test_the_live_folder_refusal_never_tells_an_agent_to_delete_the_folder` and
`test_location_mismatch_blocks_and_leaves_folder`.
