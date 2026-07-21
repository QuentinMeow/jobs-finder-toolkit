<!-- See CONTRIBUTING.md for details on each item. -->

## What & why

<!-- Briefly describe the change and the motivation. -->

## Checklist

- [ ] Tests pass: `.venv/bin/python -m unittest discover -s scripts/publish/tests`
- [ ] Budget clean: `.venv/bin/python scripts/metrics/instruction_budget.py --strict`
- [ ] Leak guard clean (exit 0, zero findings): `.venv/bin/python scripts/publish/check_public.py`
- [ ] Links OK: `.venv/bin/python scripts/maintenance/gardener/gardener.py verify-links`
- [ ] If any `.agents/skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: per the risk-based gate, either ran that skill's canaries in `evals/<skill>/` and pasted results below, or recorded a one-line skip rationale (`Eval gate: skipped — <intention + size>`) — see `evals/README.md`
- [ ] **No personal data** (no real names, emails, phones, employer/school names, or home paths) — this repo is PUBLIC

## Canary results / skip rationale (only if skill-instruction files changed)

<!-- Paste eval results per evals/README.md, or a one-line skip rationale, or write "N/A". -->
