# Group the private overlay by personal workflow

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Owner request, 2026-08-06; supersedes the private lifetime taxonomy in the workspace-restructure design
- **Claimed-by**: Codex `/root`

## Goal

Make the private overlay navigable by purpose: personal career sources, applications,
general interview preparation, and company-specific interview material live below `me/`
without loose files directly under `me/`; infrastructure, market, store, skill, evaluation,
and process roots remain clearly separated. Update every consumer and open the required
private and public pull requests without disturbing unrelated work in progress.

## Context

The current layout deliberately separates `applications/`, `companies/`, and `me/` by
lifetime. The owner has replaced that organizing principle: applications are personal
artifacts and belong below `me/`, while the current company tree contains interview-only
material and belongs below `me/interviews/`. Loose candidate files directly under `me/`
must also move into purpose-named subfolders.

The private checkout has unrelated uncommitted application, calendar, log, and queue
changes. Build the private migration in a separate worktree and leave those edits untouched.
The public toolkit and private overlay are separate Git repositories and require separate
PRs. Public prose must describe the private tree without naming any real company or quoting
private content.

## Definition of done

- [x] A design records the complete before/after taxonomy and supersedes the prior lifetime layout without rewriting history.
- [x] Every tracked private file is classified, moved or intentionally retained, with no loose files directly under `me/`.
- [ ] Ignored local data under moved roots has a safe, non-overwriting migration path.
- [x] Config accessors, examples, documentation, skills, and tests resolve the new paths; the ignored local config waits for merge-time cutover.
- [x] File-count and blob-identity checks prove that mechanical moves did not lose or rewrite owner data.
- [ ] Impacted gates pass in both repositories, including a config-less public checkout.
- [x] Separate private and public branches are committed, pushed, and opened as PRs with CI checked.
