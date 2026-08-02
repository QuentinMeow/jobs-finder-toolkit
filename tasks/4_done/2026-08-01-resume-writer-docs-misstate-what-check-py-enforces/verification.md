# Verification — 2026-08-01-resume-writer-docs-misstate-what-check-py-enforces

Run on branch `docs/resume-writer-gate-truth` in a worktree of `main` at `f360aec`, with
`.venv/bin/python`. `config.yaml` is absent there, so every run uses the fictional
"Jordan Rivers" persona from `config.example.yaml`; the `config:` banner line is trimmed below.
No owner data under `private/` was read or written. Probe folders were copies under the
gitignored `local/scratch/`.

## Item 4 — the `jd.md` literal in `check.py:417` can never match

`layout.find_jd_files` globs `source/*.md` and keeps only names starting with `jd-`, so the
bare filename the warning names is never read:

```
$ .venv/bin/python local/scratch/probe_gate_truth.py
files on disk: ['jd.md']
find_jd_files -> []
after adding JD-role.md -> ['JD-role.md']
```

Fixed to name `source/JD-*.md` only.

## Item 1 — the documented 1-6 direct-bullet range is not what `check_structure` allows

The shipped example baseline is projects-only. One direct bullet — inside the documented range —
FAILs:

```
$ .venv/bin/python local/scratch/probe_gate_truth.py
example baseline direct bullets: 0
direct bullets in tailored.yaml: 1 (inside the documented 1-6 range)
FAILS: ['employer 1 (Northwind Systems) added direct role bullets: 1 vs baseline 0']
```

## Item 2 — a letter written to the documented per-paragraph minimums FAILs the gate

A copy of the example folder whose letter was trimmed to `reference.md`'s stated minimums
(70 + 80 + 25 words):

```
$ .venv/bin/python skills/resume-writer/scripts/check.py local/scratch/app-minletter/
  FAIL: cover letter for 'Senior Software Engineer, Platform' body is 175 words — outside the
        200-450 range (target ~250-400). Expand thin paragraphs or trim padding.
  → 1 check(s) FAILED — fix tailored.yaml and re-render
EXIT=1
```

The corrected minimums (100 + 110), with the optional closing left out, pass:

```
$ .venv/bin/python skills/resume-writer/scripts/check.py local/scratch/app-newmin/
paragraph word counts: [100, 110] total 210
  ✓ all checks passed (0 warning(s))
EXIT=0
```

## Item 3 — a folder with zero cover letters exits 0 today

Copy of the example folder with its bundled `.txt` deleted:

```
$ .venv/bin/python skills/resume-writer/scripts/check.py local/scratch/app-noletter/
  WARN: no bundled Jordan_Rivers_Software_Engineer_Application_Senior_Software_Engineer_Platform.txt
        (COVER LETTER section) found for 'Senior Software Engineer, Platform' — every JD needs its own cover letter
  ✓ all checks passed (1 warning(s))
EXIT=0
```

Unchanged by this task, by design. Documented as a limitation in `SKILL.md`, `reference.md`, and
`check.py --rules`; the promotion to FAIL is filed at
`message-queue/needs-human/decisions/missing-cover-letter-warn-or-fail.md`.

## Gates (all at working tree over `f360aec`)

```
$ .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests
Ran 98 tests in 44.027s
OK
EXIT=0

$ .venv/bin/python skills/resume-writer/scripts/render.py examples/applications/6_drafted/example-corp-senior-software-engineer/
  ✓ all checks passed (0 warning(s))
EXIT=0

$ .venv/bin/python automation/gardener/verify_links.py
  OK: 3129 references, the skill symlinks and the vendored copies verified.
EXIT=0

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
skills/resume-writer/SKILL.md      472  33115  8278  600  ok
skills/resume-writer/LESSONS.md    106   8314  2078  160  ok
EXIT=0

$ .venv/bin/python automation/gates/run_gates.py
ALL GREEN (29 gates, 2 skipped: reconciler-require-roots, verify-links-require-roots)
EXIT=0
```

`example-render` and the standalone render rewrite the four tracked example DOCX/PDF artifacts
(binary output is not byte-reproducible); reverted with `git checkout -- examples/` both times, so
they are not in this branch's diff.

## Eval gate

Skipped with a recorded rationale. Under `evals/README.md`'s risk-based rule this edit is
"correcting paths, flags, or labels to match code reality" — 2 instruction files of one skill,
21 added / 10 removed lines (5 of them numeric substitutions), no gate added/removed/rerouted,
no step or deliverable redefined, no file restructured. The accumulated state is annotated onto
`tasks/0_backlog/2026-07-31-resume-writer-canary-run-for-gate-honesty`, which is the open
MUST-run debt for this skill.
