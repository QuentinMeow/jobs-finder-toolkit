# `extract_salary_range` can emit a band whose low is not a salary

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: observed in a live stage-1 canary run, 2026-07-31 — one of five job-search
  canaries run against real ATS boards for the eval gate
- **Claimed-by**:

## Goal

Stop the salary extractor emitting a range whose two ends came from different things, so a
shortlist row cannot show a pay band that no posting states.

## Context

A live run over 11,638 postings produced this row for a real posting titled
"Senior Backend Engineer, LangSmith Deployments":

```
salary_range: $240–$175,000
```

The low end is three digits and the high end is six. No employer states that band. The
extractor has matched a bare number somewhere in the description — plausibly a "240" from
unrelated prose, a team size, a latency figure, a version string — and paired it with a real
salary figure.

This matters more than a cosmetic glitch because `salary_range` is one of the six fields
`job_metadata.analyze_job_metadata` extracts, it is written into `meta.yaml` by
`status.py --enrich-metadata`, and it is shown to the user as fact in the shortlist. A row
that reads `$240` invites exactly the wrong conclusion about a posting.

Neighbouring evidence that this family of bug is live: a substring defect was already found
and fixed in the same module in this round — the salary term `"ote"` (on-target earnings)
matched inside the word "Rem**ote**", pulling every remote-work line into the pay section.
The fix there was word-boundary anchoring. Check whether the same anchoring gap explains
this one before assuming it is a separate cause.

## Definition of done

- [ ] The garbled band is reproduced from a fixture (fictional text carrying the same shape),
      not from a live fetch
- [ ] A range whose two ends are implausible as a pair — orders of magnitude apart, or one end
      below any credible annual figure — is rejected rather than reported
- [ ] A test pins the rejection, and pins that ordinary bands (`$176,000–$230,000`,
      `$176k–230k`, hourly ranges if supported) still parse
- [ ] `.venv/bin/python -m unittest discover -s automation/shared/tests` passes
