# Verification — 2026-08-21-skill-prompt-safety

## Prompt-surface audit and focused test suites

```
$ .venv/bin/python automation/metrics/skill_prompt_audit.py --strict
19 file(s); 17 with advisory/hard categories; 0 over a strict limit.
OK: no conservative prompt-surface limit exceeded.

$ .venv/bin/python -m unittest discover -s automation/metrics/tests
Ran 90 tests in 0.608s
OK

$ .venv/bin/python -m unittest discover -s automation/evals/tests
Ran 81 tests in 9.477s
OK

$ .venv/bin/python -m unittest discover -s automation/gates/tests
Ran 75 tests in 0.298s
OK
```

## Policy and maintenance lanes

```
$ .venv/bin/python automation/gates/run_gates.py --lane policy --lane maintenance
ALL GREEN (19 gates)
```

## Company-research canaries

```
$ .venv/bin/python automation/evals/record_pins.py --write evals/results/company-research-02fa203db610-20260821-prompt-surface.md
refreshed eval-pin block for `company-research` (5 file(s) pinned).

Independent GPT-5.6-sol xhigh rubric judges
Pass rate: 7/7
Efficiency metrics: not measured
Invalid-prompt policy rejections after the repair: 0
```

## Static skill checks

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.

$ .venv/bin/python automation/gardener/verify_links.py --no-overlay
OK: 3767 references, the skill symlinks and the vendored copies verified.

$ .venv/bin/python automation/publish/sync_skill_manifests.py --check
skill manifests in sync (13 public skill(s))

$ git diff --check
(exit 0; no output)

$ .venv/bin/python scripts/quick_validate.py .
Skill is valid!
```
