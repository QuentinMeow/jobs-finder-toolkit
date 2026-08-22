<!--
One-page result-recording template. Copy to evals/results/<skill>-<git-sha>-<date>.md and fill.
Results are per-machine (network/board state + local model dependent). Tracked for now; may be
gitignored later. Pull tokens/wall-clock from: .venv/bin/python automation/metrics/report.py --by-sha
-->
# Eval result — <skill>

| Field | Value |
|-------|-------|
| Skill | `<skill>` |
| Canary set | `evals/canaries/<skill>.yaml` |
| Run kind | regression baseline / regression pre-merge / A/B |
| Run commit | `<12-char sha>` — where the runs happened, in whatever words are TRUE: a branch tip, a PR head, "plus uncommitted working tree". Informational; nothing checks it |
| Anchor commit | `<12-char sha>` — an ancestor of `main` carrying EXACTLY the pinned bytes below, or `none` |
| Model version | `<claude model id>` |
| Config mode | examples fallback (config.yaml unset) / private overlay mounted |
| Date | `YYYY-MM-DD` |
| Judge | manual / skill-creator comparator / `<judge model + rubric>` |

```eval-pin v1
skill <skill>
pin sha256=<16 hex> bytes=<n> path=skills/<skill>/SKILL.md
pin sha256=<16 hex> bytes=<n> path=skills/<skill>/LESSONS.md
pin sha256=<16 hex> bytes=<n> path=skills/<skill>/reference.md
# Additional top-level Markdown guides in the skill package are inserted here.
pin sha256=<16 hex> bytes=<n> path=evals/canaries/<skill>.yaml
```

**Fill the block by running it, never by hand** (it inserts or refreshes in place, and
leaves the rest of this file alone):

```bash
.venv/bin/python automation/evals/record_pins.py --write evals/results/<this file>.md
# later, to ask whether those bytes are still at HEAD:
.venv/bin/python automation/evals/record_pins.py --report evals/results/<this file>.md
```

Why two commit rows and a digest block. The old single `Git SHA` cell was prose, so
nothing could check it: the honest entries said "`<sha>` + uncommitted working tree",
which is the case where the tested bytes were in **no commit at all** — an ancestry check
on that sha passes while proving nothing about what ran. **Run commit** keeps that honesty
and claims nothing. **Anchor commit** is the checkable half, and `none` is a correct answer
— write it rather than naming a commit whose bytes the block does not match. The block
itself is the measurement: sha256 (first 64 bits) + length of each instruction file the
run was a test of, canary set included, because editing a prompt changes a verdict just as
surely as editing the SKILL.md does. Records are evidence; **never edit an old one to add a
block it never had.**

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `<id>` | | | | | |
| `<id>` | | | | | |
| `<id>` | | | | | |
| `<id>` | | | | | |

Pass rate: `<n_pass>/<n_total>`.

## Verdict

- **Regression:** PASS / FAIL. If FAIL, which canary(ies) + which check regressed, and whether it
  blocks the merge (rubric fail OR large efficiency blow-up vs baseline).
- **Efficiency vs baseline (if comparing):** token / wall-clock / tool-call deltas per canary
  (mean + median from `report.py --by-sha`).

## A/B section (only for run kind = A/B)

- **Pre-registered primary metric:** `<e.g. total_tokens>` — registered on `<date>` BEFORE runs.
- **Variants:** A = `<sha/branch>`, B = `<sha/branch>`. Model pinned: `<model id>`.
- **n paired runs:** `<5-10>`.
- **Efficiency (quantitative):** per-canary paired deltas; overall mean/median delta on the
  primary metric.
- **Quality (directional, blind pairwise):** `<e.g. B preferred 6/8, 2 ties>` — direction only,
  NO significance claim. Judge kappa on calibration set: `<>= 0.6>`.
- **Ship decision:** ship winner as a normal single-purpose commit / no change.

## Stage row (only for run kind = stage A/B — `evals/protocols/stage-benchmarks.md`)

Compact variant for a single-stage matched-pair row. Stage rows compare only against other rows of
the SAME stage + fixture version + model id — state all three.

| Field | Value |
|-------|-------|
| Stage id | `<S1–S9 / D1–D11>` (boundary + fixture per `evals/protocols/stage-map.md`) |
| Fixture | `private/evals/fixtures/<version>/<fixture>/` (version pinned; an edit invalidates the row) |
| Variants (SHA pair) | A = `<baseline sha>`, B = `<lever branch sha>` |
| Model version | `<claude model id>` (pinned; a mid-test change voids the row) |
| Primary metric | `<total_tokens | wall_clock_s>` — registered `YYYY-MM-DD` BEFORE the B runs |
| Decision rule | e.g. "ship B if median `<metric>` drops ≥ X% with every gate still PASS" |
| n paired runs | `<2–3>` |

**Per-pair results** (matched pairs on the same fixture; paired delta = B − A on the same input):

| Pair | Fixture instance | A `<metric>` | B `<metric>` | Δ (B−A) | A tool_calls | B tool_calls |
|------|------------------|--------------|--------------|---------|--------------|--------------|
| 1 | `<id>` | | | | | |
| 2 | `<id>` | | | | | |

Median Δ on the primary metric: `<value / %>`. Secondary (descriptive): `tool_calls`, self-audit
bytes read.

**Gate results (must PASS identically on A and B — gate-first; an efficiency win that fails a gate
is a loss):** `check.py` `<PASS/PASS>` · `--check-metadata` `<ok/ok>` · `--check-locations`
`<match/match>` · handoff validation `<ok/ok>`. Blind pairwise artifact read (`evals/rubrics/judging.md`
with `evals/rubrics/artifact-quality.md`): `<e.g. B non-worse; 2 ties>` — direction only, no
significance claim.

**Failure telemetry:** tool calls A/B `<n/n>`, plus in prose any failed tool calls or retries you
observed, and `not measured` where you did not. There is **no transcript miner** — the fields it
used to feed (failure count by tool, retry classification, tokens burned in retry turns) were
struck from `evals/protocols/stage-benchmarks.md` on 2026-08-02 because no tool produces them.
A run that thrashed on failed calls is still not a clean efficiency win, and a repeated
meaningless retry is a bug to file in `memory/known-issues/` — that is now your judgement from
the transcript, not a number to fill in.

**Artifacts:** stage output for A and B saved under `private/evals/runs/artifacts/<row-id>/` for
the pairwise quality read — the same path `evals/protocols/stage-benchmarks.md` names, inside the
overlay's sanctioned `evals/{canaries,fixtures,runs}/` tree.

**Ship decision:** apply the pre-registered rule — ship B as one revertible commit / no change. A
shipped slate is still confirmed later by one end-to-end confirmation row
(`docs/designs/token-usage-modes/benchmark-scenario.md`).
