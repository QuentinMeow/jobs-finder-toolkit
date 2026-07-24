# Handover — one-folder-per-company default

- **Date**: 2026-07-23
- **Task(s)**: none (ad-hoc owner request)

Owner reported that `/job-search` + `/resume-writer` keep creating a **separate application
folder per role at the same company** in a single session, when the intended default is **one
folder per company** (one resume, one cover letter per role), splitting only when roles are truly
divergent. Asked to find the root cause, fix the default, and reason about public vs private.

## What happened

- **Root cause (confirmed empirically).** The one-folder-per-company default was only documented
  deep in `resume-writer/reference.md` (Path A) + the handbook — but folders are actually created
  at *job-search handoff time*, and (1) `handoff.py` had **no grouping capability** (`--select`
  = one posting, `--all` = one folder per row, dedup only blocked exact duplicates), and (2)
  job-search **Step 4 told the agent to scaffold a folder "for each selected posting."** So a
  faithful agent produced one folder per posting. Evidence in the private applications tree: one
  company alone had **11 separate folders from a single session**, with several other companies at
  2–4 folders each.
- **Fix (all public tree — timeless tooling, no identity/dated data):**
  - `skills/job-search/scripts/handoff.py`: added **group-by-company** as the default for any
    multi-posting selection. New selectors `--select "Company"` and `--select "rank N,M"`; `--all`
    now groups **one folder per company** (multi-role `jobs:` list, one verbatim JD + one cover
    letter per posting). New `--split` flag forces the old one-per-posting layout (divergent
    roles). Multi-role grouping drops location-mismatch postings from a folder instead of blocking
    it. Single `--select "rank N"` / `"Company/Title"` unchanged.
  - `skills/job-search/scripts/tests/test_handoff.py`: +6 tests (grouping, `--all` per-company,
    `--split`, rank-list grouping, location-drop, JD-name disambiguation). **278/278 pass.**
  - `skills/job-search/SKILL.md` Step 4 + Files table: made one-folder-per-company the explicit
    default with a group-first decision + divergent-roles `--split` exception.
  - `skills/resume-writer/SKILL.md` Preflight + Step 1: added the one-folder-per-company default
    rule and clarified that "a new role at an already-applied company" means a **prior** session
    (not per-role folders within one session).
  - `evals/resume-writer/canaries.yaml`: added `rw-multi-role-one-folder` (examples-based).

## Where things stand

- Code + docs done; tests (278/278), reconciler, and the public leak guard all green. Bundled into
  a public PR alongside a company-research AI-strategy skill enhancement and a check.py known-issue.
- **Eval gate — skipped this batch (owner decision, 2026-07-23).** These are behavioral SKILL edits
  (job-search, resume-writer, company-research) whose canaries would normally run before merge per
  `evals/README.md`; the owner opted to skip the canary run for this batch. Unit tests (278/278)
  cover the handoff tool change; a brittle live-network job-search handoff canary was intentionally
  *not* added (real postings drift weekly).
- The pre-existing per-role folders that motivated this fix were consolidated separately (in the
  private applications tree); that cleanup is not part of this public PR.

## Needs your attention

- `reconcile.py --check` may flag `memory/index.md` stale after the new `known-issues/` note lands
  in this PR; regenerate the memory index (`reconcile.py --fix-index`) if so.
