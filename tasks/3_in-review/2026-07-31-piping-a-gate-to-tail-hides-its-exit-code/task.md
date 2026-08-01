# Piping a gate to `tail` hides its exit code, and four independent runs were fooled

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: cross-run pattern found while judging the job-search canary set, 2026-07-31 —
  four of four live runs made the identical mistake
- **Claimed-by**: agent, 2026-07-31 (branch `wip/34-gate-exit-code-discipline`)

## Goal

Stop a red gate reading as green because its output was piped, and say what an agent
should do when a mandatory gate fails outside the scope of its task.

## Context

Two separate defects, found together because they compound.

**1. The exit code is lost in the pipe.** Every one of the four live canary runs that
invoked the filter-variant gate did some form of:

```bash
.venv/bin/python skills/job-search/scripts/validate_filter_variants.py ... | tail -5
echo "EXIT=$?"
```

In a POSIX shell `$?` after a pipeline is the exit status of the **last** command, so this
reports `tail`'s success, not the gate's. All four read a reassuring `EXIT=0` from a gate
that was exiting 1. All four happened to notice anyway, from the text of the output — but
that is luck, not a check.

Four independent sessions making the same mistake is a property of the instructions, not of
four agents. Wherever the docs demonstrate running a gate through a pipe, they teach this.
`set -o pipefail`, `${PIPESTATUS[0]}`, or simply not piping a gate would each fix it; pick
one and make the documented examples consistent.

**2. Nobody knows what to do with an out-of-scope red gate.** The same failing gate was
handled four different ways across the four runs: one filed a `needs-agent/retries/` item,
one filed a `0_backlog` task, one filed an unrelated task, and one did nothing. Each is
defensible; the spread is the problem. The contract says never bypass a gate, but it does
not say what to do when a gate that is mandatory for the repo is red for reasons the current
task did not cause and must not fix.

**2026-07-31 update — the sample is now seven of nine.** A second, independent canary set
(`evals/results/job-search-40871e6799a0-20260731-stack-head.md`, "Cross-run observations")
reproduced it three times in five runs, on top of the four-of-four above. That record adds a
second trap this task's original text did not name: one run reached for the bash idiom
`${PIPESTATUS[0]}`, but **this shell is zsh**, where the array is `$pipestatus` and is
**1-indexed** — the bash spelling expands to the empty string, which reads as "nothing wrong".
The same record confirms the second defect independently: the same red gate was again handled
several different ways because nothing says what to do with one that is out of scope.

## Definition of done

- [x] Every documented example that pipes a gate's output either stops piping it, sets
      `pipefail`, or reads `${PIPESTATUS[0]}` — one convention, applied consistently
      → **vacuously true, and that is the finding**: the sweep found **zero** piped gates in
      the tracked tree. The defect is in ad-hoc shell agents type, not in tracked examples, so
      the fix is a stated convention rather than an edit sweep. Convention chosen:
      **do not pipe a gate — redirect to a file in `local/` and read the file.**
- [x] `grep -rn '| *tail\|| *head' skills/ docs/ automation/` reviewed; each hit judged as
      "gate, must not lose status" or "display only, fine" → 11 hits, **0 gates**, 11 display /
      probe / markdown-table false positives, all left alone. `.github/` (the authoritative gate
      list) contains no pipe at all. Per-hit table in `verification.md`.
- [x] `AGENTS.md` or the relevant skill states the routing rule for a mandatory gate that is
      red outside your scope — which queue it goes to, and whether you may proceed
      → new **Guardrails** bullet "A gate that is red outside your scope". Put in `AGENTS.md`
      rather than a skill because the defect is not job-search-specific and hard invariants live
      in the contract by its own Folder-Scoped Context rule.
- [x] The new fenced-command checker (`verify_links.py`) is considered as an enforcement
      point: it already parses documented commands, so a piped-gate pattern is detectable
      there rather than by review → **considered and declined, on a measurement.** A rule
      "a python invocation that is not the last stage of a pipeline" fires 9 times on this tree:
      0 real defects, 3 false positives in the hard-fail REFERENCE tier (a literal `|` inside a
      `<applied|in_progress|rejected>` placeholder is not a pipe), 5 legitimate display pipes,
      and 1 quotation of the bug inside this very task file. Numbers in `verification.md`.
