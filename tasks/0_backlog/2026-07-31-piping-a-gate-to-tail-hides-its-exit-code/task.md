# Piping a gate to `tail` hides its exit code, and four independent runs were fooled

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: cross-run pattern found while judging the job-search canary set, 2026-07-31 —
  four of four live runs made the identical mistake
- **Claimed-by**:

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

## Definition of done

- [ ] Every documented example that pipes a gate's output either stops piping it, sets
      `pipefail`, or reads `${PIPESTATUS[0]}` — one convention, applied consistently
- [ ] `grep -rn '| *tail\|| *head' skills/ docs/ automation/` reviewed; each hit judged as
      "gate, must not lose status" or "display only, fine"
- [ ] `AGENTS.md` or the relevant skill states the routing rule for a mandatory gate that is
      red outside your scope — which queue it goes to, and whether you may proceed
- [ ] The new fenced-command checker (`verify_links.py`) is considered as an enforcement
      point: it already parses documented commands, so a piped-gate pattern is detectable
      there rather than by review
