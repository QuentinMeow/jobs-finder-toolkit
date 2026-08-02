# Workday's "and N more" truncation cannot be detected from the search payload alone

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: left behind by the search-recall-audit defect fixes (adversarial audit #4, finding 4), 2026-07-31
- **Claimed-by**: agent session 2026-08-02 (fix/25-recall-audit-cli)

## Goal

`field_fidelity corpus` should be able to say **which** locations a Workday
posting's `locationsText` hid behind "and N more", instead of only being able to
report the truncated string faithfully.

## Context

Finding 4 was that `cmd_corpus` could never raw-resolve a Workday posting, so the
source was reported clean without ever being read. That is fixed: `_job_native_id`
now derives the id-less source's identity through the parser's own
`_workday_req`, so Workday rows carry `raw_resolved: True`, a
`raw_location_view`, a gate decision, and a place in `sample`.

What the fix does **not** reach is the failure that motivated it. Workday's search
list ships one field, `locationsText`, whose canonical shape is
`"Austin, TX and 3 more"`. The generated `location` is a verbatim copy of it, so
`dropped_raw_tokens` is empty **by construction** — raw and generated are the same
string, and the three hidden metros are absent from BOTH. The audit can now look
at the posting and will correctly report "faithful"; the information loss happened
upstream, at the board.

The hidden locations live in the per-posting detail response
(`skills/job-search/scripts/sources.py`, `fetch_workday`'s detail leg), which the
search fetch does not always take. So this needs either:

* a detail-backed location list folded into the raw view (cost: one fetch per
  posting, and `fetch_workday` already reports when those fail — see
  `record_source_warning`), or
* a deterministic `truncated_location_list` flag in `_flags_for` that fires on the
  `and \d+ more` shape and sends the case to a judge as "known-lossy at source",
  which is honest and free.

The second is the cheaper first step and matches the skill's stated design (fix
KNOWN formats in code, escalate WEIRD ones — never fold noisy fields). Note the
gate currently reads `"Austin, TX and 3 more"` as `review/unknown`, so these
postings are already surfaced for a human rather than silently dropped; this is a
precision/visibility gap, not a recall hole.

## Definition of done

- [x] A Workday posting whose `locationsText` ends in `and N more` is flagged (or
      its hidden metros resolved), rather than reported as a faithful copy. —
      flagged `truncated_location_list`; the hidden metros are NOT resolved, which
      is this file's own second option (no per-posting detail fetch).
- [x] A test in `automation/search-recall-audit/tests/test_field_fidelity.py`
      pins the new behaviour on a recorded Workday payload (no live fetch). —
      `TruncatedLocationListTests` + `FlagShapeTests`.
- [x] The skill's field-fidelity section names the new flag if one is added. —
      `skills/search-recall-audit/SKILL.md`; it named no flags at all, so the
      added line names all five.

Not redone: the `_job_native_id` half described in the Context above was already
fixed before this task was picked up (`field_fidelity.py`'s `_DERIVED_NATIVE_ID`),
and this change touched none of it. See `verification.md`.
