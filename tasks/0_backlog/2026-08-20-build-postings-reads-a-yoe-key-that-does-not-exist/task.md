# The store's level opinion reads a YOE key that does not exist

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: noticed while fixing GH #257/#264/#288 in `automation/shared/job_metadata.py`

## Goal

The posting store's `opinions.level` fallback actually uses the JD's stated
years, instead of silently discarding them and recording `unknown`.

## Context

`skills/job-search/scripts/build_postings.py`, in the opinion builder
(~line 342):

    level, _signal = job_metadata.classify_level(title)
    if level == "unknown" and text:
        yoe = job_metadata.assess_required_yoe(text) or {}
        level = job_metadata.infer_level_from_yoe(yoe.get("minimum"))

`assess_required_yoe()` returns the minimum under the key `min`, not
`minimum` — its result is `{"domain", "decision", "result", "min", "max",
"source", "confidence", "requirement_kind", "specialty", "review_reasons"}`.
So `yoe.get("minimum")` is always `None`, `infer_level_from_yoe(None)` always
returns `"unknown"`, and the fallback has never once fired: every unleveled
title in the store records `level: unknown` regardless of what the JD states.

The tracked example fixtures show the symptom —
`examples/store/jobs/derived/postings/*/posting.yaml` all carry
`opinions.level.value: unknown`.

Two things to decide when fixing:

- reading `min` will start moving fixture VALUES (not just the module digest
  line), so `automation/store/generate_fixture_store.py` must be re-run and the
  result reviewed, not just regenerated;
- `assess_required_yoe` is the tri-state gate; `extract_required_yoe_details`
  is the plain read. The opinion probably wants the details call, and should
  likely respect confidence the way `scoring.parse_min_required_years` does
  (only a high-confidence minimum is safe to level from).

Note that as of #288 `classify_level` also returns management scopes, so a
manager title no longer reaches this fallback at all.

## Definition of done

- The fallback uses a key the assessment actually returns, with a test that
  fails on the old key.
- `examples/store` regenerated and the value changes reviewed deliberately.
- `.venv/bin/python automation/gates/run_gates.py --lane job-search --lane shared`
  exits 0.
