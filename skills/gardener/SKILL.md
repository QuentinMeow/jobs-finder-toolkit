---
name: gardener
visibility: public
description: Periodic memory hygiene for the toolkit's agent-memory zones — expire stale discovery scans, prune old search-log rows, flag stale/duplicate LESSONS, verify links, and recompute the pipeline funnel. Use for weekly upkeep or when the user says "clean up memory", "expire stale discoveries", "garden the repo", "prune the logs", "run the gardener", or asks to measure the pipeline/memory health. Every routine is DRY-RUN by default and MOVES rather than deletes.
---

# Gardener — Memory Hygiene

The gardener keeps this repo's **agent-memory zones** from growing without bound
(maintainer-only design doc — overlay-mounted, absent in contributor checkouts:
`private/docs/03-folder-structure-and-memory.md`
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
- **Report-only routines don't act.** `lessons-report`, `card-staleness`,
  `roadmap-staleness`, `skill-drift`, `store-report`, `queue-hygiene`, `workspace-hygiene` and `verify-links` never mutate anything, and `--apply` on one only prints
  `note: '<routine>' is report-only` — promotion/demotion of a lesson is a **separate
  human-reviewed commit** (self-evolution contract), and store pruning is `gc_store.py`.
- Always use the repo venv: `.venv/bin/python`.

## Routines

| Routine | What it does | Mode | Guardrail |
|---------|--------------|------|-----------|
| `expire-discoveries` | Discovery scans older than `discovery_ttl_days` (30) → move to `archive/`; raw scans >`discovery_archive_days` (14) flagged for review | dry-run; `--apply` moves | move-not-delete; per-file plan; index entry appended |
| `compact-logs` | `company-search-log.yaml` rows older than `search_log_prune_days` (90) → prune; the append-only `applications-log.jsonl` is **never compacted** — rewriting it would restore the truncation this log exists to prevent | dry-run; `--apply` writes a compacted copy + runs `--sync-log`, which now *appends* changed postings | never edits either live log in place |
| `lessons-report` | Flag LESSONS sections whose `last_confirmed` > `lesson_confirm_days` (180) or that are untagged; flag near-duplicate bullets within a LESSONS.md and vs its SKILL.md | **report-only** | human ratifies any promotion/deletion |
| `card-staleness` | Compare the source hashes recorded in the resume-writer tailoring card (`config.tailoring_card_path()`) with current profile/baseline/story-bank hashes; flag the card when a source drifted | **report-only** | rebuild is the skill's job (`build_tailoring_card.py --force`), never the gardener's |
| `roadmap-staleness` | Flag `docs/roadmap/current-state.md` when its `Last-updated` date is more than 30 days old, so the document the read order sends agents to for "what is true today" gets re-confirmed | **report-only** | always exits 0 — this is deliberately NOT a gate: the reconciler's `roadmap-dated` check fails a commit on a MALFORMED date (missing / unparseable / future), age never does |
| `skill-drift` | Flag skill tokens in the baseline resume (`config.baseline_path()`) whose spelling is not in the profile's canonical Approved/Weak/Never lists, so a mis-spelled skill is caught in upkeep instead of mid-render by `check.py` | **report-only** | fixing a spelling (in the baseline, or by adding the skill to the profile lists) is a human edit; always exits 0, and reports "nothing to check" when the baseline or profile is absent |
| `store-report` | Raw-data-layer store health per domain under `config.data_root()`: zone sizes, manifest/blob counts, the four blob availability states, orphaned blobs, manifest-less fetch dirs, torn JSONL tails, stale locks, cursor ages, triage + annotation-conflict backlogs, and the `validate_store` result | **report-only** | NEVER prunes — pruning is `automation/store/gc_store.py`, run deliberately. Exits non-zero only on a `validate_store` failure (corrupt blob / schema violation) |
| `queue-hygiene` | Aging items in the coordination queues: `message-queue/needs-human/reviews/` past 30 days, `decisions/` pending past 21 days, tasks dwelling past 14 days in `1_in-progress`/`3_in-review`, and parked decisions whose `Revisit when` names a stage its design's `execution-plan.md` marks SHIPPED | **report-only** | always exits 0 — age is a prompt for judgement, never a gate (the reconciler keeps the correctness half: `queue-schema` + `task-structure`). No-ops when `message-queue/` and `tasks/` are absent (the public export ships neither). For `private/` mirrors it prints **counts only, never an item name** — see below |
| `workspace-hygiene` | Local branches and worktrees nobody came back to: branches whose content is already in main with no worktree, branches WEDGED by a worktree registration that outlived its directory (`git switch` refuses them and `git gc` will not clear the metadata for three months), and unmerged branches idle past 14 days | **report-only** | always exits 0 — age is a prompt for judgement, never a gate. Merge state is LOCAL and unfetched, and the report says so beside every number; retiring anything is the separate `automation/workspace/cleanup.py` (dry-run, writes a script, deletes nothing). `github-workflow` owns the mandatory fresh-main sweep of finished local `codex/` and `claude/` work around GitHub operations. For `private/` this report prints **counts only, never a branch name** |
| `verify-links` | Backticked toolkit paths AND `[text](path)` markdown links resolve — in the overlay's tracked `.md` too when it is mounted; heading anchors match a real heading; skill symlinks resolve; `sync_vendored.py --check` | report-only; **exit 1 on break** | runs in CI and pre-commit; fails on a broken link / vendor drift |
| `self-measure` | Recompute the funnel (discovered/drafted/applied/in_progress/rejected/ignored) + LESSONS staleness + instruction-budget summary | dry-run; `--apply` writes `metrics.yaml` | writes only into the overlay (`config.candidate_dir()/metrics.yaml`), never the toolkit |

Retention windows come from the optional `retention:` block in `config.yaml`
(`config.example.yaml` documents the defaults); unset keys fall back to the values above.

## Commands

```bash
# Run ALL ELEVEN routines in dry-run (safe weekly sweep). Fixed order:
# self-measure, expire-discoveries, compact-logs, lessons-report, card-staleness,
# roadmap-staleness, skill-drift, store-report, queue-hygiene, workspace-hygiene,
# verify-links —
# verify-links LAST so its exit code is the overall gate. --apply is ignored under
# --all; every routine runs dry.
.venv/bin/python automation/gardener/gardener.py --all

# A single routine (dry-run)
.venv/bin/python automation/gardener/gardener.py expire-discoveries
.venv/bin/python automation/gardener/gardener.py compact-logs
.venv/bin/python automation/gardener/gardener.py lessons-report
.venv/bin/python automation/gardener/gardener.py card-staleness
.venv/bin/python automation/gardener/gardener.py roadmap-staleness
.venv/bin/python automation/gardener/gardener.py skill-drift
.venv/bin/python automation/gardener/gardener.py store-report
.venv/bin/python automation/gardener/gardener.py queue-hygiene
.venv/bin/python automation/gardener/gardener.py workspace-hygiene
.venv/bin/python automation/gardener/gardener.py verify-links
.venv/bin/python automation/gardener/gardener.py self-measure

# Act on a plan (ONLY after the user reviews and approves the dry-run):
.venv/bin/python automation/gardener/gardener.py expire-discoveries --apply
.venv/bin/python automation/gardener/gardener.py compact-logs --apply
.venv/bin/python automation/gardener/gardener.py self-measure --apply

# Each routine also runs standalone, e.g.
.venv/bin/python automation/gardener/verify_links.py
.venv/bin/python automation/gardener/verify_links.py --no-overlay      # what CI sees
.venv/bin/python automation/gardener/verify_links.py --list-unrecognised
# Prove a move broke no link: snapshot before, compare after (renames are followed).
.venv/bin/python automation/gardener/verify_links.py --baseline local/links-before.json
.venv/bin/python automation/gardener/verify_links.py --compare  local/links-before.json
```

Workflow: run dry-run → show the user the plan → get explicit approval → run the matching
`--apply`. `verify-links` and `lessons-report` are safe to run anytime (they never mutate).

**`queue-hygiene` and `workspace-hygiene` output is safe to paste; `verify-links` output is not.** The two routines take
opposite stances on the overlay on purpose. `queue-hygiene` reports the private mirrors as **counts
only** — never a filename — because a private queue item's slug names the owner's real pipeline, so
the filename is the content (rationale + the reason there is no opt-in detail flag:
`PRIVATE_POLICY` in `automation/gardener/queue_hygiene.py`).

**`verify-links` output can name `private/` paths** when the overlay is mounted — it reads the
overlay's markdown, which is the only way links inside it are ever checked. That report is not a
tracked file, so the leak guard never inspects it: never paste a run into a PR description, a
commit message, or any other public text. `--baseline` refuses to write outside a git-ignored
path for the same reason; keep snapshots in `local/`.
