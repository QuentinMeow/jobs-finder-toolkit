# resume-writer told the agent to create applications outside the configured root

- **Priority**: P1 (this round)
- **Area**: resume-writer
- **Source**: repo contradiction audit, 2026-07-30 (finding 5 — the only finding that misfiled
  owner data at the time it was written)
- **Claimed-by**: agent, 2026-07-31 (branch `fix/03-owner-data-paths`; work complete, in review)

## Goal

Make an agent following the resume-writer skill create the application folder under
`config.applications_root()`, and define the `applications/` shorthand wherever a reader
meets it instead of leaving it undefined in every document but one.

## Context

`skills/resume-writer/SKILL.md` step 5 printed a literal
`mkdir -p applications/6_drafted/<slug>/source`, against `AGENTS.md`'s rule that paths always
come from `config.*_path()` and never literals. `config.applications_root()` resolves into the
private overlay for a real hunt and to `examples/applications` under the example config, so the
literal created the folder at the public repo root: git-ignored, invisible to `status.py`,
`--check-locations`, `--sync-log` and the skip-log, and gone on the next clean checkout — with
no error at any point.

The bare literal also appears in `AGENTS.md`, `docs/handbook/command-cookbook.md`,
`docs/handbook/application-folders.md`, and in the application-tracker, job-search and
search-recall-audit skills. Only `skills/ask-me-anything/SKILL.md` ever defined it as shorthand
for the accessor. Those other sites are prose describing where things live, not commands that
create them, so the fix there is a definition rather than a rewrite.

## Definition of done

- [x] No skill prints a command that creates an application folder at a literal path
- [x] The `applications/` shorthand is defined in every document that leans on it as a top-level
      instruction surface
- [x] The full gate is green

## Follow-up left open

The remaining `applications/` literals in `skills/job-search/SKILL.md`,
`skills/search-recall-audit/SKILL.md` and `skills/resume-writer/reference.md` were judged
documentation shorthand covered by the definitions above (reference.md is only ever opened from
its own SKILL.md, which now defines the term). If a future reader is misled by one of them, the
fix is another one-line definition, not a rewrite.
