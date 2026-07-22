# Tailoring Guardrails (extended guidance)

These expand the core `AGENTS.md` → "Guardrails" invariants.

- **Traceability sources**: a bullet may pull real, traceable detail from the candidate
  profile (`config.profile_md_path()`) or the supporting library
  (`interviews/behavioral-story-bank/`, the answer bank, prior applications, notes).
  Rewording and pulling in real detail from those sources is encouraged; fabrication is forbidden.
- **Keyword density**: incorporate job description keywords naturally. Do not stuff.
  Readability matters — a human recruiter reads after ATS passes.
- **Skill lists (full rule)**: the profile's Skills section defines Approved (generally
  include in most resumes, if not all), Weak (shown to users as **Weak or Selective**;
  include only when the JD specifically mentions it), and Never (never include in any resume,
  even when the JD mentions it). JD skills in none of the lists must be surfaced to the user
  for categorization at the end of a tailoring run, never added silently.
