# Document the skills_diff precision rules in the resume-writer skill

- **Priority**: P2 (someday)
- **Area**: resume-writer
- **Source**: Follow-up from the fixes for issues #260, #261 and #272 on branch
  `fix/tailoring-card-units`. That branch was explicitly scoped to
  `skills/resume-writer/scripts/` and was not allowed to touch any
  `SKILL.md` / `LESSONS.md` / `reference.md` (eval gate + in-flight harness work),
  so the behavior changed and its documentation did not.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Add a short note to the resume-writer skill's Step-7 section explaining the two
new matching rules a drafting agent can otherwise misread as a missing skill,
and (if the skill documents the card at all) that a tailoring-card key number
now carries its unit.

## Context

Three script fixes landed with no doc change:

1. `build_tailoring_card.py` — a key number now keeps the unit or noun that gives
   it meaning ("18 Kubernetes clusters", "54 minutes", "1,200 to 430 pages"), is
   never a number glued to a bare unit letter ("18 K"), and the 12-item list is
   ordered by job-search value rather than document order.
2. `skills_diff.py` — provenance URLs, URL query fragments, labelled
   location/time-zone/source fields and "City, ST" pairs are removed before
   extraction, and time-zone/region/generic section words can never be queued.
3. `skills_diff.py` — a known compound ("CI/CD", "A/B testing") is ONE queue item
   and is never split, and a **qualified profile entry categorizes its concept**:
   Weak "Java basics" answers a JD's "Java", Never "MySQL administration"
   answers "MySQL", Never "CI/CD work" answers "CI/CD".

Rule 3 is the one worth documenting: an agent reading Step 7 may expect a bare
"Java" in the queue and, not seeing it, add it to the profile by hand — which is
exactly the broader, less truthful duplicate entry the fix exists to prevent. The
skill should state that the qualifier stays as written, that this matching is
report-only, and that `check.py` remains the authority on what a resume may claim.

Relevant files:

- `skills/resume-writer/SKILL.md` § "Step 7: Categorize New JD Skills in One Batch"
- `skills/resume-writer/scripts/skills_diff.py` (module docstring already carries
  the full rule; the skill text can point at it)
- `skills/resume-writer/scripts/build_tailoring_card.py` § key numbers

## Definition of done

- Step 7 of `skills/resume-writer/SKILL.md` states that a qualified profile entry
  covers its bare concept and that compounds are asked once, in <= 4 lines.
- The eval gate is discharged per AGENTS.md: run `evals/canaries/resume-writer.yaml`
  if the edit is behavioral, or record the one-line skip rationale if it is not.
- `automation/reconcile/reconcile.py --check` exits 0.
