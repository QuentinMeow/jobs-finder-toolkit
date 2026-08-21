# Make parallel agent work actually parallel, and make its green results mean something

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: the 2026-08-20 agent-work-lifecycle session — 10 parallel subagents, 15 merged PRs
  (#340-#354). Record: `history/conversations/2026-08-20-agent-work-lifecycle/summary.md`
- **Claimed-by**:

## Goal

Five defects made a ten-agent session behave like a one-agent session with extra steps, and let one
of them report a green build it had never tested. Each item below is independently shippable; do them
in the listed order, which is highest-value first. **None of them requires a new gate** — an open
owner decision (`message-queue/needs-human/decisions/process-weight-what-to-cut.md`) says no new gate
is added while it is open.

## Context

All five were observed, not predicted. Evidence is quoted so the next agent can re-check rather than
trust it.

### 1. A fast gate selector reports ALL GREEN having run 8 of 36 gates

`automation/gates/run_gates.py --impact-from origin/main --jobs 8` is the documented pre-PR command
(`skills/github-workflow/SKILL.md`, §8). When the Git range contains no changes — which is the normal
state right after committing on a freshly-branched worktree — it selects **only the `policy` lane, 8
of 36 gates**, prints `ALL GREEN`, and exits 0.

Measured this session: it never ran `tests-workspace`, the suite covering `automation/workspace/`,
while `automation/workspace/cleanup.py` was being changed. The full run is 33 PASS / 3 SKIP / exit 0,
so nothing was actually broken — but the green light was issued for work it had not tested, and both
the orchestrator and several subagents reported it as verification.

This is the failure shape `memory/lessons/harness/broken-twice-build-the-check.md` already names:
never let a skip or a missing result render as a pass. `run_gates.py:870-874` enforces that for a
missing *binary*; it does not enforce it for a lane that was never selected.

**Wanted:** when `--impact-from` selects a strict subset, the summary must say so in the same breath
as the verdict — e.g. `ALL GREEN (8 of 36 gates; lanes: policy — 28 not selected)` — and must never
render as an unqualified `ALL GREEN`. Consider also: if the range is empty, say that the range is
empty rather than implying the change was assessed.

### 2. Two shared files serialize every parallel branch

`automation/publish/review_ledger.yaml` conflicted on **6 of 6** first-wave branches and on every
branch after. Merging any single PR re-dirtied every other open PR within ~20 seconds; each then
needed a hand resolution, a re-push, a fresh CI run and a merge.

**This is already filed** as `tasks/0_backlog/2026-08-02-structure-aware-merge-for-the-review-ledger`
(P1). Do not duplicate it — this session's measured evidence has been appended to that task. Treat
the ledger as *that* task's scope.

What is NOT filed there: `skills/job-search/filter_variants/corpus.yaml` has the same shape and
conflicted three times, because independent agents each append test cases at the end of one list.
The resolution is identical (keep both sides whole, never a line union), and it should be documented
in one place both files point at.

**Wanted:** a written, one-paragraph resolution procedure for append-only convergence files, and
`corpus.yaml` named alongside the ledger wherever that procedure lives. The procedure is: take the
incoming side's bytes whole, then re-append this branch's authored bytes whole. **Never a line-level
union** (it silently corrupted a row in 2026-08-02) and **never a YAML round-trip** (measured this
session: re-dumping reformatted all 351 historical rows, 1,986 insertions to append 3, destroying the
reviewability of an append-only audit file).

### 3. Subagents collide in shared scratch space and silently work around it

Two agents independently reported it. One: *"another agent overwrote `msg1.txt` mid-session — it now
holds a job-search commit message."* Another: *"Another agent shares the scratchpad directory and
overwrote a file there mid-run; I switched to `c6_`-prefixed filenames."*

Nothing broke, because both invented a private prefix on the spot. There is no convention, so the
next pair may invent the same prefix.

**Wanted:** a stated convention for per-agent scratch paths, in whichever instruction file subagents
actually read. A subdirectory per agent is enough; the point is that it is written down rather than
improvised.

### 4. Line numbers passed between agents go stale within one wave

Wave-1 agents were given exact coordinates (`scoring.py:451`, `search_jobs.py:1424`). By wave 2 those
had moved, because wave-1 work had landed. The wave-2 prompts had to carry an explicit correction:
*"Line numbers have MOVED — locate by function name."*

**Wanted:** a one-line rule that work handed to a subagent identifies code by **function or symbol
name**, with a line number only as a hint that is explicitly marked as possibly stale.

### 5. An upstream agent's finding becomes a downstream agent's false premise

A triage pass marked issue #293 as already fixed, citing a specific code path. A later agent checked
and found that path only fires when one identifier differs from another, which #293's case never
triggers — so the defect was live. It was caught only because the downstream prompt happened to say
*"an earlier triage was wrong and you should not trust it."*

Seven of that triage's verdicts were wrong in total.

**Wanted:** findings passed between agents carry their verification status — confirmed with a
reproduction, or asserted-but-unverified. An unverified upstream claim must be re-checked by the
agent acting on it, not inherited as fact.

### Related debt this session created, for whoever picks this up

To stop agents colliding on documentation and tripping the eval gate, every subagent was forbidden
from editing `SKILL.md`, `LESSONS.md`, or `reference.md`. That worked — and left **at least 8 backlog
tasks recording documentation that now contradicts shipped code**, with none done. See
`2026-08-20-job-search-docs-behind-the-filter-pipeline-fixes`,
`2026-08-20-document-skills-diff-precision-rules`,
`2026-08-20-document-search-json-provenance-fields`.

The pattern is worth naming: banning doc edits for merge safety is correct **only if** one agent owns
the documentation pass at the end. That closing pass did not happen.

## Definition of done

1. `run_gates.py` never prints an unqualified `ALL GREEN` for a partial selection; the verdict line
   carries the selected count out of the total and names the lanes not run. A test asserts that an
   empty `--impact-from` range does not render as a full-suite pass.
2. The append-only convergence procedure is written in one place, names both `review_ledger.yaml` and
   `filter_variants/corpus.yaml`, and states the two rejected resolutions (line union, YAML
   round-trip) with the reason each is rejected.
3. A per-agent scratch-path convention exists in an instruction file subagents read.
4. A rule exists that code handed between agents is identified by symbol name, not line number.
5. A rule exists that a finding passed between agents carries whether it was verified, and that an
   unverified finding is re-checked before it is acted on.
6. Items 3-5 are added as **delta-only** edits (`AGENTS.md:270-271` — harness self-edits never rewrite
   a file wholesale), and the instruction-budget gate stays green
   (`automation/metrics/instruction_budget.py --strict`; note `skills/github-workflow/SKILL.md` sits at
   599 of 600 lines, so it cannot absorb new text).
7. No new gate is added, and the PR body says so explicitly, because
   `process-weight-what-to-cut.md` is open and its default path forbids one.
8. `automation/gates/run_gates.py --lane maintenance --lane policy --jobs 8` exits 0. Name the lanes
   explicitly — do not use `--impact-from` to verify a change to `run_gates.py`, for the reason this
   task exists.
