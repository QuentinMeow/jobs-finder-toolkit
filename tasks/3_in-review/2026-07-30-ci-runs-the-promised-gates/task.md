# CI runs the gates the documents promise

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: repo contradiction audit, 2026-07-30 (findings 1, 2, 3, 4, 17)
- **Claimed-by**: agent session 2026-07-30 (fix/02-ci-runs-the-promised-gates)

## Goal

Every check that `CONTRIBUTING.md`, `README.md` and
`skills/github-workflow/SKILL.md` describe as a gate actually runs in
`.github/workflows/ci.yml`, and `automation/metrics/instruction_budget.py`
measures what its docstring says it measures.

## Context

The audit reproduced five gaps between what the documents promise and what CI
does:

1. **Four skill suites never ran in CI** — `skills/application-tracker/scripts/tests`
   (77 tests), `skills/email-assistant/scripts/tests` (67),
   `skills/behavioral-interview-prep/scripts/tests` (12),
   `skills/github-workflow/scripts/tests` (15). `CONTRIBUTING.md` said "CI runs
   them too" and `README.md` said "CI runs it all". application-tracker owns the
   v5 `meta.yaml` schema, the status rollup and the folder moves over owner
   data; email-assistant owns the send-less mail path. Both could regress at
   merge behind a green tick.
2. **`automation/shared/mail/check_mail_safety.py` never ran in CI** — only in
   `automation/hooks/pre-commit`. `AGENTS.md` states the send-less invariant
   absolutely, and it is the one guardrail whose failure is irreversible for the
   user. An uninstalled hook, a `--no-verify` commit or a fork PR could add
   `Mail.Send` and keep CI green.
3. **`instruction_budget.py --strict` never ran in CI** — `CONTRIBUTING.md`, the
   script's own usage block and `skills/github-workflow/SKILL.md` (gate #7) all
   present it as a hard gate; it was enforced only by the local hook.
4. **The budget script over-claimed its coverage** — the docstring said "every
   `AGENTS.md`" while `_iter_targets` globbed the root file and `skills/*/`
   only. `docs/designs/AGENTS.md` exists, auto-loads for any agent reading in
   that folder, and was unmeasured.
5. **`.github/pull_request_template.md` named one suite** (`automation/publish/tests`)
   for its "Tests pass" box while CI ran eight — a contributor who ticked the
   box had run about an eighth of the gate.

Constraint that shapes all of it: CI has **no `config.yaml` and no `private/`
overlay**. A step that needs either turns the trunk red, so everything added
here was first run in a detached worktree with neither.

## Definition of done

- [x] `ci.yml` runs the four skill suites, `check_mail_safety.py` and
      `instruction_budget.py --strict`.
- [x] Every added step verified in a config-less, overlay-less worktree
      (`verification.md`).
- [x] `instruction_budget.py`'s docstring and code agree: every `AGENTS.md` in
      the tree is measured, root and folder leaves on separate budgets.
- [x] The leaf tier is covered by unit tests, and CI runs them.
- [x] The PR template points at `CONTRIBUTING.md`'s list instead of naming a
      stale subset; that list is declared canonical and is complete.
- [x] `automation/reconcile/reconcile.py --check --require-roots` clean.
