# Approach 1 — Trim and tier the instruction stack (single mode)

**Strategy:** Attack the largest fixed cost — the instruction files every agent must
read before doing any work — without introducing any mode switch. Same behavior for
every run, just a cheaper preamble.

## The problem it targets

Every subagent that touches a skill pays a fixed "boot tax" before its first useful
token (est. tokens = bytes / 4, from `scripts/metrics/instruction_budget.py`):

| File | ~tokens | Read by |
|---|---|---|
| `AGENTS.md` | ~10,000 | every agent, every skill |
| `resume-writer/SKILL.md` | ~9,200 | every drafting agent |
| `resume-writer/reference.md` | ~3,900 | every drafting agent |
| `job-search/SKILL.md` | ~6,800 | every search agent |
| `application-tracker/SKILL.md` | ~3,800 | drafting agents (meta.yaml schema) |
| LESSONS.md files | ~1,500–1,700 each | every agent of that skill |
| Candidate profile + baseline + story bank | ~10,000+ | every drafting agent |

A fan-out of N subagents pays this N times. In the measured baseline run (see
[README](README.md)), instruction/context loading was roughly a third of each
agent's total tokens.

## How it works

1. **Quickstart header per SKILL.md.** The first ~50 lines of each SKILL.md become a
   self-sufficient "standard path" — the exact commands, the folder layout, the hard
   gates, and a rule: *read the section named X only when situation Y arises*. The
   remaining body is restructured so each section is loadable on demand (agents Read
   specific line ranges or sections, not the whole file).
2. **Split `AGENTS.md` into core + annexes.** A ~120-line core contract (traceability,
   no-fabrication, leak guard, folder conventions pointer, subagent budget) that every
   agent reads, plus per-topic annex files (`docs/agents/` or in-file anchors) read only
   when relevant. The core keeps hard guardrails; the annexes keep the exposition.
3. **Demote narrative to reference.** Rationale, history, and "why this design"
   paragraphs move from SKILL.md/AGENTS.md into `reference.md`/`docs/`, which agents
   read only when they hit the corresponding decision.
4. **Ratchet the budgets.** `instruction_budget.py` already enforces per-file line
   budgets. Lower them (e.g. AGENTS.md core ≤ 150 lines, SKILL.md quickstart ≤ 60)
   so the trim can't silently regrow.

## Pros

- **Every consumer benefits** — subagents, interactive sessions, any harness. No new
  concepts, no config, no second code path.
- **Uses tooling that already exists** (`instruction_budget.py` budgets, canary evals
  as the safety net for instruction edits).
- **No quality fork:** there is still exactly one documented behavior; nothing is
  skipped, only loaded lazily.

## Cons

- **Every instruction edit is eval-gated** (per CONTRIBUTING, SKILL.md/LESSONS.md
  edits require the skill's canary run) — this is a large, high-stakes rewrite of the
  most safety-critical files (fabrication rules, leak guard, tailoring limits), and a
  compression mistake degrades *every* run, not just cheap ones.
- **Limited ceiling.** Realistically saves 30–50% of the boot tax (~10–15k tokens per
  drafting agent). It does nothing about the variable costs that dominated the
  measured run: repeated search fetches, raw JSON/table dumps into context, source-code
  archaeology, multi-cycle render loops, and full profile/story-bank reads.
- **Lazy loading is advisory.** An agent can still read everything (some will); the
  saving depends on agents honoring "read on demand" instructions.
