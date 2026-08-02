# Worklog — 2026-07-31-piping-a-gate-to-tail-hides-its-exit-code

## 2026-07-31 — session 1 (agent, `wip/34-gate-exit-code-discipline`)

- Swept `skills/ automation/ docs/ CONTRIBUTING.md` (and, unprompted, `.github/`,
  `templates/`, `evals/protocols/`) for a piped command. **14 hits, 0 gates.** The
  surprise: nothing in the tracked tree teaches the pattern, so there was no edit
  sweep to do — the whole fix is a stated convention.
- Chose **do not pipe a gate; redirect and read the file**. `pipefail` was rejected
  partly on a fact found mid-sweep: the hooks are `#!/bin/sh` under `set -e`, where
  `pipefail` is not portable, so a repo-wide `pipefail` rule could never have covered
  the repo's own gate runner.
- Two `AGENTS.md` additions: the idiom in **Shell & Paths** (with the zsh
  `${pipestatus[1]}` vs bash `${PIPESTATUS[0]}` difference stated in place), the
  out-of-scope-red-gate routing rule as a new **Guardrails** bullet. 318 → 335 lines
  against a 500 budget.
- Measured the `verify_links.py` enforcement idea rather than arguing it: 9 hits, 0
  real, and all three hard-failing-tier hits are a literal `|` inside a
  `<a|b|c>` placeholder. Declined, no follow-up task.
- Reproduced the bug live on `check_public.py` (a gate that really exits 2) and hit an
  unplanned instance of it in this session's own first command.
- Next: owner review of the two `AGENTS.md` bullets. Nothing blocked.
