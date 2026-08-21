# A metadata review reason is computed and then never shown

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #264 ("emit a metadata-review reason rather than silently treating stated facts as absent"), residual from `fix/jd-metadata-extraction`

## Goal

When a posting states experience or pay that the extractor declined to publish,
the row says so — instead of reading identically to a posting that stated
nothing.

## Context

`fix/jd-metadata-extraction` added the two readers in
`automation/shared/job_metadata.py` but could not wire them up, because the
consuming files were owned by another change in flight:

- `extract_required_yoe_details()` / `assess_required_yoe()` now return
  `review_reasons`, carrying `yoe_stated_but_unparsed` when a "<count> years"
  phrase sits in an experience sentence that no pattern could read;
- `salary_review_reason(text, supplied=None)` returns `pay_stated_not_annual`,
  `pay_bands_conflict`, `pay_stated_but_unparsed`, or `None`.

Nothing calls either. The wiring is in files that change owner:

- `skills/job-search/scripts/scoring.py::experience_ok` already appends
  `experience_over_cap` to `posting.review_reasons`; the YOE reasons should join
  it there (the assessment is already stored in
  `posting.filter_assessments["experience"]`).
- salary has no equivalent hook. `search_jobs.py::enrich_posting_metadata`
  calls `analyze_job_metadata` and would be the natural place to call
  `salary_review_reason` and append the result to `posting.review_reasons`.
- `search_jobs.py::_format_comp` renders `?` for a missing band; a row whose
  pay was refused rather than absent should be distinguishable in the review
  section, not necessarily in the main table.

Do NOT add a review-reason field to `analyze_job_metadata`'s return: the flat
dict is copied into `meta.yaml` by `metadata_field_gaps`, and
`validate_job_metadata` rejects unknown structured fields on a `jobs[]` entry.

## Definition of done

- A posting whose pay or experience was read and then refused carries a named
  review reason on the row; a posting that stated neither carries none.
- Corpus or unit fixtures pin both sides (stated-and-refused vs silent).
- `.venv/bin/python automation/gates/run_gates.py --lane job-search` exits 0.
