# Should already-enriched applications be re-run now that third-party years no longer count as a requirement?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [task 2026-07-31-sponsorship-negation-defeats-require-positive](../../../tasks/4_done/2026-07-31-sponsorship-negation-defeats-require-positive/task.md)
- **Blocks**: nothing — the fix ships either way; this is only about existing files
- **Default path**: agents change nothing. Existing `meta.yaml` files keep whatever
  `required_yoe` / `job_level` they were written with; only newly enriched
  applications get the corrected reads.
- **Cost if wrong**: one-time
- **Safe to merge because**: agents write nothing meanwhile; when the answer lands, `status.py
  --enrich-metadata` re-derives the affected `meta.yaml` files from the JD and cache.

## Background

Before this fix, a JD sentence such as "our founders bring 25 years of engineering
experience" was parsed as the *candidate's* required years. Any application enriched
with `status.py --enrich-metadata` while that was true may carry
`required_yoe: {min: <the company's number>, confidence: high}` and, when the title
has no seniority word, a `job_level.normalized` inferred from it (25 years reads as
`senior_staff`). Those are wrong facts about a real posting, sitting in tracking
metadata you read.

Re-running `--enrich-metadata` on an application recomputes those fields from the
saved JD, so it would correct them. Agents do not touch application folders without
being asked, which is why this is a question rather than a change.

## Options

### Option A — Leave existing applications alone (default)
Nothing is rewritten. Wrong YOE/level values persist in older folders; you notice
them only if you look. Zero risk, zero work.

### Option B — Re-enrich everything once, yourself
`status.py --enrich-metadata` per application folder. Corrects the wrong numbers,
but it also recomputes every other enriched field from the current JD text, so
anything you hand-edited in those fields since could be overwritten. It is your
data, so it is your call, not an agent's.

### Option C — Re-enrich only where it matters
Check the folders whose `required_yoe.min` looks implausible for the role (a
"Software Engineer" showing 25+ years is the tell) and re-run only those.

## Recommendation

Option C. The defect needs a company-history sentence with a large number in it, so
only a minority of folders can be affected, and they are identifiable by eye from
`status.py` output. A blanket re-enrich buys little and risks overwriting fields you
may have corrected by hand.

**Your answer:** ______
