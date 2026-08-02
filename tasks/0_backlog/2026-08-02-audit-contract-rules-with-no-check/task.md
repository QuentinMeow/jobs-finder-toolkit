# Audit the contract for rules that have no check behind them

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: the second occurrence of the piped-gate defect, 2026-08-01, one day after
  [`tasks/4_done/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code`](../../4_done/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code/task.md)
  closed it with prose · [the lesson](../../../memory/lessons/harness/broken-twice-build-the-check.md)

## Goal

List every hard rule in `AGENTS.md` that is enforced only by being written down, and for
each one say whether a check is possible, cheap, and worth it — so the next repeat is a
decision that was already made rather than a surprise.

## Context

`AGENTS.md`'s Guardrails read as invariants, but they are enforced very unevenly. Some are
backed by a gate that fails (`private/` staged, the leak guard, the review gate, the
reconciler, `check_mail_safety.py`). Others exist only as sentences an agent is trusted to
remember at the moment of action — and at least one of those has now failed twice after
being "fixed" once:

- **Never pipe a command whose exit code you are about to read** (Shell & Paths). Fixed on
  2026-07-31 by adding the convention to `AGENTS.md`; broken again on 2026-08-01. The
  closing task explicitly considered a `verify_links.py` enforcement point, measured 9
  hits / 0 real defects, and declined. The countermeasure that shipped instead is
  `automation/gates/run_gates.py`, which removes the *motive* for the pipe rather than
  detecting it.
- **Always use absolute paths in bash calls** — no check.
- **Never `--no-verify`** — the hook cannot see its own bypass; nothing downstream looks.
- **Agents never delete owner data** — no check; a `tasks/0_backlog/` item already exists
  for one place where an instruction tells an agent to do it anyway.
- **Never fabricate experience** — `check.py` covers titles and skills, not claims.

The `git add -A` case shows the opposite failure: the rule is treated as binding in task
files and in `bootstrap_overlay.py`'s comments, but it is **not in `AGENTS.md` at all**, and
two tracked files actively teach it (`automation/publish/review_gate.py:74` and
`skills/github-workflow/SKILL.md:369`). A rule that lives only in the folklore of past tasks
is worse than one that lives only in prose.

## Definition of done

- [ ] A table in `docs/handbook/` (or this task's `verification.md`): every Guardrails bullet
      and every Conventions rule → the check that enforces it, or `none`.
- [ ] For each `none`, one of: a filed task to build the check, or a written decision to
      accept recurrence with the reason (the false-positive count, the cost, the rarity).
- [ ] The `git add -A` contradiction resolved in one direction — either the rule enters
      `AGENTS.md` and the two teaching sites are corrected, or the folklore is dropped.
- [ ] Re-run of the sweep the 2026-07-31 task did, to confirm no tracked file teaches a
      piped gate:
      `grep -rn '| *tail\|| *head' skills/ docs/ automation/ .github/`
