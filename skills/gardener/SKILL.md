---
name: gardener
visibility: public
description: Periodic memory hygiene for the toolkit's agent-memory zones — expire stale discovery scans, prune old search-log rows, flag stale/duplicate LESSONS, verify links, and recompute the pipeline funnel. Use for weekly upkeep or when the user says "clean up memory", "expire stale discoveries", "garden the repo", "prune the logs", "run the gardener", or asks to measure the pipeline/memory health. Every routine is DRY-RUN by default and MOVES rather than deletes.
---

# Gardener — Memory Hygiene

The gardener keeps this repo's **agent-memory zones** from growing without bound
(maintainer-only design doc — overlay-mounted, absent in contributor checkouts:
`private/docs/harness-engineering-and-repo-evolution/03-folder-structure-and-memory.md`
§5, and the "Memory Map" in `AGENTS.md`). Memory has promotion (MEMORY→LESSONS→SKILL)
but the gardener supplies the missing half: **forgetting** — TTL expiry, log pruning,
and staleness/duplicate flagging.

## When to Use

- Weekly upkeep ("garden the repo", "run the gardener", "weekly memory cleanup").
- "Clean up memory", "expire stale discoveries", "prune the search log".
- "How healthy is my pipeline / memory?" → `self-measure`.
- At the start of a job-search run (expire old scans first) or after a big search.

## Guardrails (inviolable)

- **Dry-run by default.** Every routine prints a plan/diff and changes nothing unless
  you pass `--apply`.
- **Move, never delete.** Stale discoveries are MOVED to a sibling `archive/` (soft-delete);
  the live search log is never edited in place — a `*.compacted.yaml` copy is written for review.
- **Human confirms `--apply`.** Never run `--apply` on the user's behalf without explicit
  approval. If a run would touch **more than ~10 items**, surface the plan and get a fresh OK first.
- **Report-only routines don't act.** `lessons-report` and `verify-links` never mutate anything —
  promotion/demotion of a lesson is a **separate human-reviewed commit** (self-evolution contract).
- Always use the repo venv: `.venv/bin/python`.

## Routines

| Routine | What it does | Mode | Guardrail |
|---------|--------------|------|-----------|
| `expire-discoveries` | Discovery scans older than `discovery_ttl_days` (30) → move to `archive/`; raw scans >`discovery_archive_days` (14) flagged for review | dry-run; `--apply` moves | move-not-delete; per-file plan; index entry appended |
| `compact-logs` | `company-search-log.yaml` rows older than `search_log_prune_days` (90) → prune; `applications-log.yaml` regenerated via `status.py --sync-log` | dry-run; `--apply` writes a compacted copy + runs sync | never edits the live log in place |
| `lessons-report` | Flag LESSONS sections whose `last_confirmed` > `lesson_confirm_days` (180) or that are untagged; flag near-duplicate bullets within a LESSONS.md and vs its SKILL.md | **report-only** | human ratifies any promotion/deletion |
| `card-staleness` | Compare the source hashes recorded in the resume-writer tailoring card (`<applications_root>/0_profile/tailoring-card.md`) with current profile/baseline/story-bank hashes; flag the card when a source drifted | **report-only** | rebuild is the skill's job (`build_tailoring_card.py --force`), never the gardener's |
| `verify-links` | Backticked toolkit paths exist; tool-compatibility skill symlinks resolve; `sync_vendored.py --check` | report-only; **exit 1 on break** | fails CI on a broken link / vendor drift |
| `self-measure` | Recompute the funnel (discovered/drafted/applied/in_progress/rejected/ignored) + LESSONS staleness + instruction-budget summary | dry-run; `--apply` writes `metrics.yaml` | writes only into the overlay (`0_profile/metrics.yaml`), never the toolkit |

Retention windows come from the optional `retention:` block in `config.yaml`
(`config.example.yaml` documents the defaults); unset keys fall back to the values above.

## Commands

```bash
# Run every routine in dry-run (safe weekly sweep)
.venv/bin/python automation/maintenance/gardener/gardener.py --all

# A single routine (dry-run)
.venv/bin/python automation/maintenance/gardener/gardener.py expire-discoveries
.venv/bin/python automation/maintenance/gardener/gardener.py compact-logs
.venv/bin/python automation/maintenance/gardener/gardener.py lessons-report
.venv/bin/python automation/maintenance/gardener/gardener.py card-staleness
.venv/bin/python automation/maintenance/gardener/gardener.py verify-links
.venv/bin/python automation/maintenance/gardener/gardener.py self-measure

# Act on a plan (ONLY after the user reviews and approves the dry-run):
.venv/bin/python automation/maintenance/gardener/gardener.py expire-discoveries --apply
.venv/bin/python automation/maintenance/gardener/gardener.py compact-logs --apply
.venv/bin/python automation/maintenance/gardener/gardener.py self-measure --apply

# Each routine also runs standalone, e.g.
.venv/bin/python automation/maintenance/gardener/verify_links.py
```

Workflow: run dry-run → show the user the plan → get explicit approval → run the matching
`--apply`. `verify-links` and `lessons-report` are safe to run anytime (they never mutate).
