# Worklog — 2026-07-31-workday-multi-location-truncation-is-invisible-in-raw

## 2026-08-02 — session 1 (agent)

- **The `_job_native_id` half was already fixed before this session started** and
  was not touched here. `field_fidelity.py` already carries
  `_DERIVED_NATIVE_ID = {"workday": parsers._workday_req}` and derives the id-less
  source's identity through the parser's own function, so Workday rows already
  resolved against their raw payload, carried a `raw_location_view` and a gate
  decision, and already reached `sample`. `WorkdayRawResolutionTests` pins that
  and passed untouched. This session did only the half the task said the earlier
  fix does not reach: making the truncation visible.
- Took the task's second option — the deterministic flag — not the detail-backed
  location list. It is the cheaper first step, it costs no fetch, and it matches
  the skill's stated design (fix KNOWN formats in code, escalate WEIRD ones). The
  detail leg remains available if the flag ever shows the volume is worth a fetch
  per posting.
- The flag matches the GENERATED string, not the source name. Any board that
  ships an `and N more` tail is caught, and nothing about the check assumes
  Workday. Kept deliberately narrow per LESSONS ("keep the detector
  CONSERVATIVE"): a spelled-out multi-location string hides nothing and is not
  flagged, with negative controls pinning that — including `"Portland, OR"`,
  where the word `and` is inside a metro name.
- Confirmed the defect's mechanism in the test rather than assuming it: the
  corpus row for a truncated posting has `dropped_raw_tokens == []` — raw and
  generated really are the same string — and is still flagged. That assertion
  pair is the whole finding in two lines.
- Named the flag in `skills/search-recall-audit/SKILL.md`. The section listed no
  flags at all, so the new line names all five, not just this one.
