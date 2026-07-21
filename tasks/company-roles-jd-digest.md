# Add a digest mode to company_roles.py --jd (the ATS-API JD path)

- **Status**: todo
- **Priority**: P1
- **Area**: job-search
- **Source**: confirmation-round search leg, 2026-07-21
  (`evals/results/confirmation-round-20260721.md`)

## Goal

Extend the fetch-time digest lever to the ATS-API JD-recovery path:
`company_roles.py --jd` currently dumps the full recovered JD (~5–8 KB per
candidate) to stdout with no digest option.

## Context

`fetch_jd.py --digest` (PR #40) prints a ~2 KB gate-signal locator alongside
the saved verbatim JD — but only for direct page fetches. In the 2026-07-21
measured search leg, ALL four JD verifications went through
`company_roles.py --jd` because every candidate was Ashby-hosted and
JS-rendered, so the digest lever never engaged: 4 full-JD stdout dumps were
read instead. On JS-heavy days the ATS-API path is the COMMON path, not the
fallback.

Implementation: reuse `fetch_jd.build_digest()` (import or vendored-shared,
respecting the skills' self-containment rule — both scripts live in the same
job-search `scripts/` dir, so a sibling import works). `--jd --digest`
saves/prints the verbatim JD to the `--out` path exactly as today AND prints
the digest; without `--digest`, byte-identical behavior. Update the
SKILL.md/reference.md JS-fallback lines (PR #38/#40 sections) to carry the
flag.

## Definition of done

- `company_roles.py --jd --digest` prints the same digest format as
  `fetch_jd.py --digest` for the same JD text; no-flag behavior unchanged
  (regression test).
- Unit tests beside the existing company_roles tests; job-search suite
  green.
- Reference/SKILL fallback lines updated (mechanical edit; record the eval
  gate skip rationale).
