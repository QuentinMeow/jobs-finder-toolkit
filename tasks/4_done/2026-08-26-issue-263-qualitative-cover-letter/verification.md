# Verification — 2026-08-26-issue-263-qualitative-cover-letter

## Canary definition and pinned instruction bytes

```
$ .venv/bin/python -c 'import yaml; data=yaml.safe_load(open("evals/canaries/resume-writer.yaml", encoding="utf-8")); print("resume-writer canaries:", len(data["canaries"]))'
resume-writer canaries: 9

$ .venv/bin/python automation/evals/record_pins.py --report evals/results/resume-writer-a68b2b69a223-20260826-qualitative-evidence.md
eval-pin report — skill `resume-writer` against HEAD (a68b2b69a223)
current  skills/resume-writer/SKILL.md
current  skills/resume-writer/LESSONS.md
current  skills/resume-writer/reference.md
current  evals/canaries/resume-writer.yaml
4 pinned file(s): 4 current.
```

## Fresh-session behavioral regression gate

Each canary ran in a separate ephemeral, non-interactive Codex process with no prior transcript,
using its prompt verbatim and these fixed subject settings:

```
/Applications/ChatGPT.app/Contents/Resources/codex exec --ephemeral --strict-config \
  -m gpt-5.6-sol -c 'model_reasoning_effort="xhigh"' --approve-for-me \
  -C "$PWD" \
  -o local/evals/issue-263/<canary-id>.md '<verbatim canary prompt>'
```

| Canary | Result | Evidence summary |
|--------|--------|------------------|
| `rw-tailor-single-posting` | PASS | All artifacts and validation passed. Step 7 returned a complete zero-item queue; zero questions is correct. The separate category canary covers question formatting. |
| `rw-layout-budget-verdict` | PASS | Preserved supported content and correctly treated the rendered page count as authoritative. |
| `rw-multi-experience-baseline` | PASS | Preserved two employers, six direct bullets, and four projects; render/check exit 0. |
| `rw-bundled-txt-structure` | PASS | Canonical bundle; source-backed 50M+, 30+, and 35% metrics; render/check exit 0. |
| `rw-sparse-source-qualitative-cover-letter` | PASS | 130 words; specific source-backed actions; no number, estimate, unsupported outcome, or invented detail. |
| `rw-skill-gating-weak-never` | PASS | Never/Weak policy preserved. |
| `rw-skill-category-question-batch` | PASS | Two one-skill questions, one batch, correct option order, no category edit. |
| `rw-multi-role-one-folder` | PASS | One shared resume, two exact JD mappings, two distinct bundles/letters; render/check exit 0. |
| `rw-duplicate-preflight` | PASS | Duplicate detected before write; sentinel unchanged. |

Pass rate: `9/9`. Full notes and pinned bytes are in
`evals/results/resume-writer-a68b2b69a223-20260826-qualitative-evidence.md`.

## Deterministic resume-writer tests

```
$ env JOBHUNT_CONFIG="$PWD/config.example.yaml" .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests -p 'test_*.py'
...................................................................................................................................................
----------------------------------------------------------------------
Ran 147 tests in 3.324s

OK
EXIT=0
```

The suite ran outside the macOS sandbox because its real PDF tests launch LibreOffice.

## Instruction budget

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
skills/resume-writer/SKILL.md  473 lines  33,223 bytes  ~8,305 tokens  budget 600  ok
OK: all instruction files within budget.
EXIT=0
```

## Impact-selected repository gates

```
$ .venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
running 19 of 37 gates (impact from: origin/main, jobs: 8)
PASS: vendor-drift, mail-send-less, compileall, instruction-budget,
skill-prompt-audit, reconciler, verify-links, tests-reconcile, tests-gardener,
tests-hooks, tests-metrics, tests-evals, tests-gates, tests-ci-classifier,
tests-cutover, tests-workspace, review-gate-verify-all, tests-github-workflow,
leak-guard-tree
coverage: 19 of 37 gates in the table executed (0 skipped, 18 not selected)
ALL GREEN (19 of 37 gates ran)
EXIT=0
```

The selector dropped render, resume, shared, job-search, applications, and publish because every
changed path had a focused CI owner. The resume-writer suite above independently ran all 147 resume
tests, including the real PDF-producing tests.

## Commit trailers on the implementation commit

```
$ git show -s --format='%H%n%B' a68b2b69a223039270f49a272f9058e7bd4a1aa1
a68b2b69a223039270f49a272f9058e7bd4a1aa1
docs(resume-writer): allow truthful qualitative evidence
...
Co-Authored-By: GPT-5.6 Codex <noreply@anthropic.com>
Claude-Session: unavailable-in-codex-desktop
```
