# Token-usage modes for job search + application drafting

**Status:** proposal (2026-07-20). Nothing here is implemented; this records a
measured baseline, the cost taxonomy, and four candidate designs.

## Problem

A routine "search then draft a couple of applications" run, fanned out to subagents
per the toolkit's own workflow, costs hundreds of thousands of tokens — most of them
spent on things that don't improve search or writing quality: re-reading the same
instruction files in every agent, re-running identical network fetches, dumping raw
tables/JSON into context, and reading pipeline source code to answer questions a doc
line could answer. We want to cut token usage substantially **without reducing job
search quality or resume/cover-letter quality**, and (optionally) expose an explicit
cheap-by-default / thorough-on-demand switch.

## Measured baseline (live experiment, 2026-07-20)

One live run on the owner's real config: 1 search subagent ("postings from the last
2 hours" — genuinely empty at 2h; widened stepwise to 3 days) + 2 drafting subagents
(one application each, end-to-end through render + validation). All three agents ran
a mid-tier model and produced passing artifacts.

| Agent | Tokens | Tool calls | Wall clock | Outcome |
|---|---:|---:|---:|---|
| job search | 108,491 | 35 | ~11.3 min | ranked shortlist, 2 handoffs; 7 full pipeline invocations |
| drafting A | 169,471 | 67 | ~12.3 min | full app folder, check.py PASS, 3 render cycles |
| drafting B | 159,311 | 57 | ~12.5 min | full app folder, check.py PASS, 3 render cycles |
| **total (subagents)** | **437,273** | **159** | — | + orchestrator session on top |

### Where the tokens went (from the agents' own file/command audits)

1. **Instruction boot tax, paid per agent (~95k total, ~22%).** Each drafting agent
   read ~155 KB (~39k tokens) of instructions + candidate context before its first
   useful step: `AGENTS.md` (40 KB), resume-writer `SKILL.md`/`LESSONS.md`/`reference.md`
   (59 KB), application-tracker `SKILL.md` (15 KB), candidate profile + baseline
   (17 KB), story bank (24 KB). The search agent read ~73 KB (~18k tokens). This
   duplicates per agent in a fan-out. (Sizes: `scripts/metrics/instruction_budget.py`.)
2. **Repeated identical fetches.** Widening the freshness window (0.084 → 1 → 3 days)
   plus a `--json-out` re-run cost **7 full pipeline invocations**, each re-fetching
   ~12k postings from 100+ boards and re-printing output into context. The fetches
   were identical; only the filter changed. (A missing optional dependency the agent
   had to diagnose and install accounted for 3 of the 7.)
3. **Source-code archaeology (~25–40k).** All three agents read pipeline source
   (`scoring.py`, `location.py`, `check.py`, `job_metadata.py`, `estimate_layout.py`)
   to answer "why did X happen / what format does Y want". One read caught a real bug
   (below); the agents' own hindsight audits flag most of the rest as skippable.
4. **Extra render cycles from a latent baseline collision.** Both drafting agents
   burned 2 of their 3 render cycles on the same cause: the baseline resume's own
   wording collides with a Never-listed skill name (a phrase-vs-tool false positive),
   in two places. Fixing the baseline wording once removes ~1–2 cycles from *every*
   future application.
5. **Duplicate + lossy JD fetching.** The search agent fetched JDs via an
   AI-summarizing web tool for verification; each drafting agent then re-fetched the
   same URL. Three fetches per posting, none saved verbatim on first touch.
6. **Full-fidelity candidate context regardless of need.** Both drafting agents read
   the full 24 KB story bank; one judged afterward that a header skim would have
   sufficed for its JD.

### Quality findings the experiment surfaced (why "cheap" can also mean "better")

The expensive behaviors were not buying quality on the routine path — but the
*verification* behaviors were: manual JD reads found that the market-scraper `remote`
flag was systemically wrong this run (every match tagged remote, including explicit
hybrid/on-site roles) and that a visa heuristic `yes` was a negated-phrase false
positive. Both handed-off postings would normally have been rejected on policy. Any
token-saving design must keep (ideally script-ify) posting verification — the tokens
to cut are instruction re-reads, refetches, and archaeology, not the checking.

## The four approaches

| # | Approach | Savings lever | Quality risk | Effort |
|---|---|---|---|---|
| 1 | [Trim/tier the instruction stack](approach-1-trim-instruction-stack.md) | boot tax (~30–50% of it) | medium (eval-gated rewrite of safety-critical docs) | medium |
| 2 | [Script-first handoff](approach-2-script-first-handoff.md) | refetches, transcription, dumps, candidate-context size | ~none (mechanical steps only) | medium |
| 3 | [Explicit `token_saving`/`full` modes](approach-3-two-modes.md) | research depth, iteration, subagent use | medium (default path is the cheap one) | high |
| 4 | [Staged hybrid — **recommended**](approach-4-hybrid-recommended.md) | all of the above, sequenced risk-free-first | low → contained | staged |

**Recommendation:** Approach 4 — ship Approach 2's mechanics first (pure wins:
fetch cache + `--refilter`, `handoff.py` scaffolding, compact output, tailoring
card, verbatim JD fetcher), then the instruction tiering, and only then the explicit
mode switch, which by that point is a thin composition of existing pieces.
**Default mode: `token_saving`;** `full` is opt-in for deep research and
pre-submission polish. Hard gates (blacklist/log pre-flight, location gate, schema
validation, `check.py`, no-fabrication rules) run identically in both modes.

### Projected effect on the measured run (estimates, to be re-measured per stage)

| Stage | Search | 2 drafts | Total | vs baseline |
|---|---:|---:|---:|---:|
| Baseline (measured) | 108k | 329k | ~437k | — |
| + Stage 1 (script-first) | ~45k | ~200k | ~245k | −44% |
| + Stage 2 (instruction tiering) | ~35k | ~150k | ~185k | −58% |
| + Stage 3, `token_saving` default (no search subagent, card-only context, capped cycles) | ~8k | ~110k | ~120k | **−73%** |
| Stage 3, `full` mode | ≈ baseline, minus Stage 1–2 savings | | ~200k | −54% |

## How to re-measure

- Per-subagent totals come from the harness's task-completion usage line
  (tokens/tool-calls/duration); have each agent self-audit files read (`wc -c`) and
  large command outputs, as in this experiment.
- Instruction-file sizes: `scripts/metrics/instruction_budget.py`.
- The benchmark scenario is "one search + two drafted applications, end-to-end";
  re-run it after each stage and append a row to the table above.

## Follow-ups outside this design (found during the experiment)

- Fix the baseline resume wording that collides with a Never-listed tool name (saves
  render cycles fleet-wide; two occurrences).
- LESSONS.md candidates (eval-gated edits, not yet made): market-scraper `remote`
  flag is unreliable — verify workplace from the real JD before handoff; visa
  heuristic can false-positive on negated sponsorship phrases.
- The optional scraper dependency was missing from the venv while docs said it was
  installed — reconcile (`requirements.txt` vs docs), since a silently degraded
  stage-1 fetch cost 3 redundant pipeline runs before diagnosis.
