# Filter variant corpus

This directory is the deterministic, public-safe regression corpus for job-search
fields that can incorrectly remove a posting: location/workplace, sponsorship,
title/seniority, and required years of experience.

`corpus.yaml` contains fictional, timeless examples. Known examples run as ordinary
unit tests and consume no AI. A live snapshot remains private under `tmp/`; audit it
with:

```bash
.venv/bin/python .agents/skills/job-search/scripts/validate_filter_variants.py \
  --snapshot tmp/search_cache/<snapshot>.json --profile example
```

The command exits nonzero when signal-bearing text is contradictory or cannot be
classified. It writes grouped YAML stubs under `tmp/filter_variant_reports/`.
Review the real posting privately, add or adjust a deterministic rule, then promote
only a fictional minimal reproduction to `corpus.yaml`.

Do not copy real company names, URLs, full job descriptions, candidate data, or
dated posting facts into this tracked corpus. The public leak guard remains the
final promotion gate.

Novelty detection is intentionally bounded: deterministic code can flag a new
shape only when it contains a known domain marker (for example `remote`,
`sponsorship`, or `years of experience`) or produces conflicting evidence. Text
with no recognizable marker cannot be proven novel without a separate review.
